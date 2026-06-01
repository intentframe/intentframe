"""Unit tests for shared default prompt bodies and bundle specialisations."""

from __future__ import annotations

from intentframe_native_kit.intentframe_native_bundles.shared.files.prompts_ae import _CRITICAL_WRITE_FILE
from intentframe_native_kit.intentframe_native_bundles.actions.terminal.prompts_ae import _CRITICAL_RUN_COMMAND
from intentframe_components.analysis.engine import AIAnalysisEngine
from intentframe_components.guardian.engine import AIGuardian
from intentframe_prompt_library.library import (
    DEFAULT_AE_SYSTEM_INSTRUCTIONS,
    DEFAULT_GUARDIAN_SYSTEM_INSTRUCTIONS,
)


class TestLibraryShape:
    def test_default_ae_body_is_nonempty(self):
        assert isinstance(DEFAULT_AE_SYSTEM_INSTRUCTIONS, str)
        assert DEFAULT_AE_SYSTEM_INSTRUCTIONS.strip()

    def test_default_guardian_body_is_nonempty(self):
        assert isinstance(DEFAULT_GUARDIAN_SYSTEM_INSTRUCTIONS, str)
        assert DEFAULT_GUARDIAN_SYSTEM_INSTRUCTIONS.strip()


class TestAEStandardBody:
    def test_contains_semantic_domains_section(self):
        assert "Semantic domains" in DEFAULT_AE_SYSTEM_INSTRUCTIONS

    def test_contains_hidden_behaviors_section(self):
        assert "Hidden behaviors" in DEFAULT_AE_SYSTEM_INSTRUCTIONS

    def test_contains_data_integrity_section(self):
        assert "Data integrity" in DEFAULT_AE_SYSTEM_INSTRUCTIONS

    def test_contains_factual_analysis_phrase(self):
        assert "factual analysis" in DEFAULT_AE_SYSTEM_INSTRUCTIONS

    def test_base_instructions_facade_returns_standard(self):
        assert AIAnalysisEngine._base_instructions() == DEFAULT_AE_SYSTEM_INSTRUCTIONS


class TestGuardianStandardBody:
    def test_contains_allow_block_decisions_phrase(self):
        assert "ALLOW/BLOCK" in DEFAULT_GUARDIAN_SYSTEM_INSTRUCTIONS

    def test_contains_intent_limits_section(self):
        assert "Intent Limits" in DEFAULT_GUARDIAN_SYSTEM_INSTRUCTIONS

    def test_contains_ask_user_carve_out(self):
        assert "ASK_USER" in DEFAULT_GUARDIAN_SYSTEM_INSTRUCTIONS

    def test_base_instructions_facade_returns_standard(self):
        assert AIGuardian._base_instructions() == DEFAULT_GUARDIAN_SYSTEM_INSTRUCTIONS


class TestBundleCriticalWriteFileBody:
    def test_body_contains_write_framing(self):
        markers = ("WRITE_FILE", "file-write", "destination", "payload")
        assert any(m in _CRITICAL_WRITE_FILE for m in markers)

    def test_body_is_factual_analysis(self):
        assert "factual analysis" in _CRITICAL_WRITE_FILE

    def test_body_does_not_instruct_ae_to_allow_or_block(self):
        forbidden = [
            "you must ALLOW",
            "you must BLOCK",
            "you allow",
            "you block",
            "You ALLOW",
            "You BLOCK",
        ]
        for phrase in forbidden:
            assert phrase not in _CRITICAL_WRITE_FILE


class TestBundleCriticalRunCommandBody:
    def test_body_contains_command_framing(self):
        markers = ("TERMINAL COMMAND", "shell command", "decompose", "compound")
        assert any(m in _CRITICAL_RUN_COMMAND for m in markers)

    def test_body_is_factual_analysis(self):
        assert "factual analysis" in _CRITICAL_RUN_COMMAND

    def test_body_does_not_instruct_ae_to_allow_or_block(self):
        forbidden = [
            "you must ALLOW",
            "you must BLOCK",
            "you allow",
            "you block",
            "You ALLOW",
            "You BLOCK",
        ]
        for phrase in forbidden:
            assert phrase not in _CRITICAL_RUN_COMMAND

