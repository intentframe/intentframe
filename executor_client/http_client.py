"""
Executor HTTP Client — calls the Executor service over HTTP/UDS.

Implements the Executor ABC from intentframe_components.executor.base so the
Runtime can use it as a drop-in replacement for the in-process ExecutorBridge.

Handles:
    1. IntentFrame → ExecutionRequest translation
    2. HMAC request signing
    3. HTTP POST to executor service over UDS
    4. ExecutionResult translation back to intentframe types

This module has zero dependency on the executor server package.  Wire-protocol
models are imported from executor_client.models.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Any

import httpx

from intentframe_core.types import (
    ExecutionResult as IFExecutionResult,
    IntentFrame,
)
from intentframe_components.executor.base import Executor

from executor_client.models import (
    AuthorizationProof,
    ExecutionRequest,
    ExecutionResult as WireExecutionResult,
    RequestMetadata,
)

logger = logging.getLogger(__name__)

DEFAULT_SOCKET = "~/.intentframe/run/executor.sock"
_DEMO_HMAC_KEY = "intentframe_demo_secret_key_do_not_use_in_production"

# ── Result reshaping: adapter result dict → IntentFrame result dict ────────
# Only needed when the adapter's output key doesn't match what the caller
# expects.  Actions not listed here pass through unchanged.
_RESULT_MAP: dict[str, Any] = {
    "LIST_DIRECTORY": lambda d: {"files": d.get("entries", d.get("files", []))},
    "READ_FILE":      lambda d: {"content": d.get("content", "")},
    "RUN_COMMAND":    lambda d: {"content": d.get("stdout", "")},
    "APPEND_ROW":     lambda d: {"appended": True},
    "ASK_USER":       lambda d: {"response": d.get("response")},
    "SHOW_OPTIONS":   lambda d: {"response": d.get("response")},
}


class ExecutorHTTPClient(Executor):
    """Executor ABC implementation that calls the executor service over HTTP/UDS.

    Drop-in replacement for the ExecutorBridge. The Runtime doesn't
    know or care that execution happens in a different process.
    """

    def __init__(
        self,
        socket_path: str = DEFAULT_SOCKET,
        hmac_key: str = _DEMO_HMAC_KEY,
    ) -> None:
        self._socket = os.path.expanduser(socket_path)
        self._hmac_key = hmac_key.encode() if isinstance(hmac_key, str) else hmac_key
        self._transport = httpx.HTTPTransport(uds=self._socket)
        self._client = httpx.Client(
            transport=self._transport,
            base_url="http://executor",
            timeout=60.0,
        )

    def close(self) -> None:
        self._client.close()

    def execute(self, validated_intent: IntentFrame) -> IFExecutionResult:
        action = validated_intent.action.value

        request = self._to_execution_request(validated_intent, action)
        resp = self._client.post("/execute", json=request.model_dump(mode="json"))
        resp.raise_for_status()

        wire_result = WireExecutionResult.model_validate(resp.json())
        translated_data = self._translate_result_data(action, wire_result.data)

        return IFExecutionResult(
            success=wire_result.success,
            data=translated_data,
            error=wire_result.error,
            execution_id=wire_result.execution_id,
            timestamp=wire_result.timestamp,
        )

    def _to_execution_request(
        self, intent: IntentFrame, action: str,
    ) -> ExecutionRequest:
        params = self._translate_params(action, intent)

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

    @staticmethod
    def _translate_params(action: str, intent: IntentFrame) -> dict[str, Any]:
        """Build adapter params from the IntentFrame.

        ``intent.data`` is forwarded as-is (field names already match
        adapter keys).  ``intent.target`` is always included as ``path``
        for file-based adapters.
        """
        params: dict[str, Any] = dict(intent.data or {})
        params["path"] = intent.target
        return params

    @staticmethod
    def _translate_result_data(
        action: str, data: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if data is None:
            return None
        translator = _RESULT_MAP.get(action)
        return translator(data) if translator else data
