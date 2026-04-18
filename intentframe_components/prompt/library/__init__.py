"""
Prompt library — versioned bodies of the AE and Guardian system prompts.

Bundle C (C1) establishes the library with two prompt ids per component
and three lane aliases on the AE side:

Analysis Engine
    ``standard``                    — byte-identical to the pre-Bundle-C body
    ``critical_generic``            — standard body + a focused critical
                                      overlay (stricter scrutiny)
    ``critical_network_probe``      — aliased to ``critical_generic`` in C1
    ``critical_network_mutation``   — aliased to ``critical_generic`` in C1

Guardian
    ``standard``                    — byte-identical to the pre-Bundle-C body
    ``critical``                    — standard body + a focused critical
                                      overlay (stricter scrutiny)

The per-lane specialisation for network_probe vs network_mutation is
deferred to C2/C3 so Bundle C's AI-behaviour change is confined to a
single, additive overlay that moves judgement in the safer direction
only (harder to ALLOW; never harder to BLOCK).

Contract
--------
Every prompt id must produce output that conforms to the same pydantic
output schema — :class:`AIAnalysisOutput` for AE,
:class:`AIGuardianOutput` for Guardian.  Changing the schema is not
part of a prompt-library change; it is a cross-cutting concern.

Looking up an unknown id falls through to ``standard`` with a warning
log — fail-closed on ambiguity, never a hard crash on a typo in a
third-party strategy.
"""

from intentframe_components.prompt.library.analysis import (
    ANALYSIS_PROMPTS,
    ANALYSIS_PROMPT_IDS,
)
from intentframe_components.prompt.library.guardian import (
    GUARDIAN_PROMPTS,
    GUARDIAN_PROMPT_IDS,
)

__all__ = [
    "ANALYSIS_PROMPTS",
    "ANALYSIS_PROMPT_IDS",
    "GUARDIAN_PROMPTS",
    "GUARDIAN_PROMPT_IDS",
]
