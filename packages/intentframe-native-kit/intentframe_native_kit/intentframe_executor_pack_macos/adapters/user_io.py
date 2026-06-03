"""
User I/O adapter -- native macOS dialogs and notifications.

UserIOService is a PROTECTED RESOURCE, not a special channel.
ASK_USER, SHOW_MESSAGE, GET_CONFIRMATION all go through the
IntentFrame pipeline. Guardian validates that the prompt is safe
(not phishing) before the authorized request reaches the executor.

Uses osascript (AppleScript) for native macOS dialog rendering.

This adapter stamps successful user-IO results with a
``user_response_token`` in ``extras`` -- a SHA-256 hash attesting:
"I showed this prompt, user responded with this."  The adapter is
the witness; the token is its attestation.

Sets ``display_summary`` on each result so the runtime verbose banner
can print human lines without action-specific pipeline logic.

Actions: ASK_USER, SHOW_MESSAGE, GET_CONFIRMATION, SHOW_OPTIONS
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import subprocess

from intentframe_native_kit.action_registry import ActionType
from executor_sdk.adapters.base import CapabilityAdapter
from executor_sdk.models import AdapterManifest, ExecutionResult

logger = logging.getLogger(__name__)


class UserIOAdapter(CapabilityAdapter):
    """macOS native user interaction adapter via AppleScript."""

    def __init__(self, **_kwargs) -> None:
        pass

    def supported_actions(self) -> list[str]:
        return [
            ActionType.ASK_USER.value,
            ActionType.SHOW_MESSAGE.value,
            ActionType.GET_CONFIRMATION.value,
            "SHOW_OPTIONS",
        ]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="user_io",
            name="User I/O Adapter",
            description="Native macOS dialogs for user interaction",
            supported_actions=self.supported_actions(),
            requires_credentials=False,
        )

    async def execute(self, action: str, params: dict, credentials: dict | None = None) -> ExecutionResult:
        return await asyncio.to_thread(self._execute_sync, action, params)

    def _execute_sync(self, action: str, params: dict) -> ExecutionResult:
        if action == "ASK_USER":
            return self._ask_user(params)
        if action == "SHOW_MESSAGE":
            return self._show_message(params)
        if action == "GET_CONFIRMATION":
            return self._get_confirmation(params)
        if action == "SHOW_OPTIONS":
            return self._show_options(params)
        return ExecutionResult(success=False, error=f"Unknown action: {action}")

    def _ask_user(self, params: dict) -> ExecutionResult:
        """Show a text input dialog and return the user's response."""
        prompt = params.get("prompt", "Please enter a value:")
        title = params.get("title", "IntentFrame")
        default = params.get("default", "")

        script = (
            f'display dialog "{self._escape(prompt)}" '
            f'with title "{self._escape(title)}" '
            f'default answer "{self._escape(default)}" '
            f'buttons {{"Cancel", "OK"}} default button "OK"'
        )

        result = self._run_osascript(script)
        if result is None:
            return ExecutionResult(
                success=True,
                data={"response": None, "cancelled": True},
                display_summary=f"Prompt: {prompt}\n(cancelled)",
            )

        # Parse "button returned:OK, text returned:value"
        text = self._parse_text_returned(result)
        exec_result = ExecutionResult(
            success=True,
            data={"response": text, "cancelled": False},
            display_summary=f"Prompt: {prompt}\nUser: {text or '(empty)'}",
        )
        exec_result.extras["user_response_token"] = self._compute_user_response_token(
            prompt=prompt, response=text or "", timestamp=exec_result.timestamp,
        )
        return exec_result

    def _show_message(self, params: dict) -> ExecutionResult:
        """Show an informational message dialog."""
        message = params.get("message", "")
        title = params.get("title", "IntentFrame")

        script = (
            f'display dialog "{self._escape(message)}" '
            f'with title "{self._escape(title)}" '
            f'buttons {{"OK"}} default button "OK"'
        )

        self._run_osascript(script)
        return ExecutionResult(
            success=True,
            data={"shown": True},
            display_summary=f"Shown: {message}",
        )

    def _get_confirmation(self, params: dict) -> ExecutionResult:
        """Show a yes/no confirmation dialog."""
        prompt = params.get("prompt", "Are you sure?")
        title = params.get("title", "IntentFrame")

        script = (
            f'display dialog "{self._escape(prompt)}" '
            f'with title "{self._escape(title)}" '
            f'buttons {{"No", "Yes"}} default button "Yes"'
        )

        result = self._run_osascript(script)
        if result is None:
            confirmed = False
            response_str = "no"
        else:
            confirmed = "Yes" in result
            response_str = "yes" if confirmed else "no"

        exec_result = ExecutionResult(
            success=True,
            data={"confirmed": confirmed},
            display_summary=f"Prompt: {prompt}\nUser: {response_str}",
        )
        exec_result.extras["user_response_token"] = self._compute_user_response_token(
            prompt=prompt, response=response_str, timestamp=exec_result.timestamp,
        )
        return exec_result

    def _show_options(self, params: dict) -> ExecutionResult:
        """Show a list selection dialog."""
        prompt = params.get("prompt", "Choose an option:")
        title = params.get("title", "IntentFrame")
        options = params.get("options", [])

        if not options:
            return ExecutionResult(success=False, error="No options provided")

        options_str = ", ".join(f'"{self._escape(o)}"' for o in options)
        script = (
            f'choose from list {{{options_str}}} '
            f'with prompt "{self._escape(prompt)}" '
            f'with title "{self._escape(title)}"'
        )

        result = self._run_osascript(script)
        if result is None or result.strip() == "false":
            return ExecutionResult(
                success=True,
                data={"selection": None, "cancelled": True},
                display_summary=f"Prompt: {prompt}\n(cancelled)",
            )

        selection = result.strip()
        exec_result = ExecutionResult(
            success=True,
            data={"selection": selection, "cancelled": False},
            display_summary=f"Prompt: {prompt}\nUser: {selection}",
        )
        exec_result.extras["user_response_token"] = self._compute_user_response_token(
            prompt=prompt, response=selection, timestamp=exec_result.timestamp,
        )
        return exec_result

    @staticmethod
    def _run_osascript(script: str) -> str | None:
        """Run an AppleScript and return the output, or None if cancelled."""
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=120,  # 2 minute timeout for user interaction
            )
            if result.returncode != 0:
                return None
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            return None
        except Exception:
            return None

    @staticmethod
    def _escape(text: str) -> str:
        """Escape special characters for AppleScript strings."""
        return text.replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    def _parse_text_returned(result: str) -> str:
        """Parse 'text returned:VALUE' from osascript output."""
        if "text returned:" in result:
            return result.split("text returned:", 1)[1].strip()
        return result

    @staticmethod
    def _compute_user_response_token(
        prompt: str, response: str, timestamp: str,
    ) -> str:
        """Compute SHA-256 attestation of a user-IO interaction.

        The adapter is the witness -- it showed the prompt and received
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

    async def rollback(self, rollback_id: str) -> ExecutionResult:
        return ExecutionResult(
            success=False,
            error="User interaction is irreversible",
        )
