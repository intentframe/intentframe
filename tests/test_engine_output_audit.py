"""Output forensic audit: raw LLM output + converted pipeline artifacts."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from action_registry.types import ActionType
from intentframe_core.enums import Decision, Reversibility, RiskLevel
from intentframe_core.types import (
    AnalysisReport,
    IntentFrame,
    PromptEvidence,
    UserContext,
)
from intentframe_components.analysis.engine import AIAnalysisEngine, AIAnalysisOutput
from intentframe_components.guardian.engine import AIGuardian, AIGuardianOutput
from intentframe_components.prompt.logging import log_output_dump
from intentframe_server.pipeline import IntentFrameRuntime
from policy_registry.models import ActionPermission


def _intent() -> IntentFrame:
    return IntentFrame(
        action=ActionType.RUN_COMMAND,
        target="echo hi",
        reason="test",
        agent_id="tester",
    )


class TestLogOutputDump:
    def test_writes_analysis_output_log(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INTENTFRAME_LOG_DIR", str(tmp_path))
        log_output_dump(
            "analysis",
            llm_output={"stated_intent": "x"},
            converted_output={"confidence": 0.9},
            prompt_source="bundle",
            prompt_label="critical_run_command",
        )
        log_file = tmp_path / "analysis_outputs.log"
        assert log_file.exists()
        entry = json.loads(log_file.read_text().strip())
        assert entry["component"] == "analysis"
        assert entry["llm_output"]["stated_intent"] == "x"
        assert entry["converted_output"]["confidence"] == 0.9


class TestAnalysisEngineOutputAudit:
    @pytest.mark.asyncio
    async def test_returns_output_evidence_after_llm(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INTENTFRAME_LOG_DIR", str(tmp_path))
        engine = AIAnalysisEngine(verbose=False)
        llm_out = AIAnalysisOutput(
            stated_intent="List files",
            actual_behavior="Lists directory contents",
            risk_level="LOW",
            risk_reason="Read-only",
            reversibility="FULLY_REVERSIBLE",
            scope_analysis="current directory",
            confidence=0.95,
            recommendation="Benign read",
        )
        mock_result = MagicMock()
        mock_result.final_output = llm_out

        with patch(
            "intentframe_components.analysis.engine.Runner.run",
            new=AsyncMock(return_value=mock_result),
        ):
            report = await engine.analyze(_intent())

        assert report.prompt_evidence is not None
        assert report.prompt_evidence.llm_output is not None
        assert report.prompt_evidence.llm_output["stated_intent"] == "List files"
        assert report.prompt_evidence.converted_output is not None
        assert report.prompt_evidence.converted_output["confidence"] == report.confidence
        assert report.prompt_evidence.converted_output["ae_output_anomaly"] is False


class TestGuardianOutputAudit:
    @pytest.mark.asyncio
    async def test_fast_path_returns_converted_output_only(self):
        guardian = AIGuardian(verbose=False)
        analysis = AnalysisReport(
            stated_intent="ok",
            risk_factors={"overall": RiskLevel.LOW},
            reversibility=Reversibility.FULLY_REVERSIBLE,
            confidence=1.0,
            recommendation="ok",
        )
        user_context = UserContext(
            user_id="u",
            allowed_actions={"RUN_COMMAND": ActionPermission(safe=True)},
        )
        result = await guardian.validate(_intent(), analysis, user_context)
        assert result.decision_path == "fast_path"
        assert result.prompt_evidence is not None
        assert result.prompt_evidence.llm_output is None
        assert result.prompt_evidence.converted_output is not None
        assert result.prompt_evidence.converted_output["decision"] == Decision.ALLOW.value

    @pytest.mark.asyncio
    async def test_ai_path_sets_both_output_fields(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INTENTFRAME_LOG_DIR", str(tmp_path))
        guardian = AIGuardian(verbose=False)
        analysis = AnalysisReport(
            stated_intent="risky",
            risk_factors={"overall": RiskLevel.HIGH},
            reversibility=Reversibility.IRREVERSIBLE,
            confidence=0.8,
            recommendation="review",
            hidden_behaviors=["unexpected network call"],
        )
        user_context = UserContext(
            user_id="u",
            allowed_actions={"RUN_COMMAND": ActionPermission(safe=False)},
        )
        llm_out = AIGuardianOutput(
            decision="BLOCK",
            reason="Hidden network behavior",
            confidence=0.9,
        )
        mock_result = MagicMock()
        mock_result.final_output = llm_out

        with patch(
            "intentframe_components.guardian.engine.Runner.run",
            new=AsyncMock(return_value=mock_result),
        ):
            result = await guardian.validate(_intent(), analysis, user_context)

        assert result.decision == Decision.BLOCK
        assert result.prompt_evidence is not None
        assert result.prompt_evidence.llm_output is not None
        assert result.prompt_evidence.llm_output["decision"] == "BLOCK"
        assert result.prompt_evidence.converted_output is not None
        assert result.prompt_evidence.converted_output["decision"] == Decision.BLOCK.value


class TestPipelineOutputAuditFields:
    def test_add_output_audit_fields(self):
        artifact = MagicMock()
        artifact.prompt_evidence = PromptEvidence(
            llm_output={"decision": "ALLOW"},
            converted_output={"decision": "ALLOW", "decision_path": "ai_path"},
        )
        entry: dict = {}
        IntentFrameRuntime._add_output_audit_fields(entry, "guardian", artifact)
        assert entry["guardian_llm_output"]["decision"] == "ALLOW"
        assert entry["guardian_converted_output"]["decision_path"] == "ai_path"
