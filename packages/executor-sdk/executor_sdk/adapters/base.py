"""
Abstract base class for capability adapters.

Every capability the executor can perform (send email, read file, create
calendar event, etc.) is wrapped in a CapabilityAdapter. This is the ONLY
"framework" code in the executor -- everything else is either ABCs or
platform-specific implementations.

Key design:
    - safe_execute() is a FINAL method on the base class. It wraps every
      execute() call with timeout enforcement and exception catching.
      Adapters NEVER override safe_execute().
    - execute() is the abstract method adapters implement. It can raise,
      hang, or crash -- safe_execute() catches everything.
    - This enforces fail-closed at the framework level. No adapter can
      accidentally bypass timeout or error handling.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod

from executor_sdk.constants import DEFAULT_ADAPTER_TIMEOUT
from executor_sdk.models import AdapterManifest, ExecutionResult

logger = logging.getLogger(__name__)


class CapabilityAdapter(ABC):
    """Base class for all capability adapters.

    Subclass contract:
        1. Implement execute() with your platform-specific logic.
        2. Implement rollback() for reversible actions (return failure for irreversible).
        3. Implement supported_actions() to declare what actions you handle.
        4. Implement manifest() to declare your identity and capabilities.

    Gateway contract:
        The gateway NEVER calls execute() directly. It always calls
        safe_execute(), which wraps execute() with:
            - asyncio.wait_for(timeout=...) to enforce deadline
            - try/except catching ALL exceptions
            - On any failure or timeout -> ExecutionResult(success=False)

        This means:
            - Adapters can raise freely. Exceptions are caught.
            - Adapters can hang. Timeout kills them.
            - Adapters can crash. The failure is contained.
            - The gateway ALWAYS gets an ExecutionResult, never an exception.
    """

    # ── Abstract interface (adapters implement these) ─────────────────────

    @abstractmethod
    async def execute(
        self,
        action: str,
        params: dict,
        credentials: dict | None = None,
    ) -> ExecutionResult:
        """Perform the requested action.

        Args:
            action: The specific action (e.g., "SEND_EMAIL", "READ_FILE").
            params: Action-specific parameters.
            credentials: Credentials from the vault (if adapter requires them).
                         Passed in-process, NEVER serialized or logged.

        Returns:
            ExecutionResult with success=True/False and relevant data.

        Raises:
            Any exception -- safe_execute() will catch it.
        """
        ...

    @abstractmethod
    async def rollback(self, rollback_id: str) -> ExecutionResult:
        """Undo a previous execution (if possible).

        For irreversible actions (email send, etc.), return:
            ExecutionResult(success=False, error="Action is irreversible")

        Args:
            rollback_id: The ID from the original ExecutionResult.rollback_id.

        Returns:
            ExecutionResult indicating rollback success or failure.
        """
        ...

    @abstractmethod
    def supported_actions(self) -> list[str]:
        """Return the list of action types this adapter handles.

        The dispatcher uses this to build the action -> adapter routing table.
        Each action type must be globally unique across all registered adapters.
        """
        ...

    @abstractmethod
    def manifest(self) -> AdapterManifest:
        """Return this adapter's identity and capabilities declaration.

        Used by the dispatcher for registration and by the gateway
        for logging and diagnostics.
        """
        ...

    # ── Framework methods (adapters do NOT override these) ────────────────

    async def safe_execute(
        self,
        action: str,
        params: dict,
        credentials: dict | None = None,
        timeout: float = DEFAULT_ADAPTER_TIMEOUT,
    ) -> ExecutionResult:
        """Execute with timeout enforcement and exception catching.

        THIS IS THE ONLY METHOD THE GATEWAY CALLS.
        Adapters MUST NOT override this method.

        Guarantees:
            - Returns ExecutionResult (never raises)
            - Respects timeout (adapter is cancelled if it hangs)
            - Logs failures for diagnostics

        Args:
            action: The action to perform.
            params: Action-specific parameters.
            credentials: Credentials from vault (if needed).
            timeout: Maximum seconds to wait for execute() to return.

        Returns:
            ExecutionResult -- always, even on failure.
        """
        adapter_id = self.manifest().adapter_id

        try:
            result = await asyncio.wait_for(
                self.execute(action, params, credentials),
                timeout=timeout,
            )
            return result

        except asyncio.TimeoutError:
            logger.error(
                "Adapter timeout: adapter=%s action=%s timeout=%.1fs",
                adapter_id,
                action,
                timeout,
            )
            return ExecutionResult(
                success=False,
                error=f"{action} timed out — please try again.",
            )

        except Exception as exc:
            logger.error(
                "Adapter error: adapter=%s action=%s error=%s",
                adapter_id,
                action,
                exc,
                exc_info=True,
            )
            return ExecutionResult(
                success=False,
                error=f"{action} is temporarily unavailable.",
            )

    async def safe_rollback(
        self,
        rollback_id: str,
        timeout: float = DEFAULT_ADAPTER_TIMEOUT,
    ) -> ExecutionResult:
        """Rollback with timeout enforcement and exception catching.

        Same safety guarantees as safe_execute().
        """
        adapter_id = self.manifest().adapter_id

        try:
            result = await asyncio.wait_for(
                self.rollback(rollback_id),
                timeout=timeout,
            )
            return result

        except asyncio.TimeoutError:
            logger.error(
                "Rollback timeout: adapter=%s rollback_id=%s", adapter_id, rollback_id
            )
            return ExecutionResult(
                success=False,
                error="Undo timed out — please try again.",
            )

        except Exception as exc:
            logger.error(
                "Rollback error: adapter=%s rollback_id=%s error=%s",
                adapter_id,
                rollback_id,
                exc,
                exc_info=True,
            )
            return ExecutionResult(
                success=False,
                error="Unable to undo this action right now.",
            )
