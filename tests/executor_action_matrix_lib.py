"""Shared fixtures + capture for executor action matrix parity.

Pre-refactor baseline commit is recorded in the frozen fixture file.
Run ``tests/verify_executor_action_matrix.py --write-baseline`` after
intentional behavior changes.
"""

from __future__ import annotations

import asyncio
import ast
import contextlib
import inspect
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from unittest.mock import AsyncMock, patch

from action_registry import ActionType
from executor_sdk.adapters.base import CapabilityAdapter
from executor.adapters.console_user_io import ConsoleUserIOAdapter
from executor_sdk.config.schema import HostFilesConfig
from intentframe_executor_pack_macos.sandbox.config import SandboxConfig
from executor_sdk.models import AdapterManifest, ExecutionResult
from intentframe_executor_pack_macos.adapters.files import FilesAdapter
from intentframe_executor_pack_macos.adapters.host_files import HostFilesAdapter
from intentframe_executor_pack_macos.adapters.http_api import HttpApiAdapter
from intentframe_executor_pack_macos.adapters.terminal import TerminalAdapter
from executor_sdk.services.virtual_filesystem import MountPointConfig

BASELINE_COMMIT = "5c266a4"

# Optional deps that may be absent in minimal CI environments.
_OPTIONAL_ADAPTER_DEPS = frozenset({"watchdog"})

# Stable case ids — do not rename without rewriting the baseline fixture.
ACTION_CASE_IDS: frozenset[str] = frozenset({
    "host_files_write_read_roundtrip",
    "host_files_write_rollback",
    "host_files_floor_write_sudoers",
    "host_files_floor_delete_sudoers",
    "host_files_ceiling_write_outside",
    "host_files_ceiling_read_outside",
    "host_files_validation_missing_path",
    "host_files_validation_bad_content",
    "vfs_write_read_roundtrip",
    "vfs_write_rollback",
    "vfs_floor_write_trap",
    "terminal_sandbox_disabled_echo",
    "terminal_sandbox_unavailable",
    "terminal_missing_command",
    "terminal_catastrophic_blocked",
    "terminal_unknown_action",
    "http_api_missing_url",
    "http_api_credentials_kwarg",
    "console_user_io_show_message",
    "console_user_io_confirmation_extras",
    "console_user_io_unknown_action",
    "safe_execute_timeout_envelope",
    "safe_execute_exception_envelope",
    "safe_execute_credentials_accepted",
    "browser_validation_missing_url",
    "calendar_validation_empty_params",
    "clipboard_validation_unknown_action",
    "contacts_validation_empty_params",
    "mail_validation_missing_account",
    "messages_validation_empty_params",
    "notes_validation_empty_params",
    "notifications_validation_empty_params",
    "reminders_validation_empty_params",
    "shortcuts_validation_missing_name",
    "spotlight_validation_missing_query",
    "system_validation_platform_action",
    "user_io_validation_empty_params",
})


@dataclass(frozen=True)
class ActionRow:
    case_id: str
    adapter: str
    action: str
    success: bool
    data_keys: str
    error_keyword: str
    wall: str
    rollback_available: str
    rollback_id_prefix: str
    extras_keys: str


@dataclass(frozen=True)
class ManifestRow:
    adapter_id: str
    action_count: int
    requires_credentials: bool
    version: str
    actions: str


@dataclass(frozen=True)
class ActionCase:
    case_id: str
    adapter: str
    action: str
    wall: str
    run: Callable[[], ExecutionResult]


class _TimeoutProbeAdapter(CapabilityAdapter):
    """Hangs until safe_execute cancels it."""

    async def execute(
        self, action: str, params: dict, credentials: dict | None = None,
    ) -> ExecutionResult:
        await asyncio.sleep(60)
        return ExecutionResult(success=True)

    async def rollback(self, rollback_id: str) -> ExecutionResult:
        return ExecutionResult(success=False, error="probe")

    def supported_actions(self) -> list[str]:
        return ["PROBE_HANG"]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="probe_timeout",
            name="Timeout Probe",
            supported_actions=self.supported_actions(),
        )


