"""
Simulated User I/O adapter -- non-interactive, deterministic responses.

Platform-neutral user-IO implementation for headless environments that have
no TTY and no GUI: demo dashboards run outside a container, CI, automated
pipelines, and smoke tests. Unlike ``console_user_io`` it never calls
``input()`` (which would EOF/hang in a supervised service) and unlike the
macOS ``user_io`` it never opens a dialog.

Behaviour (all configurable via pack_options.simulated_user_io):
    SHOW_MESSAGE      -> logs the message, returns ``show <message>``.
    ASK_USER          -> returns a canned response (``default_response``).
    GET_CONFIRMATION  -> returns a fixed decision (``auto_confirm``, default False).

UserIOService is still a PROTECTED RESOURCE: ASK_USER, SHOW_MESSAGE and
GET_CONFIRMATION all pass through the IntentFrame pipeline and Guardian before
ever reaching this adapter. This adapter only decides how the (already
authorized) prompt is *answered* when no human is attached.

Each successful interaction is stamped with a ``user_response_token`` in
``extras`` -- a SHA-256 attestation identical in shape to the other user-IO
adapters, so downstream verification is uniform.

NOTE: This adapter *simulates* a human. Selecting it via config is an explicit
statement that the deployment has no human in the loop (demo/CI). Do not use it
where a real approval gate is required -- wire a relay adapter instead.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from action_registry import ActionType
from executor_sdk.adapters.base import CapabilityAdapter
from executor_sdk.models import AdapterManifest, ExecutionResult

logger = logging.getLogger(__name__)


class SimulatedUserIOAdapter(CapabilityAdapter):
    """Non-interactive user interaction adapter for headless/demo runs."""

    def __init__(
        self,
        pack_options: dict[str, dict[str, Any]] | None = None,
        **_kwargs,
    ) -> None:
        opts = (pack_options or {}).get("simulated_user_io", {}) or {}
        self._auto_confirm: bool = bool(opts.get("auto_confirm", False))
        self._default_response: str = str(opts.get("default_response", "confirmed. add it"))

    def supported_actions(self) -> list[str]:
        return [
            ActionType.ASK_USER.value,
            ActionType.SHOW_MESSAGE.value,
            ActionType.GET_CONFIRMATION.value,
        ]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="simulated_user_io",
            name="Simulated User I/O",
            description="Non-interactive, deterministic user interaction (headless/demo)",
            supported_actions=self.supported_actions(),
            requires_credentials=False,
        )

    async def execute(
        self, action: str, params: dict, credentials: dict | None = None,
    ) -> ExecutionResult:
        if action == "SHOW_MESSAGE":
            message = params.get("message", "")
            response = f"show {message}"
            logger.info("[simulated user_io] SHOW_MESSAGE: %s", message)
            return ExecutionResult(
                success=True,
                data={"shown": True, "response": response, "simulated": True},
            )

        if action == "ASK_USER":
            return self._ask_user(params)

        if action == "GET_CONFIRMATION":
            return self._get_confirmation(params)

        return ExecutionResult(success=False, error=f"Unknown action: {action}")

    def _ask_user(self, params: dict) -> ExecutionResult:
        prompt = params.get("prompt", "")
        response = self._default_response

        logger.info("[simulated user_io] ASK_USER %r -> %r", prompt, response)
        result = ExecutionResult(success=True, data={"response": response, "simulated": True})
        result.extras["user_response_token"] = self._compute_user_response_token(
            prompt=prompt, response=response, timestamp=result.timestamp,
        )
        return result

    def _get_confirmation(self, params: dict) -> ExecutionResult:
        prompt = params.get("prompt", "")
        confirmed = self._auto_confirm
        response = "yes" if confirmed else "no"

        logger.info("[simulated user_io] GET_CONFIRMATION %r -> %s", prompt, response)
        result = ExecutionResult(
            success=True,
            data={"confirmed": confirmed, "response": response, "simulated": True},
        )
        result.extras["user_response_token"] = self._compute_user_response_token(
            prompt=prompt, response=response, timestamp=result.timestamp,
        )
        return result

    async def rollback(self, rollback_id: str) -> ExecutionResult:
        return ExecutionResult(
            success=False, error="User interaction is irreversible",
        )

    @staticmethod
    def _compute_user_response_token(
        prompt: str, response: str, timestamp: str,
    ) -> str:
        """Compute SHA-256 attestation of a user-IO interaction."""
        payload = json.dumps({
            "prompt": prompt,
            "response": response,
            "timestamp": timestamp,
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:12]
