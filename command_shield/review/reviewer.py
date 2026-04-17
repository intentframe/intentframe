"""LLM code safety reviewer.

Standalone — no imports from intentframe_components, policy_registry,
or executor.  Uses the OpenAI Agents SDK to assess whether code
content is safe to run.  This is examination, not policy — it reports
findings but does not make allow/block decisions.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from command_shield.review.types import ReviewFinding

logger = logging.getLogger(__name__)

_MODEL = "gpt-5-mini-2025-08-07"
_TIMEOUT_SECONDS = 5

_SYSTEM_INSTRUCTIONS = """\
You are a code safety analyst.  You receive code content and must
assess whether it is safe to run on a user's machine.

Focus on:
  - File-system damage (deleting, overwriting important paths)
  - Credential / secret exfiltration
  - Network exfiltration of local data
  - Privilege escalation
  - Spawning persistent background processes
  - Obfuscated payloads or encoded strings

Do NOT flag normal programming patterns (reading files in across full system,
printing output, doing arithmetic, string manipulation).

Return a JSON object with your findings and a one-sentence summary.
"""


class _ReviewerFinding(BaseModel):
    id: Annotated[str, StringConstraints(max_length=80)]
    severity: Annotated[str, StringConstraints(max_length=10)]
    title: Annotated[str, StringConstraints(max_length=200)]
    detail: Annotated[str, StringConstraints(max_length=500)]
    evidence: Annotated[str, StringConstraints(max_length=200)]


class _ReviewerOutput(BaseModel):
    findings: list[_ReviewerFinding] = Field(default_factory=list, max_length=10)
    summary: Annotated[str, StringConstraints(max_length=400)] = ""


async def review_code(
    code: str,
    *,
    language: str | None = None,
    command_context: str | None = None,
) -> tuple[tuple[ReviewFinding, ...], str, bool]:
    """Run LLM code safety review.

    Returns (findings, summary, reviewer_ran).
    On any error or timeout, returns empty findings with reviewer_ran=False.
    """
    try:
        from agents import Agent, ModelSettings, Runner
    except ImportError:
        logger.debug("agents SDK not available — skipping LLM review")
        return (), "", False

    agent = Agent(
        name="code-safety-reviewer",
        instructions=_SYSTEM_INSTRUCTIONS,
        model=_MODEL,
        model_settings=ModelSettings(temperature=0.0),
        output_type=_ReviewerOutput,
    )

    prompt_parts = []
    if language:
        prompt_parts.append(f"Language: {language}")
    if command_context:
        prompt_parts.append(f"Command: {command_context}")
    prompt_parts.append(f"Code:\n```\n{code}\n```")
    prompt = "\n".join(prompt_parts)

    try:
        result = await asyncio.wait_for(
            Runner.run(agent, prompt),
            timeout=_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("LLM reviewer timed out after %ds", _TIMEOUT_SECONDS)
        return (), "", False
    except Exception:
        logger.warning("LLM reviewer failed", exc_info=True)
        return (), "", False

    output: _ReviewerOutput = result.final_output

    findings = tuple(
        ReviewFinding(
            source="reviewer",
            finding_id=f.id,
            severity=f.severity,
            title=f.title,
            detail=f.detail,
            evidence=f.evidence,
            confidence=0.75,
        )
        for f in output.findings
    )

    return findings, output.summary, True
