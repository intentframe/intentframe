"""Email sync daemon with a single-owner lifecycle.

``SyncDaemon`` is the only way to run the background sync.  Both the CLI
entry-point and tests use the same three-step interface::

    daemon = SyncDaemon(config)
    await daemon.start()        # connect, initial sync, spawn tasks
    daemon.request_stop()       # signal + kill IDLE sockets instantly
    await daemon.wait_stopped() # gather tasks, close DB

PID file is written to ``EMAIL_HOME/daemon.pid`` on start and removed
on stop for terminal-based lifecycle management.
"""

from __future__ import annotations

import asyncio
import os
import signal
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from .config import AccountConfig, ServiceConfig
from .db import init_db, write_event
from .folders import folder_for_role
from .imap_connection import (
    force_close,
    get_or_discover_folders,
    get_provider,
)
from .sync import (
    run_idle,
    sync_all_folders,
    sync_folder,
    upgrade_all_folders_bodies,
    verify_integrity,
)

log = structlog.get_logger()

PERIODIC_SYNC_INTERVAL = 5 * 60  # 5 minutes


class SyncDaemon:
    """Owns the entire daemon lifecycle: DB, tasks, IDLE connections."""

    def __init__(self, config: ServiceConfig, *, body_sync_days: int = 90) -> None:
        self._config = config
        self._body_sync_days = body_sync_days
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._idle_connections: list[Any] = []
        self._db: Any | None = None
        self._health: dict[str, AccountHealth] = {}
        self._started_at: str | None = None

    # ── Lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialise DB, run priority sync, spawn background tasks."""
        self._db = await init_db(self._config.db_path)
        self._config.attachments_dir.mkdir(parents=True, exist_ok=True)
        self._started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        for account in self._config.accounts:
            self._health[account.email] = AccountHealth(email=account.email)
            await _upsert_account_row(self._db, account)

        # Priority pass: full content for INBOX + Sent (recent window)
        # Uses a single IMAP connection via ConnectionProvider.
        for account in self._config.accounts:
            try:
                provider = get_provider(account)
                async with provider.connection() as mb:
                    folders = await get_or_discover_folders(mb, account.email)
                    await _upsert_folders(self._db, account.email, folders)

                    priority_total = 0
                    for role in ("inbox", "sent"):
                        name = folder_for_role(folders, role)
                        if not name:
                            continue
                        count = await sync_folder(
                            account, name, self._db, self._config.attachments_dir,
                            since_days=self._body_sync_days, mb=mb,
                        )
                        priority_total += count

                self._health[account.email].record_sync(priority_total)
                log.info(
                    "priority_sync_done",
                    account=account.email,
                    new_messages=priority_total,
                    body_sync_days=self._body_sync_days,
                )
            except Exception as exc:
                self._health[account.email].record_error(str(exc))
                log.exception("priority_sync_error", account=account.email)

        # Spawn IDLE, backfill, and periodic sync per account.
        # IDLE starts immediately (real-time matters).
        # Backfill runs next; periodic sync waits until backfill completes
        # to avoid redundant overlapping work.
        for account in self._config.accounts:
            backfill_done = asyncio.Event()

            self._tasks.append(asyncio.create_task(
                run_idle(
                    account, self._db, self._config.attachments_dir,
                    stop_event=self._stop,
                    idle_connections=self._idle_connections,
                ),
                name=f"idle-{account.email}",
            ))
            self._tasks.append(asyncio.create_task(
                _backfill_account(
                    account, self._db, self._config.attachments_dir,
                    self._stop, self._body_sync_days,
                    self._health.get(account.email),
                    backfill_done=backfill_done,
                ),
                name=f"backfill-{account.email}",
            ))
            self._tasks.append(asyncio.create_task(
                _deferred_periodic_sync(
                    backfill_done,
                    account, self._db, self._config.attachments_dir,
                    self._stop, self._health.get(account.email),
                ),
                name=f"sync-{account.email}",
            ))

        log.info("daemon_running", tasks=len(self._tasks))

    def request_stop(self) -> None:
        """Signal all tasks to stop.  Non-blocking, idempotent.

        Sets the stop event *and* force-closes every live IDLE socket so
        that threads blocked on ``idle.wait()`` unblock immediately.
        Also drains idle connections from each account's provider.
        """
        if self._stop.is_set():
            return
        log.info("daemon_shutting_down")
        self._stop.set()
        for mb in list(self._idle_connections):
            force_close(mb)
        self._idle_connections.clear()
        for account in self._config.accounts:
            get_provider(account).force_disconnect_all()

    async def wait_stopped(self, timeout: float = 15) -> None:
        """Wait for tasks to finish and release all resources."""
        if self._tasks:
            _, pending = await asyncio.wait(self._tasks, timeout=timeout)
            for t in pending:
                t.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
        if self._db is not None:
            await self._db.close()
            self._db = None
        log.info("daemon_stopped")

    async def run_forever(self) -> None:
        """Block until ``request_stop()`` is called, then clean up.

        Used by the CLI entry-point.  Signal handlers are installed so
        that SIGINT / SIGTERM trigger ``request_stop()``.
        """
        self._install_signal_handlers()
        _write_pid_file(self._config)
        try:
            await self._stop.wait()
            await self.wait_stopped()
        finally:
            _remove_pid_file(self._config)

    # ── Health ────────────────────────────────────────────────────

    def health(self) -> dict:
        """Return health status for the daemon and each account.

        Useful for supervisor health checks::

            status = daemon.health()
            # {"running": True, "started_at": "...", "accounts": {...}}
        """
        return {
            "running": self.is_running,
            "started_at": self._started_at,
            "pid": os.getpid(),
            "accounts": {
                email: ah.to_dict() for email, ah in self._health.items()
            },
        }

    # ── Internals ───────────────────────────────────────────────

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.request_stop)
            except NotImplementedError:
                pass

    @property
    def is_running(self) -> bool:
        return bool(self._tasks) and not self._stop.is_set()