class _ExceptionProbeAdapter(CapabilityAdapter):
    """Raises to verify safe_execute exception envelope."""

    async def execute(
        self, action: str, params: dict, credentials: dict | None = None,
    ) -> ExecutionResult:
        raise RuntimeError("matrix probe boom")

    async def rollback(self, rollback_id: str) -> ExecutionResult:
        return ExecutionResult(success=False, error="probe")

    def supported_actions(self) -> list[str]:
        return ["PROBE_BOOM"]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="probe_exception",
            name="Exception Probe",
            supported_actions=self.supported_actions(),
        )


class _CredentialsProbeAdapter(CapabilityAdapter):
    """Verifies credentials kwarg reaches execute()."""

    async def execute(
        self, action: str, params: dict, credentials: dict | None = None,
    ) -> ExecutionResult:
        if credentials is None:
            return ExecutionResult(success=False, error="credentials missing")
        if credentials.get("probe") != "ok":
            return ExecutionResult(success=False, error="credentials invalid")
        return ExecutionResult(success=True, data={"credentials_seen": True})

    async def rollback(self, rollback_id: str) -> ExecutionResult:
        return ExecutionResult(success=False, error="probe")

    def supported_actions(self) -> list[str]:
        return ["PROBE_CREDS"]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="probe_credentials",
            name="Credentials Probe",
            supported_actions=self.supported_actions(),
            requires_credentials=True,
        )


def _run(coro) -> ExecutionResult:
    return asyncio.run(coro)


def _sorted_keys(result: ExecutionResult) -> str:
    if not result.data:
        return "-"
    return ",".join(sorted(result.data.keys()))


def _extras_keys(result: ExecutionResult) -> str:
    if not result.extras:
        return "-"
    return ",".join(sorted(result.extras.keys()))


def _rollback_id_prefix(rollback_id: str | None) -> str:
    if not rollback_id:
        return "-"
    if ":" in rollback_id:
        return rollback_id.split(":", 1)[0] + ":"
    return rollback_id


def _error_keyword(result: ExecutionResult) -> str:
    if result.success:
        return "-"
    err = (result.error or "").lower()
    for token in (
        "floor",
        "allowlist",
        "non-negotiable",
        "path",
        "content",
        "unavailable",
        "catastrophic",
        "unknown",
        "command",
        "url",
        "account",
        "query",
        "name",
        "validation",
        "credentials",
        "timed out",
        "temporarily",
    ):
        if token in err:
            return token.replace(" ", "_")
    return err.split()[0] if err else "error"


def _host_files_adapter(root: Path) -> HostFilesAdapter:
    cfg = HostFilesConfig(
        allowed_read_paths=[str(root)],
        allowed_write_paths=[str(root)],
    )
    return HostFilesAdapter(host_files_cfg=cfg)


def _files_adapter(root: Path) -> FilesAdapter:
    mount = MountPointConfig(
        virtual_path="/work/",
        real_path=str(root),
        writable=True,
    )
    from executor_sdk.services.virtual_filesystem import MountPointResolver

    resolver = MountPointResolver([mount], root)
    return FilesAdapter(mount_resolver=resolver, base_path=root)


def _platform_validation_response(*_args, **_kwargs) -> dict:
    return {"success": False, "error": "validation probe: required params missing"}


@contextlib.contextmanager
def _temp_dirs(*, prefix: str):
    """Yield a temp directory; cleaned up on exit."""
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        yield Path(tmp)


def _run_with_platform_patch(
    module_path: str,
    adapter: CapabilityAdapter,
    action: str,
    params: dict,
) -> ExecutionResult:
    with patch(
        f"{module_path}.platform_execute",
        new_callable=AsyncMock,
        return_value=_platform_validation_response(),
    ):
        return _run(adapter.safe_execute(action, params))


