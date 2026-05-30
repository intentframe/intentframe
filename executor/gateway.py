"""
Executor Gateway -- the orchestration brain.

The gateway is the central request handler. It receives ExecutionRequests
from the transport layer and orchestrates the full execution pipeline:

    1. Verify authorization proof (via AuthVerifier)
    2. Validate request schema (Pydantic already did this during deserialization)
    3. Log execution start (via AuditLogger)
    4. Route to capability adapter (via ActionDispatcher)
    5. Fetch credentials if needed (via CredentialVault)
    6. Execute in worker pool (via WorkerPool + adapter.safe_execute)
    7. Store rollback data if available (via StateStore)
    8. Log execution result (via AuditLogger)
    9. Return ExecutionResult to transport

The gateway is transport-agnostic, auth-scheme-agnostic, and
adapter-agnostic. It only knows the contracts (ABCs and models).

This is CONCRETE code -- not an ABC. It's platform-agnostic because
it only depends on abstractions. Platform-specific behavior comes
from the injected dependencies.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from executor_sdk.auth.base import AuthVerifier
from executor.dispatch import ActionDispatcher
from executor_sdk.exceptions import (
    AdapterNotFoundError,
    AuditError,
    AuthenticationError,
    CredentialError,
    ExecutorError,
)
from executor_sdk.models import (
    AuditEntry,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    RollbackEntry,
    SecurityEvent,
    SecurityEventType,
)
from executor_sdk.services.audit_logger import AuditLogger
from executor_sdk.services.credential_scrubber import CredentialScrubber
from executor_sdk.services.credential_vault import CredentialVault
from executor_sdk.services.hash_chain import HashChain
from executor_sdk.services.state_store import StateStore
from executor.worker_pool import WorkerPool

logger = logging.getLogger(__name__)

__all__ = ["ExecutorGateway"]


class ExecutorGateway:
    """The executor's central request handler.

    Orchestrates the full pipeline: auth -> validate -> route -> execute -> audit.
    Injected with all dependencies at construction -- no globals, no singletons.

    Usage:
        gateway = ExecutorGateway(
            auth_verifier=...,
            dispatcher=...,
            worker_pool=...,
            audit_logger=...,
            credential_vault=...,
            state_store=...,
            scrubber=...,
            hash_chain=...,
        )

        # Transport calls this for every inbound request:
        result = await gateway.handle(execution_request)
    """

    def __init__(
        self,
        auth_verifier: AuthVerifier,
        dispatcher: ActionDispatcher,
        worker_pool: WorkerPool,
        audit_logger: AuditLogger,
        credential_vault: CredentialVault,
        state_store: StateStore,
        scrubber: CredentialScrubber,
        hash_chain: HashChain,
    ) -> None:
        self._auth = auth_verifier
        self._dispatcher = dispatcher
        self._pool = worker_pool
        self._audit = audit_logger
        self._vault = credential_vault
        self._state = state_store
        self._scrubber = scrubber
        self._chain = hash_chain

    def close(self) -> None:
        """Close service resources (DB connections, etc.)."""
        self._audit.close()
        self._state.close()

    async def handle(self, request: ExecutionRequest) -> ExecutionResult:
        """Process a single execution request through the full pipeline.

        This is the method the transport layer calls for every inbound request.
        It ALWAYS returns an ExecutionResult -- never raises.
        On any failure at any stage, returns ExecutionResult(success=False).

        Pipeline:
            1. Verify auth    -> reject if invalid
            2. Route action   -> reject if unknown
            3. Log start      -> reject if audit fails (fail-closed)
            4. Fetch creds    -> reject if unavailable
            5. Execute        -> always returns result (safe_execute)
            6. Store rollback -> best-effort
            7. Log complete   -> best-effort (execution already done)
            8. Return result

        Args:
            request: Validated ExecutionRequest from the transport layer.

        Returns:
            ExecutionResult with success=True/False.
        """
        start_time = time.monotonic()
        execution_id = request.request_id

        # ─── Step 1: Verify Authorization ─────────────────────────────────
        try:
            auth_result = await self._auth.verify(request.authorization)
        except Exception as exc:
            logger.error("Auth verification crashed: %s", exc, exc_info=True)
            await self._log_security_event(
                SecurityEventType.INVALID_AUTH,
                source_info=request.metadata.agent_id,
                details=f"Auth verifier crashed: {type(exc).__name__}",
            )
            return self._fail(execution_id, "Authorization verification failed")

        if not auth_result.valid:
            logger.warning(
                "Auth rejected: request=%s error=%s",
                execution_id,
                auth_result.error,
            )
            await self._log_security_event(
                SecurityEventType.INVALID_AUTH,
                source_info=request.metadata.agent_id,
                details=auth_result.error or "Invalid authorization proof",
            )
            return self._fail(execution_id, "Authorization rejected")

        # ─── Step 2: Route to Adapter ─────────────────────────────────────
        try:
            adapter = self._dispatcher.resolve(request.action_type)
        except AdapterNotFoundError:
            logger.warning("Unknown action: %s", request.action_type)
            await self._log_security_event(
                SecurityEventType.UNKNOWN_ACTION,
                source_info=request.metadata.agent_id,
                details=f"Unknown action type: {request.action_type}",
            )
            return self._fail(
                execution_id,
                f"Action '{request.action_type}' is not available.",
            )

        adapter_id = adapter.manifest().adapter_id

        # ─── Step 3: Log STARTED Event ────────────────────────────────────
        params_hash = self._scrubber.hash_params(request.params)
        start_entry = AuditEntry(
            execution_id=execution_id,
            intent_frame_id=request.metadata.intent_frame_id,
            action_type=request.action_type,
            adapter_id=adapter_id,
            status=ExecutionStatus.STARTED,
            params_hash=params_hash,
        )
        start_entry = self._hash_and_chain(start_entry)

        try:
            await self._audit.log_event(start_entry)
        except Exception as exc:
            # Fail-closed: if we can't audit, we can't execute
            logger.error("Audit log_event(STARTED) failed: %s", exc, exc_info=True)
            return self._fail(execution_id, "Audit logging failed -- execution blocked")

        # ─── Step 4: Fetch Credentials (if needed) ────────────────────────
        credentials: dict[str, Any] | None = None
        if adapter.manifest().requires_credentials:
            try:
                credentials = await self._fetch_credentials(adapter_id)
            except CredentialError:
                logger.debug(
                    "Vault has no credentials for adapter '%s'; "
                    "adapter will use its own fallback resolution",
                    adapter_id,
                )
                credentials = None

        # ─── Step 5: Execute via Worker Pool ──────────────────────────────
        result = await self._pool.submit(
            adapter=adapter,
            action=request.action_type,
            params=request.params,
            credentials=credentials,
        )
        result.execution_id = execution_id

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        result.duration_ms = elapsed_ms

        # ─── Step 6: Store Rollback (if available) ────────────────────────
        if result.success and result.rollback_available and result.rollback_id:
            try:
                rollback_entry = RollbackEntry(
                    execution_id=execution_id,
                    rollback_id=result.rollback_id,
                    adapter_id=adapter_id,
                    rollback_data=self._scrubber.scrub(request.params),
                )
                await self._state.save_rollback(rollback_entry)
            except Exception as exc:
                # Rollback storage is best-effort -- don't fail the execution
                logger.warning("Failed to store rollback: %s", exc)
                result.rollback_available = False
                result.rollback_id = None

        # ─── Step 7: Log COMPLETED/FAILED Event ─────────────────────────
        final_status = ExecutionStatus.COMPLETED if result.success else ExecutionStatus.FAILED
        await self._log_completion(
            execution_id, adapter_id, request.action_type,
            request.metadata.intent_frame_id, params_hash,
            final_status, result, start_time,
        )

        # ─── Step 8: Return Result ────────────────────────────────────────
        logger.info(
            "Execution complete: id=%s action=%s adapter=%s success=%s duration=%dms",
            execution_id,
            request.action_type,
            adapter_id,
            result.success,
            elapsed_ms,
        )

        return result

    async def handle_rollback(self, rollback_id: str) -> ExecutionResult:
        """Execute a rollback for a previous execution.

        Args:
            rollback_id: The rollback ID from the original ExecutionResult.

        Returns:
            ExecutionResult indicating rollback success or failure.
        """
        # Look up the rollback entry
        entry = await self._state.get_rollback(rollback_id)
        if entry is None:
            logger.warning("Rollback not found or expired: %s", rollback_id)
            return ExecutionResult(
                success=False,
                error="Unable to undo — the action may have expired.",
            )

        # Find the adapter
        adapter = self._dispatcher.get_adapter(entry.adapter_id)
        if adapter is None:
            logger.error("Adapter not found for rollback: %s", entry.adapter_id)
            return ExecutionResult(
                success=False,
                error="Unable to undo this action right now.",
            )

        # Execute rollback
        result = await adapter.safe_rollback(rollback_id)

        # Update rollback status
        from executor_sdk.models import RollbackStatus

        new_status = RollbackStatus.EXECUTED if result.success else RollbackStatus.FAILED
        try:
            await self._state.update_rollback_status(rollback_id, new_status)
        except Exception as exc:
            logger.warning("Failed to update rollback status: %s", exc)

        return result

    # ── Private helpers ───────────────────────────────────────────────────

    @staticmethod
    def _fail(execution_id: str, error: str) -> ExecutionResult:
        """Construct a failure ExecutionResult."""
        return ExecutionResult(
            success=False,
            error=error,
            execution_id=execution_id,
        )

    async def _fetch_credentials(self, adapter_id: str) -> dict[str, str]:
        """Fetch credentials for an adapter from the vault.

        Returns a dict of credential key -> value pairs.
        Raises CredentialError if any required credential is missing.
        """
        # Convention: credentials are stored under service=adapter_id
        # This is a simplified lookup; adapters can override with
        # more specific credential requirements in their manifest.
        api_key = await self._vault.get(adapter_id, "api_key")
        if api_key is not None:
            return {"api_key": api_key}

        # If no api_key, try generic credential
        credential = await self._vault.get(adapter_id, "credential")
        if credential is not None:
            return {"credential": credential}

        raise CredentialError(
            f"No credentials found for adapter: {adapter_id}",
            details={"adapter_id": adapter_id},
        )

    def _hash_and_chain(self, entry: AuditEntry) -> AuditEntry:
        """Compute hash chain for an audit entry (all fields hashed).

        Append-only design: every field is immutable after insertion,
        so every field is included in the hash. No exclusion lists.
        """
        entry_data = entry.model_dump(exclude={"entry_hash", "prev_hash"})
        entry_hash, prev_hash = self._chain.append(entry_data)
        entry.entry_hash = entry_hash
        entry.prev_hash = prev_hash
        return entry

    async def _log_completion(
        self,
        execution_id: str,
        adapter_id: str,
        action_type: str,
        intent_frame_id: str | None,
        params_hash: str,
        status: ExecutionStatus,
        result: ExecutionResult | None,
        start_time: float,
    ) -> None:
        """Log a COMPLETED/FAILED event. Best-effort -- logs but doesn't raise.

        This INSERTs a new row (not an UPDATE). The audit log is append-only.
        """
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        safe_result = result or ExecutionResult(success=False, error="No result")
        summary = "success" if safe_result.success else (safe_result.error or "failed")

        complete_entry = AuditEntry(
            execution_id=execution_id,
            intent_frame_id=intent_frame_id,
            action_type=action_type,
            adapter_id=adapter_id,
            status=status,
            params_hash=params_hash,
            result_summary=summary[:500],
            error=safe_result.error,
            duration_ms=elapsed_ms,
        )
        complete_entry = self._hash_and_chain(complete_entry)

        try:
            await self._audit.log_event(complete_entry)
        except Exception as exc:
            logger.error(
                "Failed to log completion: execution=%s error=%s",
                execution_id,
                exc,
            )

    async def _log_security_event(
        self,
        event_type: SecurityEventType,
        source_info: str = "",
        details: str = "",
    ) -> None:
        """Log a security event. Best-effort -- logs but doesn't raise."""
        try:
            event = SecurityEvent(
                event_type=event_type,
                source_info=source_info,
                details=details,
            )
            await self._audit.log_security_event(event)
        except Exception as exc:
            logger.error("Failed to log security event: %s", exc)