# ── Account health tracker ──────────────────────────────────────


class AccountHealth:
    """Per-account health tracking for supervisor integration."""

    __slots__ = (
        "email", "last_sync_at", "last_sync_messages",
        "total_syncs", "last_error", "last_error_at", "consecutive_errors",
    )

    def __init__(self, email: str) -> None:
        self.email = email
        self.last_sync_at: str | None = None
        self.last_sync_messages: int = 0
        self.total_syncs: int = 0
        self.last_error: str | None = None
        self.last_error_at: str | None = None
        self.consecutive_errors: int = 0

    def record_sync(self, messages: int) -> None:
        self.last_sync_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.last_sync_messages = messages
        self.total_syncs += 1
        self.consecutive_errors = 0

    def record_error(self, error: str) -> None:
        self.last_error = error
        self.last_error_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.consecutive_errors += 1

    def to_dict(self) -> dict:
        return {
            "email": self.email,
            "last_sync_at": self.last_sync_at,
            "last_sync_messages": self.last_sync_messages,
            "total_syncs": self.total_syncs,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at,
            "consecutive_errors": self.consecutive_errors,
        }


# ── PID file management ─────────────────────────────────────────


def _pid_path(config: ServiceConfig) -> Path:
    return config.db_path.parent / "daemon.pid"


def _write_pid_file(config: ServiceConfig) -> None:
    path = _pid_path(config)
    path.write_text(str(os.getpid()), encoding="utf-8")
    log.debug("pid_file_written", path=str(path), pid=os.getpid())


def _remove_pid_file(config: ServiceConfig) -> None:
    path = _pid_path(config)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def read_pid_file() -> int | None:
    """Read the daemon PID from the workspace.  Returns None if not found."""
    from .config import get_email_home

    path = get_email_home() / "daemon.pid"
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def is_daemon_running() -> tuple[bool, int | None]:
    """Check if the daemon process is alive.

    Returns ``(alive, pid)``.  If the PID file exists but the process
    is dead the stale PID file is removed.
    """
    pid = read_pid_file()
    if pid is None:
        return False, None
    try:
        os.kill(pid, 0)
        return True, pid
    except ProcessLookupError:
        from .config import get_email_home
        try:
            (get_email_home() / "daemon.pid").unlink(missing_ok=True)
        except OSError:
            pass
        return False, None
    except PermissionError:
        return True, pid