def action_cases() -> tuple[ActionCase, ...]:
    cases: list[ActionCase] = []

    def add(
        case_id: str,
        adapter: str,
        action: str,
        wall: str,
        runner: Callable[[], ExecutionResult],
    ) -> None:
        cases.append(
            ActionCase(
                case_id=case_id,
                adapter=adapter,
                action=action,
                wall=wall,
                run=runner,
            )
        )

    # ── host_files ──────────────────────────────────────────────────────
    host_root_holder: dict[str, Path] = {}

    def _host_root() -> Path:
        if "root" not in host_root_holder:
            host_root_holder["root"] = Path(tempfile.mkdtemp(prefix="if_host_"))
        return host_root_holder["root"]

    def host_write_read() -> ExecutionResult:
        root = _host_root()
        adapter = _host_files_adapter(root)
        target = root / "matrix.txt"
        w = _run(
            adapter.safe_execute(
                ActionType.WRITE_HOST_FILE.value,
                {"path": str(target), "content": "matrix"},
            )
        )
        if not w.success:
            return w
        return _run(
            adapter.safe_execute(
                ActionType.READ_HOST_FILE.value,
                {"path": str(target)},
            )
        )

    def host_write_rollback() -> ExecutionResult:
        root = _host_root()
        adapter = _host_files_adapter(root)
        target = root / "rollback.txt"
        return _run(
            adapter.safe_execute(
                ActionType.WRITE_HOST_FILE.value,
                {"path": str(target), "content": "matrix"},
            )
        )

    def host_floor_write() -> ExecutionResult:
        cfg = HostFilesConfig(
            allowed_read_paths=["/etc"],
            allowed_write_paths=["/etc"],
        )
        adapter = HostFilesAdapter(host_files_cfg=cfg)
        return _run(
            adapter.safe_execute(
                ActionType.WRITE_HOST_FILE.value,
                {"path": "/etc/sudoers", "content": "x"},
            )
        )

    def host_floor_delete() -> ExecutionResult:
        cfg = HostFilesConfig(
            allowed_read_paths=["/etc"],
            allowed_write_paths=["/etc"],
        )
        adapter = HostFilesAdapter(host_files_cfg=cfg)
        return _run(
            adapter.safe_execute(
                ActionType.DELETE_HOST_FILE.value,
                {"path": "/etc/sudoers"},
            )
        )

    def host_ceiling_write() -> ExecutionResult:
        with _temp_dirs(prefix="if_host_ceiling_") as root:
            inside = root / "inside"
            outside = root / "outside"
            inside.mkdir()
            outside.mkdir()
            cfg = HostFilesConfig(
                allowed_read_paths=[str(inside)],
                allowed_write_paths=[str(inside)],
            )
            adapter = HostFilesAdapter(host_files_cfg=cfg)
            return _run(
                adapter.safe_execute(
                    ActionType.WRITE_HOST_FILE.value,
                    {"path": str(outside / "escape.txt"), "content": "x"},
                )
            )

    def host_ceiling_read() -> ExecutionResult:
        with _temp_dirs(prefix="if_host_ceiling_") as root:
            inside = root / "inside"
            outside = root / "outside"
            inside.mkdir()
            outside.mkdir()
            cfg = HostFilesConfig(
                allowed_read_paths=[str(inside)],
                allowed_write_paths=[str(inside)],
            )
            adapter = HostFilesAdapter(host_files_cfg=cfg)
            (outside / "secret.txt").write_text("x")
            return _run(
                adapter.safe_execute(
                    ActionType.READ_HOST_FILE.value,
                    {"path": str(outside / "secret.txt")},
                )
            )

    def host_missing_path() -> ExecutionResult:
        adapter = _host_files_adapter(_host_root())
        return _run(adapter.safe_execute(ActionType.READ_HOST_FILE.value, {}))

    def host_bad_content() -> ExecutionResult:
        root = _host_root()
        adapter = _host_files_adapter(root)
        return _run(
            adapter.safe_execute(
                ActionType.WRITE_HOST_FILE.value,
                {"path": str(root / "x.txt"), "content": 12345},
            )
        )

    add("host_files_write_read_roundtrip", "host_files", "READ_HOST_FILE", "none", host_write_read)
    add("host_files_write_rollback", "host_files", "WRITE_HOST_FILE", "none", host_write_rollback)
    add("host_files_floor_write_sudoers", "host_files", "WRITE_HOST_FILE", "floor", host_floor_write)
    add("host_files_floor_delete_sudoers", "host_files", "DELETE_HOST_FILE", "floor", host_floor_delete)
    add("host_files_ceiling_write_outside", "host_files", "WRITE_HOST_FILE", "ceiling", host_ceiling_write)
    add("host_files_ceiling_read_outside", "host_files", "READ_HOST_FILE", "ceiling", host_ceiling_read)
    add("host_files_validation_missing_path", "host_files", "READ_HOST_FILE", "validation", host_missing_path)
    add("host_files_validation_bad_content", "host_files", "WRITE_HOST_FILE", "validation", host_bad_content)

    # ── vfs / files ─────────────────────────────────────────────────────
    vfs_root_holder: dict[str, Path] = {}

    def _vfs_root() -> Path:
        if "root" not in vfs_root_holder:
            vfs_root_holder["root"] = Path(tempfile.mkdtemp(prefix="if_vfs_"))
        return vfs_root_holder["root"]

    def vfs_write_read() -> ExecutionResult:
        root = _vfs_root()
        adapter = _files_adapter(root)
        w = _run(
            adapter.safe_execute(
                ActionType.WRITE_FILE.value,
                {"path": "/work/hello.txt", "content": "hi"},
            )
        )
        if not w.success:
            return w
        return _run(
            adapter.safe_execute(
                ActionType.READ_FILE.value,
                {"path": "/work/hello.txt"},
            )
        )

    def vfs_write_rollback() -> ExecutionResult:
        root = _vfs_root()
        adapter = _files_adapter(root)
        return _run(
            adapter.safe_execute(
                ActionType.WRITE_FILE.value,
                {"path": "/work/rollback.txt", "content": "hi"},
            )
        )

    def vfs_floor_write() -> ExecutionResult:
        with _temp_dirs(prefix="if_vfs_trap_") as tmp:
            symlink = tmp / "floor"
            symlink.symlink_to("/System")
            mount = MountPointConfig(
                virtual_path="/trap/",
                real_path=str(symlink),
                writable=True,
            )
            from executor_sdk.services.virtual_filesystem import MountPointResolver

            resolver = MountPointResolver([mount], tmp)
            adapter = FilesAdapter(mount_resolver=resolver, base_path=tmp)
            return _run(
                adapter.safe_execute(
                    ActionType.WRITE_FILE.value,
                    {"path": "/trap/evil.plist", "content": "pwned"},
                )
            )

    add("vfs_write_read_roundtrip", "files", "READ_FILE", "none", vfs_write_read)
    add("vfs_write_rollback", "files", "WRITE_FILE", "none", vfs_write_rollback)
    add("vfs_floor_write_trap", "files", "WRITE_FILE", "floor", vfs_floor_write)

    # ── terminal ────────────────────────────────────────────────────────
    class UnavailableSandboxEngine:
        """Simulates a platform where sandbox-exec (or equivalent) is missing."""

        def available(self) -> bool:
            return False

        def wrap(self, command: str, plan) -> None:
            raise RuntimeError("wrap should not run when engine is unavailable")

    def terminal_disabled_echo() -> ExecutionResult:
        adapter = TerminalAdapter(sandbox_config=SandboxConfig(enabled=False))
        return _run(
            adapter.safe_execute("RUN_COMMAND", {"command": "echo matrix_ok"})
        )

    def terminal_unavailable() -> ExecutionResult:
        adapter = TerminalAdapter(
            sandbox_engine=UnavailableSandboxEngine(),
            sandbox_config=SandboxConfig(enabled=True),
        )
        return _run(adapter.safe_execute("RUN_COMMAND", {"command": "echo hi"}))

    def terminal_missing_command() -> ExecutionResult:
        adapter = TerminalAdapter(sandbox_config=SandboxConfig(enabled=False))
        return _run(adapter.safe_execute("RUN_COMMAND", {}))

    def terminal_catastrophic() -> ExecutionResult:
        adapter = TerminalAdapter(sandbox_config=SandboxConfig(enabled=False))
        return _run(
            adapter.safe_execute("RUN_COMMAND", {"command": "sudo rm -rf /"})
        )

    def terminal_unknown() -> ExecutionResult:
        adapter = TerminalAdapter(sandbox_config=SandboxConfig(enabled=False))
        return _run(adapter.safe_execute("NOT_A_COMMAND", {}))

    add("terminal_sandbox_disabled_echo", "terminal", "RUN_COMMAND", "none", terminal_disabled_echo)
    add("terminal_sandbox_unavailable", "terminal", "RUN_COMMAND", "unavailable", terminal_unavailable)
    add("terminal_missing_command", "terminal", "RUN_COMMAND", "validation", terminal_missing_command)
    add("terminal_catastrophic_blocked", "terminal", "RUN_COMMAND", "floor", terminal_catastrophic)
    add("terminal_unknown_action", "terminal", "NOT_A_COMMAND", "validation", terminal_unknown)

    # ── http_api ────────────────────────────────────────────────────────
    def http_missing_url() -> ExecutionResult:
        adapter = HttpApiAdapter()
        return _run(adapter.safe_execute("HTTP_GET", {}))

    def http_credentials_kwarg() -> ExecutionResult:
        adapter = HttpApiAdapter()
        return _run(
            adapter.safe_execute(
                "HTTP_GET",
                {"url": "http://127.0.0.1:1/unreachable"},
                credentials={"api_key": "matrix-probe"},
            )
        )

    add("http_api_missing_url", "http_api", "HTTP_GET", "validation", http_missing_url)
    add("http_api_credentials_kwarg", "http_api", "HTTP_GET", "none", http_credentials_kwarg)

    # ── console_user_io ─────────────────────────────────────────────────
    def console_show() -> ExecutionResult:
        adapter = ConsoleUserIOAdapter()
        return _run(
            adapter.safe_execute("SHOW_MESSAGE", {"message": "matrix probe"})
        )

    def console_confirmation_extras() -> ExecutionResult:
        adapter = ConsoleUserIOAdapter()
        with patch("builtins.input", return_value="yes"):
            return _run(
                adapter.safe_execute(
                    "GET_CONFIRMATION",
                    {"prompt": "matrix probe confirm?"},
                )
            )

    def console_unknown() -> ExecutionResult:
        adapter = ConsoleUserIOAdapter()
        return _run(adapter.safe_execute("NOT_USER_IO", {}))

    add("console_user_io_show_message", "console_user_io", "SHOW_MESSAGE", "none", console_show)
    add(
        "console_user_io_confirmation_extras",
        "console_user_io",
        "GET_CONFIRMATION",
        "none",
        console_confirmation_extras,
    )
    add("console_user_io_unknown_action", "console_user_io", "NOT_USER_IO", "validation", console_unknown)

    # ── safe_execute contract probes ────────────────────────────────────
    def safe_execute_timeout() -> ExecutionResult:
        adapter = _TimeoutProbeAdapter()
        return _run(adapter.safe_execute("PROBE_HANG", {}, timeout=0.05))

    def safe_execute_exception() -> ExecutionResult:
        adapter = _ExceptionProbeAdapter()
        return _run(adapter.safe_execute("PROBE_BOOM", {}))

    def safe_execute_credentials() -> ExecutionResult:
        adapter = _CredentialsProbeAdapter()
        return _run(
            adapter.safe_execute("PROBE_CREDS", {}, credentials={"probe": "ok"})
        )

    add("safe_execute_timeout_envelope", "probe_timeout", "PROBE_HANG", "timeout", safe_execute_timeout)
    add("safe_execute_exception_envelope", "probe_exception", "PROBE_BOOM", "exception", safe_execute_exception)
    add(
        "safe_execute_credentials_accepted",
        "probe_credentials",
        "PROBE_CREDS",
        "none",
        safe_execute_credentials,
    )

    # ── adapter validation rows (13 previously unexercised adapters) ────
    def browser_validation() -> ExecutionResult:
        from intentframe_executor_pack_macos.adapters.browser import BrowserAdapter

        adapter = BrowserAdapter()
        return _run(adapter.safe_execute(ActionType.OPEN_URL.value, {}))

    def calendar_validation() -> ExecutionResult:
        from intentframe_executor_pack_macos.adapters.calendar import CalendarAdapter

        adapter = CalendarAdapter()
        return _run_with_platform_patch(
            "intentframe_executor_pack_macos.adapters.calendar",
            adapter,
            ActionType.CREATE_EVENT.value,
            {},
        )

    def clipboard_validation() -> ExecutionResult:
        from intentframe_executor_pack_macos.adapters.clipboard import ClipboardAdapter

        adapter = ClipboardAdapter()
        return _run(adapter.safe_execute("NOT_CLIPBOARD", {}))

    def contacts_validation() -> ExecutionResult:
        from intentframe_executor_pack_macos.adapters.contacts import ContactsAdapter

        adapter = ContactsAdapter()
        return _run_with_platform_patch(
            "intentframe_executor_pack_macos.adapters.contacts",
            adapter,
            ActionType.ADD_CONTACT.value,
            {},
        )

    def mail_validation() -> ExecutionResult:
        from intentframe_executor_pack_macos.adapters.mail import MailAdapter

        adapter = MailAdapter()
        return _run(adapter.safe_execute(ActionType.SEND_EMAIL.value, {}))

    def messages_validation() -> ExecutionResult:
        from intentframe_executor_pack_macos.adapters.messages import MessagesAdapter

        adapter = MessagesAdapter()
        return _run_with_platform_patch(
            "intentframe_executor_pack_macos.adapters.messages",
            adapter,
            ActionType.SEND_MESSAGE.value,
            {},
        )

    def notes_validation() -> ExecutionResult:
        from intentframe_executor_pack_macos.adapters.notes import NotesAdapter

        adapter = NotesAdapter()
        return _run_with_platform_patch(
            "intentframe_executor_pack_macos.adapters.notes",
            adapter,
            ActionType.CREATE_NOTE.value,
            {},
        )

    def notifications_validation() -> ExecutionResult:
        from intentframe_executor_pack_macos.adapters.notifications import NotificationsAdapter

        adapter = NotificationsAdapter()
        return _run_with_platform_patch(
            "intentframe_executor_pack_macos.adapters.notifications",
            adapter,
            ActionType.SHOW_NOTIFICATION.value,
            {},
        )

    def reminders_validation() -> ExecutionResult:
        from intentframe_executor_pack_macos.adapters.reminders import RemindersAdapter

        adapter = RemindersAdapter()
        return _run_with_platform_patch(
            "intentframe_executor_pack_macos.adapters.reminders",
            adapter,
            ActionType.CREATE_REMINDER.value,
            {},
        )

    def shortcuts_validation() -> ExecutionResult:
        from intentframe_executor_pack_macos.adapters.shortcuts import ShortcutsAdapter

        adapter = ShortcutsAdapter()
        return _run(adapter.safe_execute("RUN_SHORTCUT", {}))

    def spotlight_validation() -> ExecutionResult:
        from intentframe_executor_pack_macos.adapters.spotlight import SpotlightAdapter

        adapter = SpotlightAdapter()
        return _run(adapter.safe_execute(ActionType.SEARCH_SPOTLIGHT.value, {}))

    def system_validation() -> ExecutionResult:
        from intentframe_executor_pack_macos.adapters.system import SystemAdapter

        adapter = SystemAdapter()
        return _run_with_platform_patch(
            "intentframe_executor_pack_macos.adapters.system",
            adapter,
            "SET_VOLUME",
            {},
        )

    def user_io_validation() -> ExecutionResult:
        from intentframe_executor_pack_macos.adapters.user_io import UserIOAdapter

        adapter = UserIOAdapter()
        return _run(adapter.safe_execute("NOT_USER_IO", {}))

    add("browser_validation_missing_url", "browser", "OPEN_URL", "validation", browser_validation)
    add("calendar_validation_empty_params", "calendar", "CREATE_EVENT", "validation", calendar_validation)
    add("clipboard_validation_unknown_action", "clipboard", "NOT_CLIPBOARD", "validation", clipboard_validation)
    add("contacts_validation_empty_params", "contacts", "ADD_CONTACT", "validation", contacts_validation)
    add("mail_validation_missing_account", "mail", "SEND_EMAIL", "validation", mail_validation)
    add("messages_validation_empty_params", "messages", "SEND_MESSAGE", "validation", messages_validation)
    add("notes_validation_empty_params", "notes", "CREATE_NOTE", "validation", notes_validation)
    add(
        "notifications_validation_empty_params",
        "notifications",
        "SHOW_NOTIFICATION",
        "validation",
        notifications_validation,
    )
    add("reminders_validation_empty_params", "reminders", "CREATE_REMINDER", "validation", reminders_validation)
    add("shortcuts_validation_missing_name", "shortcuts", "RUN_SHORTCUT", "validation", shortcuts_validation)
    add("spotlight_validation_missing_query", "spotlight", "SEARCH_SPOTLIGHT", "validation", spotlight_validation)
    add("system_validation_platform_action", "system", "SET_VOLUME", "validation", system_validation)
    add("user_io_validation_empty_params", "user_io", "NOT_USER_IO", "validation", user_io_validation)

    return tuple(cases)


