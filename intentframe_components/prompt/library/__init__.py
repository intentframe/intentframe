"""
Prompt library — versioned bodies of the AE and Guardian system prompts.

Analysis Engine prompt ids
--------------------------
``standard``                — general-purpose analysis body
``critical_run_command``    — full-body fork for shell commands
                              (decomposition, compound reversibility,
                              structural-signals consumption)
``critical_network_probe``  — aliased to ``critical_run_command``
                              (initial rollout; per-lane fork later)
``critical_network_mutation`` — aliased to ``critical_run_command``
                              (initial rollout; per-lane fork later)
``critical_write_file``     — full-body fork for file writes
                              (destination-payload cross-check,
                              payload-signals consumption,
                              consumer-awareness)
``critical_generic``        — equals ``standard`` by design; covers
                              PAY_INVOICE, DELETE_*, SEND_EMAIL,
                              HTTP_POST whose rubric is already well-
                              served by the standard body

Guardian prompt ids
-------------------
``standard``                — enforcement body (ALLOW/BLOCK decisions)
``critical``                — equals ``standard`` by design; Guardian's
                              standard body is already enforcement-heavy
                              and a separate critical body would risk
                              instruction drift without adding value

Content policy — full-body forks, not additive overlays
--------------------------------------------------------
The routing infrastructure for every critical lane is fully wired:
``DefaultPromptStrategy`` selects the lane, the engines hold one
:class:`Agent` per prompt id, ``last_prompt_id`` flows into the audit
log, unknown ids fail-closed to ``standard`` with a warning.

Specialisation is done by writing a complete standalone body (a fork),
not by appending to ``standard``.  See ``analysis.py`` for the
``_CRITICAL_RUN_COMMAND`` and ``_CRITICAL_WRITE_FILE`` bodies as
reference.

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
