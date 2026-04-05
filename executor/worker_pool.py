"""
Worker pool -- manages concurrent adapter execution with limits and timeouts.

The worker pool enforces:
    - Concurrency limits (semaphore-based, configurable max_workers)
    - Timeout enforcement (via adapter's safe_execute, which uses asyncio.wait_for)
    - Clean shutdown (drain in-flight work before stopping)

Design:
    The skeleton uses asyncio.Semaphore for concurrency control.
    All adapters run in the gateway's event loop via async execution.

    Future enhancement (platform-specific):
        ProcessPoolExecutor for crash isolation -- if an adapter crashes
        the worker process, the gateway survives. This requires running
        a new event loop per worker process and marshalling results back.
        The interface stays the same; only the internal execution changes.
"""

from __future__ import annotations

import asyncio
import logging
import time

from executor.adapters.base import CapabilityAdapter
from executor.constants import DEFAULT_ADAPTER_TIMEOUT, DEFAULT_MAX_WORKERS
from executor.models import ExecutionResult

logger = logging.getLogger(__name__)

__all__ = ["WorkerPool"]


class WorkerPool:
    """Manages concurrent adapter execution with limits and timeouts.

    Usage:
        pool = WorkerPool(max_workers=4, default_timeout=30.0)
        result = await pool.submit(adapter, "SEND_EMAIL", params, credentials)
        # result is always an ExecutionResult (never raises)

        await pool.shutdown()  # drain and stop

    Guarantees:
        - At most max_workers adapters execute concurrently.
        - Each execution respects its timeout (via safe_execute).
        - submit() always returns ExecutionResult (never raises).
        - shutdown() waits for in-flight work to complete.
    """

    def __init__(
        self,
        max_workers: int = DEFAULT_MAX_WORKERS,
        default_timeout: float = DEFAULT_ADAPTER_TIMEOUT,
    ) -> None:
        self._max_workers = max_workers
        self._default_timeout = default_timeout
        self._semaphore = asyncio.Semaphore(max_workers)
        self._active_count = 0
        self._shutdown_event = asyncio.Event()
        self._is_shutdown = False

    @property
    def max_workers(self) -> int:
        """Maximum number of concurrent workers."""
        return self._max_workers

    @property
    def active_count(self) -> int:
        """Number of currently executing workers."""
        return self._active_count

    @property
    def is_shutdown(self) -> bool:
        """Whether the pool has been shut down."""
        return self._is_shutdown

    async def submit(
        self,
        adapter: CapabilityAdapter,
        action: str,
        params: dict,
        credentials: dict | None = None,
        timeout: float | None = None,
    ) -> ExecutionResult:
        """Submit an action for execution with concurrency control.

        Blocks (via semaphore) if max_workers are already executing.
        Delegates to adapter.safe_execute() which handles timeout and
        exception catching.

        Args:
            adapter: The capability adapter to execute.
            action: The action type (e.g., "SEND_EMAIL").
            params: Action-specific parameters.
            credentials: Credentials from vault (if needed).
            timeout: Override timeout for this execution. Uses default if None.

        Returns:
            ExecutionResult -- always, even on failure or pool shutdown.
        """
        if self._is_shutdown:
            return ExecutionResult(
                success=False,
                error="Worker pool is shut down",
            )

        effective_timeout = timeout or self._default_timeout
        adapter_id = adapter.manifest().adapter_id

        async with self._semaphore:
            self._active_count += 1
            start_time = time.monotonic()

            try:
                logger.debug(
                    "Worker starting: adapter=%s action=%s active=%d/%d",
                    adapter_id,
                    action,
                    self._active_count,
                    self._max_workers,
                )

                result = await adapter.safe_execute(
                    action=action,
                    params=params,
                    credentials=credentials,
                    timeout=effective_timeout,
                )

                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                result.duration_ms = elapsed_ms

                logger.debug(
                    "Worker completed: adapter=%s action=%s success=%s duration=%dms",
                    adapter_id,
                    action,
                    result.success,
                    elapsed_ms,
                )

                return result

            finally:
                self._active_count -= 1
                if self._active_count == 0 and self._is_shutdown:
                    self._shutdown_event.set()

    async def shutdown(self, timeout: float = 10.0) -> None:
        """Gracefully shut down the worker pool.

        Stops accepting new work and waits for in-flight executions
        to complete (up to timeout seconds).

        Args:
            timeout: Maximum seconds to wait for in-flight work.
        """
        self._is_shutdown = True

        if self._active_count > 0:
            logger.info(
                "Worker pool shutting down: waiting for %d active workers",
                self._active_count,
            )
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    "Worker pool shutdown timed out with %d active workers",
                    self._active_count,
                )
        else:
            logger.info("Worker pool shut down (no active workers)")
