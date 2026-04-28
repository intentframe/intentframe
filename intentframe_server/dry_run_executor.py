"""
DryRunExecutor — synthetic executor for safe testing.

Drop-in replacement for :class:`executor_client.http_client.ExecutorHTTPClient`
that returns synthetic ``ExecutionResult``s without performing any real I/O.
Used exclusively for tests that exercise Analysis Engine and Guardian
decisions while "running" actions on the host would be dangerous — most
notably the ``root_demo`` suites.

Activation (server-side):

    INTENTFRAME_EXECUTOR_MODE=dry_run python -m supervisor.main start

Privilege posture (controls what Guardian sees in ``ExecutionContext``):

    INTENTFRAME_DRY_RUN_CONTEXT=user   # default, reports current user's uid/euid
    INTENTFRAME_DRY_RUN_CONTEXT=root   # reports uid=0/euid=0 for root-demo tests

Every returned ``ExecutionResult.data`` carries ``dry_run=True`` so callers
(including the root-demo runner) can *positively* assert they are seeing
synthetic output and not a silent fall-through to real execution.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from intentframe_components.executor.base import Executor
from intentframe_core.types import ExecutionResult, IntentFrame

logger = logging.getLogger(__name__)


class DryRunExecutor(Executor):
    """Synthetic executor: reports success without touching the host.

    Matches the subset of :class:`ExecutorHTTPClient`'s surface that the
    server actually uses (``execute``, ``health``, ``close``) so swapping
    one for the other requires no downstream changes.
    """

    def execute(self, validated_intent: IntentFrame) -> ExecutionResult:
        action = validated_intent.action.value
        params = validated_intent.data or {}

        # Shape output per-action so existing consumers (the _RESULT_MAP
        # in executor_client.http_client, the root-demo adapter-output
        # printer) keep working unchanged.  The ``dry_run`` flag is the
        # ground truth every caller should key off of.
        if action == "RUN_COMMAND":
            command = str(params.get("command", ""))
            synthetic = (
                f"[dry-run] would run: {command}" if command else "[dry-run]"
            )
            data: dict[str, Any] = {
                "dry_run": True,
                "action": action,
                "command": command,
                "stdout": synthetic,
                "stderr": "",
                "content": synthetic,
            }
        else:
            synthetic = f"[dry-run] would perform: {action}"
            data = {
                "dry_run": True,
                "action": action,
                "content": synthetic,
                "stdout": synthetic,
                "stderr": "",
            }

        logger.info(
            "DryRunExecutor: action=%s params_keys=%s",
            action,
            sorted(params.keys()) if isinstance(params, dict) else [],
        )

        return ExecutionResult(
            success=True,
            data=data,
            error=None,
            execution_id="",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def health(self) -> dict[str, Any]:
        """Report a privilege posture that mirrors a real executor's ``/health``.

        By default reports the current user's ``uid``/``euid``.  Setting
        ``INTENTFRAME_DRY_RUN_CONTEXT=root`` makes the runtime (and
        therefore Guardian) see the same ``ExecutionContext`` posture
        as a real root executor — required so root-demo suites can
        exercise escalation reasoning without actually running as root.
        """
        context = os.environ.get("INTENTFRAME_DRY_RUN_CONTEXT", "user").strip().lower()

        if context == "root":
            uid, euid, as_root = 0, 0, True
        elif context == "user":
            uid = os.getuid()
            euid = os.geteuid()
            as_root = euid == 0
        else:
            raise RuntimeError(
                "Unknown INTENTFRAME_DRY_RUN_CONTEXT: "
                f"{context!r}. Expected 'user' or 'root'."
            )

        return {
            "status": "ok",
            "service": "dry-run-executor",
            "running_as_root": as_root,
            "uid": uid,
            "euid": euid,
        }

    def close(self) -> None:
        """No-op: no subprocess, no socket, nothing to release."""
        return None