def stop_daemon() -> bool:
    """Send SIGTERM to the running daemon.  Returns True if signal was sent."""
    alive, pid = is_daemon_running()
    if not alive or pid is None:
        return False
    os.kill(pid, signal.SIGTERM)
    return True


# ── Helpers (kept at module level for test access) ──────────────

async def _upsert_folders(db: Any, account_email: str, folders: list[dict]) -> None:
    """Persist discovered IMAP folders (with roles) into the folders table."""
    import json as _json

    for f in folders:
        await db.execute(
            """INSERT INTO folders (account_email, name, role, delimiter, flags, selectable)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (account_email, name) DO UPDATE SET
                   role = excluded.role,
                   delimiter = excluded.delimiter,
                   flags = excluded.flags,
                   selectable = excluded.selectable""",
            (
                account_email,
                f["name"],
                f.get("role"),
                f.get("delimiter", "/"),
                _json.dumps(f.get("flags", [])),
                int(f.get("selectable", True)),
            ),
        )
    await db.commit()


async def _upsert_account_row(db: Any, account: AccountConfig) -> None:
    """Ensure the accounts table has a row for this account (metadata only)."""
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    await db.execute(
        """INSERT INTO accounts (email, display_name, provider, imap_host, smtp_host, imap_port, smtp_port, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
           ON CONFLICT (email) DO UPDATE SET
               display_name = excluded.display_name,
               provider = excluded.provider,
               imap_host = excluded.imap_host,
               smtp_host = excluded.smtp_host,
               imap_port = excluded.imap_port,
               smtp_port = excluded.smtp_port,
               status = 'active'""",
        (
            account.email,
            account.display_name,
            account.provider,
            account.imap_host,
            account.smtp_host,
            account.imap_port,
            account.smtp_port,
            now,
        ),
    )
    await db.commit()


async def _backfill_account(
    account: AccountConfig,
    db: Any,
    attachments_dir: Path,
    stop_event: asyncio.Event,
    body_sync_days: int,
    health: AccountHealth | None = None,
    *,
    backfill_done: asyncio.Event | None = None,
) -> None:
    """One-shot background task: fill in old headers and remaining folders.

    Runs after the priority pass has made INBOX + Sent usable.  Steps:

    1. INBOX + Sent headers-only for ALL messages (fills in >90-day headers;
       INSERT OR IGNORE deduplicates against the priority pass)
    2. All other folders headers-only (skip All Mail, INBOX, Sent)
    3. Body upgrade for remaining folders' recent window (skip All Mail,
       INBOX, Sent — those already have bodies from the priority pass)
    4. Verify integrity — compare local UIDs against IMAP server

    Sets *backfill_done* when finished so that deferred periodic sync
    knows it's safe to start.
    """
    if stop_event.is_set():
        if backfill_done:
            backfill_done.set()
        return
    log.info("backfill_start", account=account.email)

    provider = get_provider(account)
    async with provider.connection() as mb:
        folders = await get_or_discover_folders(mb, account.email)
        await _upsert_folders(db, account.email, folders)
        sent_name = folder_for_role(folders, "sent")

        if not stop_event.is_set():
            await sync_folder(
                account, "INBOX", db, attachments_dir,
                full=True, headers_only=True, mb=mb,
            )
        if not stop_event.is_set() and sent_name:
            await sync_folder(
                account, sent_name, db, attachments_dir,
                full=True, headers_only=True, mb=mb,
            )

    _skip: set[str] = {"all", "inbox", "sent"}

    try:
        # 2. Headers for everything else (skip All Mail + already-handled INBOX/Sent)
        if not stop_event.is_set():
            await sync_all_folders(
                account, db, attachments_dir,
                headers_only=True, skip_roles=_skip,
            )

        # 3. 90d bodies for everything else
        if not stop_event.is_set():
            await upgrade_all_folders_bodies(
                account, db, attachments_dir,
                since_days=body_sync_days, skip_roles=_skip,
            )

        # 4. Verify — confirm every server UID is in the local DB
        if not stop_event.is_set():
            result = await verify_integrity(account, db, skip_roles={"all"})
            if result["ok"]:
                log.info("backfill_integrity_ok", account=account.email,
                         server=result["total_server"], local=result["total_local"])
            else:
                gaps = {n: len(i["missing"]) for n, i in result["folders"].items() if i["missing"]}
                log.warning("backfill_integrity_gaps", account=account.email, gaps=gaps)
            await write_event(
                db, "integrity_check",
                account_email=account.email,
                data={"ok": result["ok"], "server": result["total_server"],
                       "local": result["total_local"]},
            )

        log.info("backfill_done", account=account.email)
    except Exception as exc:
        if health:
            health.record_error(str(exc))
        log.exception("backfill_error", account=account.email)
    finally:
        if backfill_done:
            backfill_done.set()


