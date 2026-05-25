"""Tests for runtime context prompt helpers."""

from intentframe_components.prompt.runtime_context import (
    append_runtime_context_sections,
    merge_runtime_context_sections,
)
from intentframe_core.types import LLMContextSection


def test_merge_runtime_context_sections():
    trusted_sections = {"Context": "Action: READ_FILE"}
    merge_runtime_context_sections(
        trusted_sections,
        (
            LLMContextSection(
                label="Execution Privilege",
                content="The executor is running as root (uid=0).",
            ),
        ),
    )
    assert trusted_sections["Execution Privilege"] == "The executor is running as root (uid=0)."


def test_append_runtime_context_sections():
    prompt = "Generate guardrails."
    result = append_runtime_context_sections(
        prompt,
        (
            LLMContextSection(
                label="EXECUTION ENVIRONMENT",
                content="The executor is running as root (uid=0).",
            ),
        ),
    )
    assert "## EXECUTION ENVIRONMENT" in result
    assert "running as root" in result
