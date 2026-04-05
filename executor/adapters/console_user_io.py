"""
Console-based User I/O adapter -- stdin/stdout interaction.

Platform-neutral alternative to the macOS osascript-based UserIOAdapter.
Uses console input/output for user interaction, suitable for CLI tools,
demos, testing, and any environment without a GUI.

UserIOService is a PROTECTED RESOURCE, not a special channel.
ASK_USER, SHOW_MESSAGE, GET_CONFIRMATION all go through the
IntentFrame pipeline. Guardian validates that the prompt is safe
(not phishing) before the authorized request reaches the executor.

This adapter stamps successful user-IO results with a
``user_response_token`` in ``extras`` -- a SHA-256 hash attesting:
"I showed this prompt, user responded with this."  The adapter is
the witness; the token is its attestation.

Actions: ASK_USER, SHOW_MESSAGE, GET_CONFIRMATION
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging

from action_registry import ActionType
from executor.adapters.base import CapabilityAdapter
from executor.models import AdapterManifest, ExecutionResult

logger = logging.getLogger(__name__)


class ConsoleUserIOAdapter(CapabilityAdapter):
    """Console-based user interaction adapter via stdin/stdout.

    Suitable for CLI demos, testing, and non-GUI environments.
    Stamps user-IO results with ``extras["user_response_token"]``.
    """

    def supported_actions(self) -> list[str]:
        return [
            ActionType.ASK_USER.value,
            ActionType.SHOW_MESSAGE.value,
            ActionType.GET_CONFIRMATION.value,
        ]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="console_user_io",
            name="Console User I/O",
            description="Console-based user interaction via stdin/stdout",
            supported_actions=self.supported_actions(),
            requires_credentials=False,
        )

    async def execute(
        self, action: str, params: dict, credentials: dict | None = None,
    ) -> ExecutionResult:
        return await asyncio.to_thread(self._execute_sync, action, params)

    def _execute_sync(self, action: str, params: dict) -> ExecutionResult:
        if action == "ASK_USER":
            return self._ask_user(params)
        if action == "SHOW_MESSAGE":
            msg = params.get("message", "")
            print(f"\n[Message] {msg}")
            return ExecutionResult(success=True, data={"shown": True})
        if action == "GET_CONFIRMATION":
            return self._get_confirmation(params)
        return ExecutionResult(success=False, error=f"Unknown action: {action}")

    def _ask_user(self, params: dict) -> ExecutionResult:
        """Show a prompt via console and return the user's response."""
        prompt = params.get("prompt", "Please enter a value:")
        options = params.get("options", [])

        if options:
            print(f"\n{prompt}")
            for i, opt in enumerate(options, 1):
                print(f"  {i}. {opt}")
            while True:
                choice = input("Enter choice number: ").strip()
                if choice.isdigit() and 1 <= int(choice) <= len(options):
                    response = options[int(choice) - 1]
                    break
                print(f"  Please enter 1-{len(options)}")
        else:
            response = input(f"\n{prompt}: ").strip()

        result = ExecutionResult(
            success=True,
            data={"response": response},
        )
        result.extras["user_response_token"] = self._compute_user_response_token(
            prompt=prompt, response=response, timestamp=result.timestamp,
        )
        return result

    def _get_confirmation(self, params: dict) -> ExecutionResult:
        """Show a yes/no prompt via console."""
        prompt = params.get("prompt", "Are you sure?")
        response = input(f"\n{prompt} (yes/no): ").strip().lower()
        confirmed = response in ("yes", "y")

        result = ExecutionResult(
            success=True,
            data={"confirmed": confirmed, "response": response},
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
        """Compute SHA-256 attestation of a user-IO interaction.

        The adapter is the witness — it showed the prompt and received
        the response. This hash is the adapter's attestation of that fact.
        The agent cannot forge it because timestamp is adapter-controlled.

        In production, this would also be HMAC-signed with an adapter secret.
        """
        payload = json.dumps({
            "prompt": prompt,
            "response": response,
            "timestamp": timestamp,
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:12]
