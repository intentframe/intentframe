"""
Executor HTTP Client — calls the Executor service over HTTP/UDS.

Implements the Executor ABC from intentframe_components.executor.base so the
Runtime can use it as a drop-in replacement for the in-process ExecutorBridge.

Handles:
    1. IntentFrame → ExecutionRequest translation
    2. HMAC request signing
    3. HTTP POST to executor service over UDS
    4. Wire ExecutionResult → intentframe ExecutionResult

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

    def health(self) -> dict[str, Any]:
        """Probe the executor's /health endpoint. Raises on failure."""
        resp = self._client.get("/health")
        resp.raise_for_status()
        return resp.json()

    def execute(self, validated_intent: IntentFrame) -> IFExecutionResult:
        """Forward an allowed intent to the executor.

        ``validated_intent`` is the actor-submitted frame (post-guardian ALLOW),
        not an enriched copy — pipeline enrichment must not alter adapter params.
        """
        action = validated_intent.action

        request = self._to_execution_request(validated_intent, action)
        resp = self._client.post("/execute", json=request.model_dump(mode="json"))
        resp.raise_for_status()

        wire_result = WireExecutionResult.model_validate(resp.json())

        return IFExecutionResult(
            success=wire_result.success,
            data=wire_result.data,
            error=wire_result.error,
            execution_id=wire_result.execution_id,
            timestamp=wire_result.timestamp,
            display_summary=wire_result.display_summary,
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

        ``intent.data`` is the executable contract and is forwarded as-is
        (field names already match adapter keys, e.g. file adapters read
        ``params["path"]``).  ``intent.target`` is display/audit only and is
        never translated into params — producers must place every executable
        field (including ``path``) in ``intent.data``.
        """
        del action
        return dict(intent.data or {})
