"""Apply pipeline-rendered runtime context sections to engine prompts."""

from __future__ import annotations

from intentframe_core.types import LLMContextSection, RuntimeContextForLLM


def merge_runtime_context_sections(
    trusted_sections: dict[str, str],
    runtime_context_for_llm: RuntimeContextForLLM,
) -> None:
    for section in runtime_context_for_llm:
        trusted_sections[section.label] = section.content


def append_runtime_context_sections(
    prompt: str,
    runtime_context_for_llm: RuntimeContextForLLM,
) -> str:
    for section in runtime_context_for_llm:
        prompt += f"\n## {section.label}\n\n{section.content}\n"
    return prompt
