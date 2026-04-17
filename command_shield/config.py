"""Operational configuration for command_shield.

ShieldConfig represents command_shield's own analysis bounds — not
user policy.  Caller-supplied overrides narrow (or widen) the envelope
within which the shield performs deep analysis.  Out-of-bound inputs
are reported as signals, never as blocking decisions.  Guardian owns
policy; command_shield owns facts.
"""

from __future__ import annotations

from dataclasses import dataclass


_DEFAULT_LANGUAGES: frozenset[str] = frozenset({"python", "shell"})


@dataclass(frozen=True)
class ShieldConfig:
    """Operational limits and scope for command_shield.

    Attributes:
        max_command_length: Commands longer than this emit a
            COMMAND_TOO_LARGE signal and skip all downstream analysis.
            Oversized input cannot be trusted by any tokenizer and
            wastes every downstream step.
        max_code_length: Code blobs (inline -c payload or
            caller-supplied file_content) larger than this emit a
            CODE_TOO_LARGE signal and skip deterministic + LLM code
            analysis.  Oversized code floods AST + LLM.
        allowed_languages: Languages for which command_shield performs
            deep code analysis (steps 8-11).  Commands in other
            languages receive an OUT_OF_SCOPE signal but still pass
            through capability classification.
        enable_llm_review: When False, the LLM reviewer step is
            unconditionally skipped even in the deep variant.  Caller
            can disable the LLM entirely without changing which entry
            point they call.
    """

    max_command_length: int = 10_000
    max_code_length: int = 50_000
    allowed_languages: frozenset[str] = _DEFAULT_LANGUAGES
    enable_llm_review: bool = True


DEFAULT_CONFIG: ShieldConfig = ShieldConfig()