async def _deferred_periodic_sync(
    backfill_done: asyncio.Event,
    account: AccountConfig,
    db: Any,
    attachments_dir: Path,
    stop_event: asyncio.Event,
    health: AccountHealth | None = None,
) -> None:
    """Wait for backfill to finish, then start periodic sync.

    Backfill already syncs every folder; running periodic sync in
    parallel would be redundant and waste IMAP connections.

    Races ``backfill_done`` against ``stop_event`` so that a shutdown
    request unblocks this task immediately rather than waiting up to
    the full timeout.
    """
    backfill_wait = asyncio.create_task(backfill_done.wait())
    stop_wait = asyncio.create_task(stop_event.wait())
    try:
        done, _ = await asyncio.wait(
            {backfill_wait, stop_wait},
            timeout=3600,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not done:
            log.warning("backfill_timeout_starting_periodic", account=account.email)
    finally:
        backfill_wait.cancel()
        stop_wait.cancel()
    if stop_event.is_set():
        return
    await _periodic_sync_loop(account, db, attachments_dir, stop_event, health)


async def _periodic_sync_loop(
    account: AccountConfig,
    db: Any,
    attachments_dir: Path,
    stop_event: asyncio.Event,
    health: AccountHealth | None = None,
) -> None:
    """Sync all folders for an account every PERIODIC_SYNC_INTERVAL seconds."""
    while not stop_event.is_set():
        try:
            total = await sync_all_folders(
                account, db, attachments_dir, skip_roles={"all"},
            )
            if health:
                health.record_sync(total)
            log.info(
                "periodic_sync_done",
                account=account.email,
                new_messages=total,
            )
        except Exception as exc:
            if health:
                health.record_error(str(exc))
            log.exception("periodic_sync_error", account=account.email)
            try:
                await write_event(
                    db,
                    "sync_error",
                    account_email=account.email,
                    data={"phase": "periodic"},
                )
            except Exception:
                pass

        try:
            result = await verify_integrity(account, db, skip_roles={"all"})
            if result["ok"]:
                log.info("periodic_integrity_ok", account=account.email,
                         server=result["total_server"], local=result["total_local"])
            else:
                gaps = {n: len(i["missing"]) for n, i in result["folders"].items() if i["missing"]}
                log.warning("periodic_integrity_gaps", account=account.email, gaps=gaps)
            await write_event(
                db, "integrity_check",
                account_email=account.email,
                data={"ok": result["ok"], "server": result["total_server"],
                       "local": result["total_local"], "phase": "periodic"},
            )
        except Exception:
            log.exception("periodic_integrity_error", account=account.email)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=PERIODIC_SYNC_INTERVAL)
        except TimeoutError:
            pass


async def run_daemon(*, body_sync_days: int | None = None) -> None:
    """CLI entry-point: load config, start daemon, block until signal.

    The workspace location is controlled by ``INTENTFRAME_EMAIL_HOME``
    (default ``~/.intentframe/email``).  *body_sync_days* overrides the
    config value for the initial body-fetch window.
    """
    from .config import load_config_async

    from intentframe_credentials import redact_credentials

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            redact_credentials,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
    )

    config = await load_config_async()
    days = body_sync_days if body_sync_days is not None else config.body_sync_days

    alive, pid = is_daemon_running()
    if alive:
        log.error("daemon_already_running", pid=pid)
        raise SystemExit(1)

    log.info(
        "daemon_starting",
        accounts=[a.email for a in config.accounts],
        db_path=str(config.db_path),
        body_sync_days=days,
    )

    daemon = SyncDaemon(config, body_sync_days=days)
    await daemon.start()
    await daemon.run_forever()