def _result_to_row(case: ActionCase, result: ExecutionResult) -> ActionRow:
    return ActionRow(
        case_id=case.case_id,
        adapter=case.adapter,
        action=case.action,
        success=result.success,
        data_keys=_sorted_keys(result),
        error_keyword=_error_keyword(result),
        wall=case.wall,
        rollback_available="true" if result.rollback_available else "false",
        rollback_id_prefix=_rollback_id_prefix(result.rollback_id),
        extras_keys=_extras_keys(result),
    )


def capture_action_rows() -> tuple[ActionRow, ...]:
    rows: list[ActionRow] = []
    for case in action_cases():
        result = case.run()
        rows.append(_result_to_row(case, result))
    return tuple(rows)


def capture_manifest_rows() -> tuple[ManifestRow, ...]:
    import importlib

    from executor_sdk.adapters import _ADAPTER_REGISTRY, register_adapter
    from intentframe_executor_pack_macos.adapters import _ADAPTER_SPECS, register_all_adapters

    _ADAPTER_REGISTRY.clear()
    register_all_adapters()
    register_adapter("console_user_io", ConsoleUserIOAdapter)

    rows: list[ManifestRow] = []
    seen: set[str] = set()

    specs = list(_ADAPTER_SPECS) + [
        ("console_user_io", "executor.adapters.console_user_io", "ConsoleUserIOAdapter"),
    ]
    for adapter_id, module_path, class_name in specs:
        if adapter_id in seen:
            continue
        seen.add(adapter_id)
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            if adapter_id == "host_files":
                with _temp_dirs(prefix="if_manifest_") as root:
                    instance = cls(
                        host_files_cfg=HostFilesConfig(
                            allowed_read_paths=[str(root)],
                            allowed_write_paths=[str(root)],
                        )
                    )
            else:
                instance = cls()
        except ModuleNotFoundError as exc:
            missing = exc.name or ""
            if missing.split(".")[0] in _OPTIONAL_ADAPTER_DEPS:
                continue
            raise
        except Exception as exc:
            raise RuntimeError(
                f"adapter {adapter_id!r} failed to instantiate: {exc}"
            ) from exc
        actions = sorted(instance.supported_actions())
        manifest = instance.manifest()
        assert manifest.adapter_id == adapter_id, (
            f"manifest.adapter_id={manifest.adapter_id!r} != {adapter_id!r}"
        )
        rows.append(
            ManifestRow(
                adapter_id=adapter_id,
                action_count=len(actions),
                requires_credentials=manifest.requires_credentials,
                version=manifest.version,
                actions=",".join(actions),
            )
        )
    return tuple(sorted(rows, key=lambda r: r.adapter_id))


