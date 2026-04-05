"""
Prompt hardening orchestrator.

Composes all hardening techniques into a single entry point that the
Analysis Engine and Guardian consume.  Each technique lives in its own
module; this class wires them together so callers don't need to know
the details.

Techniques applied:
    1. Encoding normalization  (normalization.py)
    2. Random boundary tokens  (boundaries.py)
    3. Trusted/untrusted framing  (boundaries.py)
    4. Immutable role anchoring  (roles.py)
    5. Sandwich pattern — closing reinforcement  (roles.py)

Usage::

    from intentframe_components.prompt.hardening import PromptHardening

    hardener = PromptHardening()

    # At Agent init — harden the system prompt once
    system_prompt = hardener.harden_system_prompt(
        base_instructions="You analyze intents...",
        role_preamble=ANALYSIS_ENGINE_ROLE,
    )

    # Per request — build a hardened user prompt
    user_prompt = hardener.build_hardened_prompt(
        trusted_sections={"Context": "Action: SEND_EMAIL\\nAgent: jarvis"},
        untrusted_fields={"Target": target, "Reason": reason, "Data": data_str},
        closing_instruction="Analyze what this action will REALLY do.",
    )
"""

from __future__ import annotations

from intentframe_components.prompt.normalization import normalize_text
from intentframe_components.prompt.boundaries import (
    generate_boundary,
    frame_trusted,
    frame_untrusted,
)
from intentframe_components.prompt.roles import closing_reinforcement


class PromptHardening:
    """Orchestrates all prompt hardening techniques.

    Stateless — safe to instantiate once and reuse across requests.
    Each call to ``build_hardened_prompt`` generates a fresh boundary
    token, so concurrent requests get independent tokens.
    """

    # ── System prompt (once at Agent init) ────────────────────────

    @staticmethod
    def harden_system_prompt(
        base_instructions: str,
        role_preamble: str,
    ) -> str:
        """Prepend immutable role anchoring to existing instructions.

        The role preamble declares the role immutable and explains the
        boundary protocol.  The base instructions (semantic domains,
        hidden behaviors, decision rules, etc.) follow unchanged.
        """
        return f"{role_preamble}\n\n{base_instructions}"

    # ── Per-request prompt ────────────────────────────────────────

    @staticmethod
    def build_hardened_prompt(
        *,
        trusted_sections: dict[str, str],
        untrusted_fields: dict[str, str],
        closing_instruction: str,
    ) -> str:
        """Build a hardened per-request prompt.

        Steps:
            1. Generate a per-request random boundary token.
            2. Normalize all untrusted field values (encoding tricks).
            3. Frame trusted sections in ``<trusted_context>`` XML tags.
            4. Frame untrusted fields inside boundary markers.
            5. Append the closing instruction.
            6. Append sandwich-pattern reinforcement referencing the
               boundary token.

        Args:
            trusted_sections: ``{label: content}`` pairs of pipeline-
                controlled data.  Each pair becomes a separate
                ``<trusted_context>`` block.
            untrusted_fields: ``{name: value}`` pairs of agent-controlled
                data.  Values are normalized, then wrapped inside
                boundary markers.
            closing_instruction: The task instruction appended after
                all sections (e.g. "Analyze what this action will
                REALLY do.").
        """
        boundary = generate_boundary()
        parts: list[str] = []

        for label, content in trusted_sections.items():
            parts.append(frame_trusted(content, label=label))

        normalized_lines: list[str] = []
        for name, value in untrusted_fields.items():
            normalized_lines.append(f"{name}: {normalize_text(value)}")
        untrusted_block = "\n".join(normalized_lines)
        parts.append(frame_untrusted(untrusted_block, boundary))

        parts.append(closing_instruction)

        parts.append(closing_reinforcement(boundary))

        return "\n\n".join(parts)
