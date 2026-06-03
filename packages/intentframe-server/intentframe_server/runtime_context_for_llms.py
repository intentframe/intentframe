"""Render server-owned substrate facts into runtime LLM context sections."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from intentframe_core.types import ExecutionContext, LLMContextSection, RuntimeContextForLLM


class SubstrateContext(BaseModel):
    """Server-owned infrastructure facts probed or configured at startup."""

    model_config = ConfigDict(frozen=True)

    execution: ExecutionContext = Field(default_factory=ExecutionContext)


def _any_executor_running_as_root(contexts: tuple[SubstrateContext, ...]) -> bool:
    return any(ctx.execution.executor_running_as_root for ctx in contexts)


def _analysis_execution_section() -> LLMContextSection:
    return LLMContextSection(
        label="Execution Privilege",
        content=(
            "The executor is running as root (uid=0). All commands execute "
            "with full root privileges. Assess blast radius accordingly — "
            "even benign-looking commands can cause system-wide damage when "
            "run as root. The agent should never use sudo; if sudo appears "
            "in the command, flag it as a hidden behavior."
        ),
    )


def _guardian_execution_section() -> LLMContextSection:
    return LLMContextSection(
        label="Execution Privilege",
        content=(
            "The executor is running as root (uid=0). All commands execute "
            "with full root privileges. Apply heightened scrutiny — filesystem "
            "modifications affect the entire system, not just the user's home "
            "directory. The agent should never need sudo; its presence in a "
            "command is itself a red flag."
        ),
    )


def _onboarding_execution_section() -> LLMContextSection:
    return LLMContextSection(
        label="EXECUTION ENVIRONMENT",
        content=(
            f"The executor is running as root (uid=0).\n"
            f"All commands this agent issues, will execute with full root privileges in the terminal.\n"
            "The agent must NOT use sudo — commands already run as root.\n"
            "Generate guardrails that reflect this elevated privilege level:\n"
            "- Explicitly tell the agent its commands run with root privileges.\n"
            "- Explicitly tell the agent to never use sudo.\n"
            "- Warn that filesystem operations affect the entire system."
        ),
    )


def analysis_runtime_context_for_llm(
    contexts: tuple[SubstrateContext, ...],
) -> RuntimeContextForLLM:
    if not _any_executor_running_as_root(contexts):
        return ()
    return (_analysis_execution_section(),)


def guardian_runtime_context_for_llm(
    contexts: tuple[SubstrateContext, ...],
) -> RuntimeContextForLLM:
    if not _any_executor_running_as_root(contexts):
        return ()
    return (_guardian_execution_section(),)


def onboarding_runtime_context_for_llm(
    contexts: tuple[SubstrateContext, ...],
) -> RuntimeContextForLLM:
    if not _any_executor_running_as_root(contexts):
        return ()
    return (_onboarding_execution_section(),)
