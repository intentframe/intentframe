"""
Prompt library — versioned bodies of the AE and Guardian system prompts.

The prompt-specialisation & criticality-routing refactor establishes the
library with two prompt ids for Guardian and four prompt ids for the
Analysis Engine:

Analysis Engine
    ``standard``                    — byte-identical to the pre-specialisation baseline
    ``critical_generic``            — **initial rollout**: aliased to ``standard``
                                      (overlay body is currently empty —
                                      see initial-rollout content policy below)
    ``critical_network_probe``      — aliased to ``critical_generic``
    ``critical_network_mutation``   — aliased to ``critical_generic``

Guardian
    ``standard``                    — byte-identical to the pre-specialisation baseline
    ``critical``                    — **initial rollout**: aliased to ``standard``
                                      (overlay body is currently empty —
                                      see initial-rollout content policy below)

Initial-rollout content policy — plumbing lands, bodies are deferred
---------------------------------------------------------------------
The routing infrastructure for every critical lane is fully wired:
``DefaultPromptStrategy`` selects the lane, the engines hold one
:class:`Agent` per prompt id, ``last_prompt_id`` flows into the audit
log, unknown ids fail-closed to ``standard`` with a warning.

However the **text content** of every critical lane is intentionally
equal to ``standard`` in this initial rollout — the ``_CRITICAL_OVERLAY``
constants in ``analysis.py`` and ``guardian.py`` are ``""``.  This means
production LLM behaviour is byte-identical to the pre-specialisation
baseline for every action type while the routing seam is ready for a
later PR to author bespoke overlays without touching any engine /
pipeline / strategy / audit code.

Six tests in ``tests/test_prompt_library.py`` are marked
``@pytest.mark.xfail(strict=False, ...)`` as living placeholders for
that work — when the overlays are authored they will xpass and can
then have the marker removed.

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