def gateway_uses_safe_execute() -> bool:
    """AST walk: WorkerPool must only await adapter.safe_execute/safe_rollback."""
    from executor.worker_pool import WorkerPool

    source = inspect.getsource(WorkerPool)
    tree = ast.parse(source)

    forbidden_direct_calls: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Await):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr in {"execute", "rollback"}:
            forbidden_direct_calls.append(func.attr)

    return not forbidden_direct_calls


def parse_baseline_commit(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("Pre-refactor commit:"):
            return line.split(":", 1)[1].strip()
    return None


def assert_baseline_commit_matches() -> None:
    if not BASELINE_PATH.is_file():
        return
    fixture_commit = parse_baseline_commit(BASELINE_PATH.read_text(encoding="utf-8"))
    assert fixture_commit == BASELINE_COMMIT, (
        f"BASELINE_COMMIT in lib ({BASELINE_COMMIT!r}) != "
        f"fixture header ({fixture_commit!r})"
    )


BASELINE_PATH = Path(__file__).resolve().parent / "fixtures" / "executor_action_matrix_baseline.txt"


def format_matrix_snapshot(
    action_rows: tuple[ActionRow, ...],
    manifest_rows: tuple[ManifestRow, ...],
    *,
    safe_execute_ok: bool,
) -> str:
    lines = [
        "EXECUTOR ACTION MATRIX",
        "=" * 72,
        f"Pre-refactor commit: {BASELINE_COMMIT}",
        "",
        "ACTION ROWS",
        "-" * 72,
        (
            "case_id|adapter|action|success|data_keys|error_keyword|wall|"
            "rollback|rollback_id_prefix|extras_keys"
        ),
    ]
    for row in action_rows:
        lines.append(
            f"{row.case_id}|{row.adapter}|{row.action}|"
            f"{'true' if row.success else 'false'}|{row.data_keys}|"
            f"{row.error_keyword}|{row.wall}|{row.rollback_available}|"
            f"{row.rollback_id_prefix}|{row.extras_keys}"
        )
    lines.extend([
        "",
        "MANIFEST ROWS",
        "-" * 72,
        "adapter_id|action_count|requires_credentials|version|actions",
    ])
    for row in manifest_rows:
        cred = "true" if row.requires_credentials else "false"
        lines.append(
            f"{row.adapter_id}|{row.action_count}|{cred}|{row.version}|{row.actions}"
        )
    lines.extend([
        "",
        "EXECUTION CONTRACT",
        "-" * 72,
        f"worker_pool_uses_safe_execute={'yes' if safe_execute_ok else 'no'}",
    ])
    return "\n".join(lines) + "\n"


def parse_action_rows(text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    in_rows = False
    header = (
        "case_id|adapter|action|success|data_keys|error_keyword|wall|"
        "rollback|rollback_id_prefix|extras_keys"
    )
    for line in text.splitlines():
        if line.startswith(header):
            in_rows = True
            continue
        if not in_rows:
            continue
        if not line.strip() or line.startswith("-") or line.startswith("="):
            in_rows = False
            continue
        parts = line.split("|")
        if len(parts) < 10:
            continue
        case_id = parts[0]
        payload = "|".join(parts[2:])
        rows[case_id] = payload
    return rows


def parse_manifest_rows(text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    in_rows = False
    for line in text.splitlines():
        if line.startswith("adapter_id|action_count|requires_credentials|version|actions"):
            in_rows = True
            continue
        if not in_rows:
            continue
        if not line.strip() or line.startswith("-") or line.startswith("="):
            in_rows = False
            continue
        adapter_id, count, cred, version, actions = line.split("|", 4)
        rows[adapter_id] = f"{count}|{cred}|{version}|{actions}"
    return rows


def parse_safe_execute_contract(text: str) -> bool | None:
    for line in text.splitlines():
        if line.startswith("worker_pool_uses_safe_execute="):
            return line.split("=", 1)[1].strip() == "yes"
    return None


def require_darwin() -> None:
    if sys.platform != "darwin":
        raise RuntimeError(
            "executor action matrix requires macOS (path canonicalization, "
            "floor prefixes, and native adapters are platform-specific)"
        )
