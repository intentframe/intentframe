"""YAML config loading, account credential resolution, and account management.

Everything is derived from a single workspace root (``EMAIL_HOME``):

    EMAIL_HOME/
    ├── config.yaml      # account list (email addresses only, no passwords)
    ├── emails.db        # SQLite database (created by daemon)
    └── attachments/     # downloaded attachments

Passwords are never stored in YAML.  They are fetched from the
credential vault at config-load time.  The vault must be running.

Resolved ``AccountConfig.password`` is a ``SecretStr`` so reprs and
tracebacks do not expose plaintext; use ``.get_secret_value()`` only
when calling IMAP/SMTP APIs.

Default: ``~/.intentframe/email``
Override: set the ``INTENTFRAME_EMAIL_HOME`` environment variable.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

import structlog
import yaml
from pydantic import BaseModel, SecretStr

from intentframe_credentials.client import VaultClient, VaultClientSync

from .providers import ProviderInfo, resolve_provider

log = structlog.get_logger()

_ENV_KEY = "INTENTFRAME_EMAIL_HOME"
_DEFAULT_HOME = Path.home() / ".intentframe" / "email"


def get_email_home() -> Path:
    """Return the resolved email service workspace root."""
    return Path(os.environ[_ENV_KEY]) if _ENV_KEY in os.environ else _DEFAULT_HOME


class AccountConfigYAML(BaseModel):
    """Raw account entry as it appears in the YAML file.

    Passwords are never in YAML — they come from the credential vault.
    """

    email: str
    display_name: str = ""
    imap_host: Optional[str] = None
    smtp_host: Optional[str] = None
    imap_port: Optional[int] = None
    smtp_port: Optional[int] = None


class AccountConfig(BaseModel):
    """Fully resolved account config ready for use by the daemon/client.

    ``password`` is ``SecretStr`` so ``repr`` / traceback locals mask the
    value. Unwrap with ``password.get_secret_value()`` at IMAP/SMTP calls.
    """

    email: str
    password: SecretStr
    display_name: str
    provider: str
    imap_host: str
    smtp_host: str
    imap_port: int
    smtp_port: int


class ServiceConfig(BaseModel):
    """Top-level config for the email sync service."""

    accounts: list[AccountConfig]
    db_path: Path
    attachments_dir: Path
    body_sync_days: int = 90


def _fetch_password(email: str) -> str:
    """Fetch the email password from the credential vault.

    Hard-fails if the vault is unreachable or the credential is missing.
    """
    vault = VaultClientSync()
    password = vault.get(f"email.{email}", "password")
    if not password:
        raise ValueError(
            f"No password in vault for {email}. "
            f"Store it first: namespace='email.{email}', key='password'"
        )
    return password


def _resolve_account(raw: AccountConfigYAML) -> AccountConfig:
    """Merge YAML overrides with auto-inferred provider defaults.

    Password is fetched from the credential vault — never from YAML.
    """
    provider: ProviderInfo = resolve_provider(raw.email)
    password = _fetch_password(raw.email)
    return AccountConfig(
        email=raw.email,
        password=password,
        display_name=raw.display_name or raw.email.split("@")[0],
        provider=provider.name,
        imap_host=raw.imap_host or provider.imap_host,
        smtp_host=raw.smtp_host or provider.smtp_host,
        imap_port=raw.imap_port or provider.imap_port,
        smtp_port=raw.smtp_port or provider.smtp_port,
    )


def _check_vault_health() -> None:
    """Ping the vault to verify it is reachable (sync).

    Uses ``VaultClientSync`` — safe to call outside an event loop.
    Raises on connection failure so the caller can surface a clear
    error before attempting any credential fetches.
    """
    vault = VaultClientSync()
    vault.has("__health__", "__ping__")


async def _check_vault_health_async() -> None:
    """Ping the vault to verify it is reachable (async).

    Uses ``VaultClient`` — safe to call from a running event loop.
    """
    async with VaultClient() as c:
        client = await c._client()
        r = await client.get("/health")
        r.raise_for_status()


async def _fetch_password_async(email: str) -> str:
    """Fetch the email password from the vault (async)."""
    async with VaultClient() as vault:
        password = await vault.get(f"email.{email}", "password")
    if not password:
        raise ValueError(
            f"No password in vault for {email}. "
            f"Store it first: namespace='email.{email}', key='password'"
        )
    return password


async def _resolve_account_async(raw: AccountConfigYAML) -> AccountConfig:
    """Merge YAML overrides with provider defaults (async)."""
    provider: ProviderInfo = resolve_provider(raw.email)
    password = await _fetch_password_async(raw.email)
    return AccountConfig(
        email=raw.email,
        password=password,
        display_name=raw.display_name or raw.email.split("@")[0],
        provider=provider.name,
        imap_host=raw.imap_host or provider.imap_host,
        smtp_host=raw.smtp_host or provider.smtp_host,
        imap_port=raw.imap_port or provider.imap_port,
        smtp_port=raw.smtp_port or provider.smtp_port,
    )


def _load_raw_yaml() -> tuple[dict, Path]:
    """Read and validate config.yaml, return (raw dict, path)."""
    home = get_email_home()
    path = home / "config.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"No config found at {path}. Add an account first:\n"
            f"  email-sync-daemon add you@gmail.com"
        )

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not raw or "accounts" not in raw:
        raise ValueError(f"Config at {path} must have an 'accounts' list.")

    if not raw["accounts"]:
        raise ValueError(
            f"No accounts in {path}. Add one with:\n"
            f"  email-sync-daemon add you@gmail.com"
        )
    return raw, home


def load_config() -> ServiceConfig:
    """Load the service config (sync).

    Uses ``VaultClientSync`` — call from CLI handlers and other sync
    code that runs **outside** an event loop.
    """
    raw, home = _load_raw_yaml()

    try:
        _check_vault_health()
    except Exception as exc:
        raise ConnectionError(
            "Credential vault is not reachable. Start it before running EDI."
        ) from exc

    raw_accounts = [AccountConfigYAML(**a) for a in raw["accounts"]]
    accounts = [_resolve_account(a) for a in raw_accounts]

    return ServiceConfig(
        accounts=accounts,
        db_path=home / "emails.db",
        attachments_dir=home / "attachments",
        body_sync_days=int(raw.get("body_sync_days", 90)),
    )


async def load_config_async() -> ServiceConfig:
    """Load the service config (async).

    Uses ``VaultClient`` — call from ``run_daemon`` and other async
    code that runs **inside** an event loop.
    """
    raw, home = _load_raw_yaml()

    try:
        await _check_vault_health_async()
    except Exception as exc:
        raise ConnectionError(
            "Credential vault is not reachable. Start it before running EDI."
        ) from exc

    raw_accounts = [AccountConfigYAML(**a) for a in raw["accounts"]]
    accounts = [await _resolve_account_async(a) for a in raw_accounts]

    return ServiceConfig(
        accounts=accounts,
        db_path=home / "emails.db",
        attachments_dir=home / "attachments",
        body_sync_days=int(raw.get("body_sync_days", 90)),
    )


# ── Account management (admin operations) ────────────────────────


def _read_raw_config() -> tuple[dict, Path]:
    """Read the raw YAML dict and return (data, path)."""
    home = get_email_home()
    path = home / "config.yaml"
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    else:
        raw = {}
    if "accounts" not in raw:
        raw["accounts"] = []
    return raw, path


def _write_config_atomic(raw: dict, path: Path) -> None:
    """Write config YAML atomically (write-to-temp, rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".yaml.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(raw, f, default_flow_style=False, sort_keys=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def add_email(
    email: str,
    display_name: str = "",
    *,
    validate: bool = True,
) -> AccountConfig:
    """Add (or update) an email account in the workspace config.

    The password must already exist in the credential vault under
    ``email.<address> / password``.  If *validate* is ``True``
    (default), an IMAP login is attempted before saving.

    Returns the resolved ``AccountConfig``.
    """
    resolved = _resolve_account(AccountConfigYAML(
        email=email,
        display_name=display_name,
    ))

    if validate:
        from imap_tools import MailBox

        try:
            mb = MailBox(resolved.imap_host, resolved.imap_port)
            mb.login(email, resolved.password.get_secret_value(), initial_folder=None)
            mb.logout()
            log.info("imap_login_ok", email=email, provider=resolved.provider)
        except Exception as exc:
            raise ValueError(
                f"IMAP login failed for {email} at {resolved.imap_host}:{resolved.imap_port}: {exc}"
            ) from exc

    raw, path = _read_raw_config()
    entry: dict[str, str] = {"email": email}
    if display_name:
        entry["display_name"] = display_name

    existing_idx = next(
        (i for i, a in enumerate(raw["accounts"]) if a.get("email") == email),
        None,
    )
    if existing_idx is not None:
        raw["accounts"][existing_idx] = entry
    else:
        raw["accounts"].append(entry)

    _write_config_atomic(raw, path)
    log.info("account_added", email=email, config_path=str(path))
    return resolved


