"""Tests for runtime context rendering for LLM prompts."""

from intentframe_core.types import ExecutionContext, LLMContextSection
from intentframe_server.runtime_context_for_llms import (
    SubstrateContext,
    analysis_runtime_context_for_llm,
    guardian_runtime_context_for_llm,
    onboarding_runtime_context_for_llm,
)


def _root_contexts() -> tuple[SubstrateContext, ...]:
    return (
        SubstrateContext(
            execution=ExecutionContext(
                executor_running_as_root=True,
                executor_uid=0,
                executor_euid=0,
            )
        ),
    )


def _non_root_contexts() -> tuple[SubstrateContext, ...]:
    return (SubstrateContext(),)


def test_analysis_runtime_context_only_when_root():
    sections = analysis_runtime_context_for_llm(_root_contexts())
    assert sections == (
        LLMContextSection(
            label="Execution Privilege",
            content=sections[0].content,
        ),
    )
    assert "running as root" in sections[0].content
    assert analysis_runtime_context_for_llm(_non_root_contexts()) == ()


def test_guardian_runtime_context_only_when_root():
    sections = guardian_runtime_context_for_llm(_root_contexts())
    assert sections[0].label == "Execution Privilege"
    assert "running as root" in sections[0].content
    assert guardian_runtime_context_for_llm(_non_root_contexts()) == ()


def test_onboarding_runtime_context_only_when_root():
    sections = onboarding_runtime_context_for_llm(_root_contexts())
    assert sections[0].label == "EXECUTION ENVIRONMENT"
    assert "running as root" in sections[0].content
    assert onboarding_runtime_context_for_llm(_non_root_contexts()) == ()


def test_any_root_context_in_tuple_triggers_render():
    contexts = (
        SubstrateContext(),
        SubstrateContext(
            execution=ExecutionContext(executor_running_as_root=True),
        ),
    )
    assert analysis_runtime_context_for_llm(contexts)
