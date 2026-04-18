"""
Runtime integration test for the email intent flow.

This script fetches a real email from the local EDI database, builds a
Jarvis-style REPLY_EMAIL payload, then runs it through the real
IntentFrameRuntime.process_intent() pipeline with mocked Analysis
Engine, Guardian, and Executor components.

It logs the IntentFrame at each stage, including what the final executor
would translate into adapter params.

Run:
    python -m intentframe_server.test_email_intent_flow

Requirements:
    - EDI daemon must have synced at least once (emails.db populated)
    - No running supervisor/jarvis/executor needed
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import patch

from intentframe_core.enums import Decision, Reversibility, RiskLevel
from intentframe_core.types import (
    AnalysisReport,
    ExecutionResult,
    IntentFrame,
    UserContext,
    ValidationResult,
)
from policy_registry.models import ActionPermission


def _dump(label: str, obj: Any) -> None:
    """Pretty-print a stage snapshot."""
    border = "=" * 78
    print(f"\n{border}")
    print(label)
    print(border)
    if isinstance(obj, (dict, list, tuple, str, int, float, bool)) or obj is None:
        print(json.dumps(obj, indent=4, default=str))
    else:
        print(json.dumps(obj.model_dump(mode="json"), indent=4, default=str))


class LoggingAnalysisEngine:
    """Test double that logs the enriched intent Analysis Engine sees."""

    async def analyze(
        self,
        intent: IntentFrame,
        *,
        safe_actions: set[str],
        terminal_command_signals: tuple = (),
        **kwargs: Any,
    ) -> AnalysisReport:
        _dump("STAGE 4: Analysis Engine received intent", intent)
        _dump(
            "STAGE 4B: Analysis Engine inputs",
            {
                "safe_actions": sorted(safe_actions),
                "terminal_command_signals": list(terminal_command_signals),
                "command_intel": kwargs.get("command_intel"),
            },
        )
        return AnalysisReport(
            stated_intent="reply to the selected email",
            risk_factors={"overall": RiskLevel.LOW},
            reversibility=Reversibility.FULLY_REVERSIBLE,
            confidence=1.0,
            recommendation="allow",
        )


class LoggingGuardian:
    """Test double that logs the intent and allows it unchanged."""

    async def validate(
        self,
        intent: IntentFrame,
        analysis: AnalysisReport,
        user_context: UserContext,
        **kwargs: Any,
    ) -> ValidationResult:
        _dump("STAGE 5: Guardian received intent", intent)
        _dump(
            "STAGE 5B: Guardian analysis summary",
            {
                "decision_input_confidence": analysis.confidence,
                "risk_factors": analysis.risk_factors,
                "reversibility": analysis.reversibility,
                "allowed_actions": sorted(user_context.allowed_actions.keys()),
            },
        )
        return ValidationResult(
            decision=Decision.ALLOW,
            intent=intent,
            analysis=analysis,
            message="Allowed by integration test guardian",
        )


class CaptureExecutor:
    """Executor double that logs the validated intent and adapter params."""

    def __init__(self) -> None:
        self.received_intent: IntentFrame | None = None
        self.adapter_params: dict[str, Any] | None = None

    def execute(self, validated_intent: IntentFrame) -> ExecutionResult:
        from executor_client.http_client import ExecutorHTTPClient

        self.received_intent = validated_intent
        _dump("STAGE 6: Executor received validated intent", validated_intent)

        self.adapter_params = ExecutorHTTPClient._translate_params(
            validated_intent.action.value,
            validated_intent,
        )
        _dump(
            "STAGE 7: Adapter params derived from executor intent",
            self.adapter_params,
        )

        return ExecutionResult(
            success=True,
            data={
                "captured_action": validated_intent.action.value,
                "captured_target": validated_intent.target,
                "captured_params": self.adapter_params,
            },
        )


def _build_user_context() -> UserContext:
    return UserContext(
        user_id="demo-user",
        allowed_actions={
            "REPLY_EMAIL": ActionPermission(safe=False),
        },
    )


async def main() -> None:
    close_enricher = None
    # Step 0: Fetch a real email from local DB.
    from external_data_ingestion.email.client import EmailClient

    client = await EmailClient.create()
    accounts = await client.get_active_accounts()
    if not accounts:
        all_accounts = await client.list_accounts()
        if all_accounts:
            accounts = all_accounts
        else:
            print("No email accounts found in local DB. Run the EDI daemon at least once.")
            await client.close()
            return

    account = accounts[0]
    print(f"Using account: {account.email}")

    emails = await client.get_recent(account.email, mailbox="INBOX", limit=1)
    if not emails:
        print(f"No emails in INBOX for {account.email}")
        await client.close()
        return

    email = emails[0]
    print(f"Latest email: [{email.subject}] from {email.sender_email}")
    print(f"Message-ID:   {email.message_id}")
    await client.close()

    # Step 1: Build the Jarvis tool payload.
    # This is what _EmailReplyAction.model_dump() produces
    jarvis_payload = {
        "action": "REPLY_EMAIL",
        "rfc_message_id": email.message_id,
        "body": "Thanks, got it!",
        "reply_all": False,
        "reason": "user asked me to acknowledge this email",
    }
    _dump("STAGE 1: Jarvis tool payload (what actor.submit receives)", jarvis_payload)

    # Step 2: Actor builds the pre-runtime IntentFrame.
    from intentframe_actor.actor import Actor

    actor = Actor(agent_id="jarvis", user_id="demo-user", socket_path="")
    actor._sequence_id = 1
    intent_from_actor = actor._build_intent(jarvis_payload)
    _dump("STAGE 2: IntentFrame from Actor (pre-enrichment)", intent_from_actor)

    # Step 3: Run the real runtime pipeline with stage logging.
    from intentframe_components.prompt import format_intent_data
    from intentframe_server.enrichers.email import (
        close as close_enricher,
        enrich_intent as real_enrich_intent,
    )
    from intentframe_server.pipeline import IntentFrameRuntime

    async def logged_enrich_intent(intent: IntentFrame) -> IntentFrame:
        _dump("STAGE 3: Runtime enrichment input", intent)
        enriched = await real_enrich_intent(intent)
        _dump("STAGE 3B: Runtime enrichment output", enriched)

        old_data = intent.data or {}
        new_data = enriched.data or {}
        added_keys = sorted(set(new_data) - set(old_data))
        diff = {
            "target_before": intent.target,
            "target_after": enriched.target,
            "added_data_keys": added_keys,
            "added_data": {key: new_data[key] for key in added_keys},
        }
        _dump("STAGE 3C: Enrichment diff", diff)

        untrusted_for_ae = {
            "Target": enriched.target,
            "Reason": enriched.reason,
        }
        data_section = format_intent_data(enriched.data)
        if data_section:
            untrusted_for_ae["Data"] = data_section
        _dump("STAGE 3D: AE/Guardian untrusted prompt section", untrusted_for_ae)
        return enriched

    analysis_engine = LoggingAnalysisEngine()
    guardian = LoggingGuardian()
    executor = CaptureExecutor()
    runtime = IntentFrameRuntime(
        analysis_engine=analysis_engine,
        guardian=guardian,
        executor=executor,
        verbose=False,
    )
    runtime._resolve_user_context = lambda user_context: user_context

    try:
        with patch(
            "intentframe_server.pipeline.enrich_email_intent",
            side_effect=logged_enrich_intent,
        ):
            result = await runtime.process_intent(intent_from_actor, _build_user_context())

        _dump("STAGE 8: Final ExecutionResult returned by runtime", result)
        _dump("STAGE 9: Runtime audit log entry", runtime.get_audit_log())

        # Step 4: Verify mail adapter dispatch prerequisites.
        print("\n--- Mail adapter dispatch check ---")
        from executor.platforms.macos.adapters.mail import (
            _ACCOUNT_ACTIONS,
            _MESSAGE_ACTIONS,
        )
        if executor.received_intent is None or executor.adapter_params is None:
            raise RuntimeError("Executor did not capture the final validated intent")

        action_value = executor.received_intent.action.value
        executor_params = executor.adapter_params
        if action_value in _MESSAGE_ACTIONS:
            mid = executor_params.get("rfc_message_id") or executor_params.get("message_id")
            print(f"  OK {action_value} is a message action")
            print(f"  OK rfc_message_id present: {bool(mid)} ({mid!r})")
        elif action_value in _ACCOUNT_ACTIONS:
            acct = executor_params.get("account_email")
            print(f"  OK {action_value} is an account action")
            print(f"  OK account_email present: {bool(acct)} ({acct!r})")
        else:
            print(f"  ERROR {action_value} not recognized by MailAdapter")

        reply_body = executor_params.get("body")
        print(f"  OK body present: {bool(reply_body)} ({reply_body!r})")

        to = executor_params.get("to")
        print(f"  OK to (enriched reply recipient): {to!r}")

        print("\nDone. Full runtime integration flow logged above.")
    finally:
        if close_enricher is not None:
            await close_enricher()


if __name__ == "__main__":
    asyncio.run(main())