def remove_email(email: str) -> bool:
    """Remove an email account from the workspace config.

    Returns ``True`` if the account was found and removed, ``False``
    if it was not present.
    """
    raw, path = _read_raw_config()
    before = len(raw["accounts"])
    raw["accounts"] = [a for a in raw["accounts"] if a.get("email") != email]

    if len(raw["accounts"]) == before:
        return False

    _write_config_atomic(raw, path)
    log.info("account_removed", email=email, config_path=str(path))
    return True


def list_configured_emails() -> list[str]:
    """Return a list of email addresses from the workspace config.

    Reads ``config.yaml`` directly — does not require the daemon to be
    running.  Returns an empty list if the config file does not exist.
    """
    raw, _ = _read_raw_config()
    return [a["email"] for a in raw["accounts"] if "email" in a]


def reset_workspace(*, include_config: bool = False) -> dict[str, bool]:
    """Delete workspace data and optionally the config.

    Stops the daemon if running.  Returns a dict of what was deleted::

        {"db": True, "attachments": True, "pid": False, "config": True}
    """
    from .daemon import is_daemon_running, stop_daemon

    alive, _ = is_daemon_running()
    if alive:
        stop_daemon()
        import time
        for _ in range(30):
            time.sleep(0.5)
            if not is_daemon_running()[0]:
                break

    home = get_email_home()
    deleted: dict[str, bool] = {}

    db = home / "emails.db"
    deleted["db"] = db.exists()
    if deleted["db"]:
        db.unlink()
        for suffix in ("-wal", "-shm"):
            wal = home / f"emails.db{suffix}"
            wal.unlink(missing_ok=True)

    att = home / "attachments"
    deleted["attachments"] = att.exists()
    if deleted["attachments"]:
        shutil.rmtree(att)

    pid = home / "daemon.pid"
    deleted["pid"] = pid.exists()
    pid.unlink(missing_ok=True)

    cfg = home / "config.yaml"
    deleted["config"] = False
    if include_config:
        deleted["config"] = cfg.exists()
        if deleted["config"]:
            cfg.unlink()
        if home.exists() and not any(home.iterdir()):
            home.rmdir()

    log.info(
        "workspace_reset",
        home=str(home),
        include_config=include_config,
        deleted=deleted,
    )
    return deleted
