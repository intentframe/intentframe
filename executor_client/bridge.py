"""
ExecutorBridge -- Adapter between IntentFrame and the production Executor.

Client-side code that translates IntentFrame types into ExecutionRequest
types, signs requests with HMAC, and forwards them through the
ExecutorGateway. Neither intentframe nor executor depend on each other;
this module is the glue between them.

Responsibilities:
    1. Convert IntentFrame  -> production ExecutionRequest
    2. Translate action-specific params  (IntentFrame shape -> adapter shape)
    3. Sign the request with HMAC  (gateway requires auth proof)
    4. Call the production gateway  (in-process for demo, async->sync bridge)
    5. Translate result data back   (adapter shape -> IntentFrame shape)
    6. Convert production ExecutionResult -> IntentFrame ExecutionResult

Usage:
    # Quick setup for demo (via ResourceRegistry):
    executor_view = registry.executor_view("my_workspace")
    bridge = ExecutorBridge.create_for_demo(executor_view=executor_view)
    executor = InvoiceExecutor(bridge=bridge)

    # Or wire manually:
    bridge = ExecutorBridge(gateway=my_gateway, hmac_key="my_secret")
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import hmac
import logging
import tempfile
from pathlib import Path
from typing import Any

# ── IntentFrame types ─────────────────────────────────────────────────────────
from action_registry import ActionType  # noqa: F401 -- canonical source of truth
from intentframe_core.types import (
    ExecutionResult as DemoExecutionResult,
    IntentFrame,
)

# ── Production executor types ─────────────────────────────────────────────────
from executor.gateway import ExecutorGateway
from executor_client.models import (
    AuthorizationProof,
    ExecutionRequest,
    ExecutionResult as ProductionExecutionResult,
    RequestMetadata,
)

logger = logging.getLogger(__name__)

# Demo HMAC key -- in production this comes from the credential vault
_DEMO_HMAC_KEY = "intentframe_demo_secret_key_do_not_use_in_production"


# ═════════════════════════════════════════════════════════════════════════════
# Executor Bridge
# ═════════════════════════════════════════════════════════════════════════════

class ExecutorBridge:
    """Translates between IntentFrame world and production executor world.

    Handles:
        - IntentFrame (dataclass) -> ExecutionRequest (Pydantic) conversion
        - Action-specific parameter shaping  (demo dict -> adapter dict)
        - HMAC request signing  (gateway requires auth proof)
        - Sync-to-async bridging  (demo is sync, gateway is async)
        - Action-specific result translation  (adapter dict -> demo dict)
        - Production ExecutionResult -> demo ExecutionResult conversion
    """

    def __init__(
        self,
        gateway: ExecutorGateway,
        hmac_key: str = _DEMO_HMAC_KEY,
    ) -> None:
        self._gateway = gateway
        self._hmac_key = (
            hmac_key.encode() if isinstance(hmac_key, str) else hmac_key
        )

    # ── Public API ────────────────────────────────────────────────────────

    def forward(self, intent: IntentFrame) -> DemoExecutionResult:
        """Forward a demo IntentFrame through the production executor.

        This is the single entry point. InvoiceExecutor calls this
        instead of doing direct I/O.

        Args:
            intent: Demo IntentFrame (already validated by Guardian).

        Returns:
            Demo ExecutionResult (dataclass) with data shaped to match
            what the demo agent expects.
        """
        action = intent.action.value  # e.g. ActionType.READ_FILE -> "READ_FILE"

        # 1. Build production request with translated params
        request = self._to_execution_request(intent, action)

        # 2. Call gateway (async -> sync bridge)
        prod_result = self._run_async(self._gateway.handle(request))

        # 3. Translate result data back to demo shape
        translated_data = self._translate_result_data(action, prod_result.data)

        # 4. Convert to demo ExecutionResult
        return DemoExecutionResult(
            success=prod_result.success,
            data=translated_data,
            error=prod_result.error,
            execution_id=prod_result.execution_id,
            timestamp=prod_result.timestamp,
        )

    # ── Request Translation: Demo -> Production ──────────────────────────

    def _to_execution_request(
        self, intent: IntentFrame, action: str,
    ) -> ExecutionRequest:
        """Convert demo IntentFrame to production ExecutionRequest."""
        params = self._translate_params(action, intent)

        # Sign the request
        payload = f"{intent.session_id}:{intent.sequence_id}:{action}"
        signature = hmac.new(
            self._hmac_key, payload.encode(), hashlib.sha256,
        ).hexdigest()
        token = f"{payload}:{signature}"

        return ExecutionRequest(
            action_type=action,
            target=intent.target,
            params=params,
            reason=intent.reason,
            authorization=AuthorizationProof(
                scheme="guardian_hmac",
                token=token,
            ),
            metadata=RequestMetadata(
                agent_id=intent.agent_id,
                session_id=intent.session_id,
                sequence_id=intent.sequence_id,
                timestamp=intent.timestamp,
                task_description=intent.task_description,
            ),
        )

    # ── Result reshaping: adapter result dict → demo result dict ────────
    # Only needed when the adapter's output key doesn't match what the
    # demo agent expects.  Actions not listed here pass through unchanged.
    #
    # RUN_COMMAND: the terminal adapter returns
    # {stdout, stderr, return_code, command}.  We keep the historical
    # ``{"content": stdout}`` shape (that the LLM and demo harnesses
    # already read) and add ``stderr`` next to it — success or failure.
    # That single extra field is enough to make silent failures visible
    # (e.g. ``ps aux --sort=-%cpu | head`` on macOS where ps errors to
    # stderr, head exits 0, pipeline rc=0) without reshaping the payload
    # into a structured terminal-session-looking dict that primed the
    # LLM to summarise ("output above") instead of quoting the output
    # back to the user.  ``return_code`` and ``command`` are intentionally
    # not forwarded.
    _RESULT_MAP: dict[str, Any] = {
        "LIST_DIRECTORY": lambda d: {"files": d.get("entries", d.get("files", []))},
        "READ_FILE":      lambda d: {"content": d.get("content", "")},
        "RUN_COMMAND":    lambda d: {
            "content": d.get("stdout", ""),
            "stderr": d.get("stderr", ""),
        },
        "APPEND_ROW":     lambda d: {"appended": True},
        "ASK_USER":       lambda d: {"response": d.get("response")},
        "SHOW_OPTIONS":   lambda d: {"response": d.get("response")},
    }

    @classmethod
    def _translate_params(cls, action: str, intent: IntentFrame) -> dict[str, Any]:
        """Build adapter params from the IntentFrame.

        ``intent.data`` is forwarded as-is (field names already match
        adapter keys).  ``intent.target`` is always included as ``path``
        for file-based adapters.
        """
        params: dict[str, Any] = dict(intent.data or {})
        params["path"] = intent.target
        return params

    # ── Result Translation: Production -> Demo ───────────────────────────

    @classmethod
    def _translate_result_data(
        cls, action: str, data: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Reshape production adapter result data to what the demo agent expects."""
        if data is None:
            return None
        translator = cls._RESULT_MAP.get(action)
        return translator(data) if translator else data

    # ── Async-to-Sync Bridge ─────────────────────────────────────────────

    @staticmethod
    def _run_async(coro):
        """Run an async coroutine from sync code.

        Handles the case where an event loop is already running
        (e.g. called from within the async demo runtime).
        """
        try:
            asyncio.get_running_loop()
            # Loop is running -- can't nest asyncio.run().  Use a worker thread.
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=60)
        except RuntimeError:
            # No running loop -- safe to use asyncio.run() directly.
            return asyncio.run(coro)

    # ── Factory: Quick Setup for Demo ────────────────────────────────────

    @classmethod
    def create_for_demo(
        cls,
        executor_view: Any,
        hmac_key: str = _DEMO_HMAC_KEY,
        db_path: str | None = None,
    ) -> ExecutorBridge:
        """Create a fully wired bridge for demo use.

        Handles all production executor setup:
            1. Registers macOS platform implementations
            2. Creates SQLite audit logger + state store
            3. Creates HMAC auth verifier with demo key
            4. Creates file adapter from ExecutorView mount table
            5. Creates console-based UserIO adapter (matches demo behaviour)
            6. Wires the gateway
            7. Returns ready-to-use bridge

        Args:
            executor_view: ExecutorView from ResourceRegistry containing
                           the mount table and base_path for VFS setup.
            hmac_key: HMAC key for request signing (default: demo key).
            db_path: SQLite database path.  None = auto temp directory.

        Returns:
            ExecutorBridge ready to forward intents.
        """
        # ── Register macOS platform ──────────────────────────────────────
        from intentframe_executor_pack_macos import register_all

        register_all()

        # ── Auth verifier ────────────────────────────────────────────────
        from intentframe_executor_pack_macos.auth import GuardianHMACVerifier

        auth_verifier = GuardianHMACVerifier(secret_key=hmac_key)

        # ── Storage (SQLite) ─────────────────────────────────────────────
        if db_path is None:
            storage_dir = Path(tempfile.mkdtemp(prefix="intentframe_demo_"))
            db_path = str(storage_dir / "demo_executor.db")

        from intentframe_executor_pack_macos.audit_logger import SQLiteAuditLogger
        from intentframe_executor_pack_macos.state_store import SQLiteStateStore

        audit_logger = SQLiteAuditLogger(db_path=db_path)
        state_store = SQLiteStateStore(db_path=db_path)

        # ── Virtual filesystem from ExecutorView mounts ──────────────────
        from executor_sdk.services.virtual_filesystem import (
            MountPointConfig,
            MountPointResolver,
        )

        base_path = executor_view.base_path
        mount_configs = [
            MountPointConfig(
                virtual_path=m.virtual_path,
                real_path=m.real_path,
                writable=m.writable,
                file_filter=m.file_filter,
            )
            for m in executor_view.mounts
        ]
        resolver = MountPointResolver(mount_configs, base_path)

        # ── Action Catalog (source of truth) ──────────────────────────
        from action_registry import ActionCatalog
        from action_registry.platforms.macos import register_macos_actions

        catalog = ActionCatalog()
        catalog.register_defaults()
        register_macos_actions(catalog)

        # ── Adapters ─────────────────────────────────────────────────────
        from executor.dispatch import ActionDispatcher
        from intentframe_executor_pack_macos.adapters.files import FilesAdapter
        from executor.adapters.console_user_io import ConsoleUserIOAdapter

        dispatcher = ActionDispatcher(catalog=catalog)
        dispatcher.register(FilesAdapter(mount_resolver=resolver, base_path=base_path))
        dispatcher.register(ConsoleUserIOAdapter())  # console IO, not osascript

        # ── Worker pool ──────────────────────────────────────────────────
        from executor.worker_pool import WorkerPool

        worker_pool = WorkerPool(max_workers=4, default_timeout=30.0)

        # ── Credential vault (no-op for demo) ────────────────────────────
        from executor_sdk.services.credential_vault import CredentialVault

        class _DemoVault(CredentialVault):
            """No-op vault -- demo adapters don't need credentials."""

            async def get(self, service: str, key: str) -> str | None:
                return None

            async def store(self, service: str, key: str, value: str) -> None:
                pass

            async def delete(self, service: str, key: str) -> None:
                pass

            async def has(self, service: str, key: str) -> bool:
                return False

            async def list_keys(self, namespace: str) -> list[str]:
                return []

        # ── Wire gateway ─────────────────────────────────────────────────
        from executor.services.credential_scrubber import CredentialScrubber
        from executor_sdk.services.hash_chain import HashChain

        gateway = ExecutorGateway(
            auth_verifier=auth_verifier,
            dispatcher=dispatcher,
            worker_pool=worker_pool,
            audit_logger=audit_logger,
            credential_vault=_DemoVault(),
            state_store=state_store,
            scrubber=CredentialScrubber(),
            hash_chain=HashChain(),
        )

        logger.info(
            "Demo ExecutorBridge ready: %d actions via production gateway, db=%s",
            len(dispatcher.registered_actions),
            db_path,
        )

        return cls(gateway=gateway, hmac_key=hmac_key)
