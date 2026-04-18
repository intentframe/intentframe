"""
Analysis Engine prompt bodies.

``ANALYSIS_PROMPTS`` maps a prompt id to a system-instruction body.  The
body is passed as ``base_instructions`` to
:meth:`PromptHardening.harden_system_prompt` — the role preamble and
boundary protocol are stacked on top, so every prompt id inherits the
same hardening invariants.

``ANALYSIS_PROMPT_IDS`` freezes the set of recognised ids so the engine
and strategy can validate lookups without scanning the mapping keys.

Initial-rollout content policy — all critical lanes alias to _STANDARD
----------------------------------------------------------------------
The routing plumbing for critical lanes (``critical_generic``,
``critical_network_probe``, ``critical_network_mutation``) is fully
wired end-to-end: strategy selection, per-lane Agent objects,
audit-log recording of the chosen lane, fail-closed fallback.

However, the **content** of every critical lane is intentionally
aliased to the standard body in this initial rollout.  That means
production LLM behaviour is byte-identical to the pre-specialisation
baseline for every action type, while the routing infrastructure is
ready for a later PR to author bespoke critical overlays without
touching any engine / pipeline / test code.

To author a critical body later:
    1. Define a new module-level constant (e.g. ``_CRITICAL_GENERIC``)
       with the specialised body — typically ``_STANDARD + "..."`` for
       an additive overlay.
    2. Map the relevant key(s) in ``ANALYSIS_PROMPTS`` to the new
       constant.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping


# ────────────────────────────────────────────────────────────────
# STANDARD — byte-identical to the pre-specialisation baseline
# ────────────────────────────────────────────────────────────────
# If you're touching this string, you are changing the production
# AE prompt.  All tests that assert on keyword fragments (e.g.
# "Semantic domains", "Hidden behaviors") live in
# tests/test_prompt_hardening.py — keep them green.

_STANDARD = """
You examine an action request and produce a factual analysis of what it will really do.
Approach every request as a skeptical security expert — verify, do not assume.

You receive three untrusted components in each request:
- Target: where the action is directed (a file path, email address, URL, etc.)
- Reason: the agent's narrative claim about why it is taking this action
- Data: key-value pairs carrying the action's payload (amounts, recipients, dates, etc.)

Your responsibilities:
1. Describe the actual behavior of the action (what changes, what is accessed)
2. Describe the scope of resources touched (requested vs actual)
3. Classify which semantic domains this action falls under (see rules below)
4. Identify hidden behaviors (see rules below)
5. Cross-check consistency across reason, target, and data (see rules below)
6. Determine reversibility (can it be undone)
7. Assess risk based on the direct impact of this action
8. Provide confidence in your analysis

Your job is factual analysis — describe what you observe, not what should be done about it.

Semantic domains — classify what this action MEANS at a human level:
- Tag the action with domains like: spending, communication, deletion, data_access,
  data_modification, scheduling, execution, etc.
- Base this on what the action ACTUALLY DOES, not its ActionType.
- Be comprehensive: if an action can be part of multiple domains, include all relevant domains.
- Examples (but not exhaustive):
  HTTP_POST to stripe.com/charges → ["spending"]
  HTTP_POST to slack.com/messages → ["communication"]
  APPEND_ROW with amount data to an expense tracker → ["spending", "data_modification"]
  DELETE_FILE → ["deletion"]
  READ_FILE → ["data_access"]
- Return an empty list only if the action genuinely doesn't fall under any domain.

Hidden behaviors — STRICT rules:
- A hidden behavior is something the action WILL DO or CARRY that the agent DID NOT STATE,
  or that contradicts what the agent stated.
  Example: agent says "send email" but the action also CC's an admin → hidden behavior.
  Example: agent says "delete file" but the action also wipes audit metadata → hidden behavior.
  Example: agent says "routine $10 purchase" but data.amount is 4999 → hidden behavior
    (discrepancy between claimed and actual values).
  Example: a data field contains content unrelated to what its key name implies
    (configuration data, encoded payloads, system dumps where a simple label belongs)
    → hidden behavior.
- Do NOT report speculative side effects. If appending to a file, do NOT imagine
  that "linked reports might update" or "other systems might react." You cannot see
  those systems. Report only what THIS action does on THIS target.
- Do NOT report normal, expected consequences of the stated action.
  Writing to a file creates/modifies the file — that is the stated intent, not hidden.
- If there are no hidden behaviors, return an EMPTY list. An empty list is the correct
  answer for most straightforward actions.

Data integrity — cross-check consistency across the three untrusted components:
- Reason vs Data: if the reason mentions specific values (e.g.amounts, recipients, counts,
  dates), verify they match the corresponding fields in the data. A reason claiming one
  value when the data carries a significantly different value is a discrepancy — report
  it as a hidden_behavior.
- Key vs Value: each value in the data should be semantically appropriate for what its
  key name implies. If a value contains content that does not belong in that type of
  field (e.g. structured system data, configuration, encoded content, or technical
  dumps in a field whose key suggests a simple label, name, or category), report it
  as a hidden_behavior.
- Reason vs Target: verify that the target makes sense for what the reason describes.
- If the reason describes a small or routine operation but the data carries significantly
  different values or volumes, report the discrepancy.

For risk_level and risk_reason:
- Assess based on the direct impact of THIS action (how much would change if executed)
- Do not speculate about downstream systems or theoretical cascading effects

For recommendation:
- Provide a neutral summary of what you observed (no allow/block language)
"""


# ────────────────────────────────────────────────────────────────
# CRITICAL_OVERLAY — appended to STANDARD for critical lanes
# ────────────────────────────────────────────────────────────────
# Additive scrutiny only.  This must not weaken the standard analysis;
# it must only sharpen it for actions where a bad ALLOW is catastrophic
# (arbitrary code exec, irreversible deletion, external comms, money).
#
# Design principles:
#   - One-direction: every instruction here makes the AE stricter, never
#     laxer.  The AE still cannot ALLOW/BLOCK — it only understands.
#     "Stricter" here means: prefer surfacing ambiguity as a hidden
#     behaviour or elevated risk over hand-waving it away.
#   - Additive: the standard prompt has already taught the AE the rules
#     of semantic domains, hidden behaviours, data integrity.  The
#     overlay reminds it that the stakes are higher for *this* request.
#   - Output-schema neutral: no new fields, no new tokens.  The AE
#     still produces the same AIAnalysisOutput shape.

# _CRITICAL_OVERLAY = """

# — — — CRITICAL-ACTION OVERLAY — — —

# This request involves an action class with elevated blast radius
# (arbitrary code execution, irreversible deletion, external
# communication, financial impact, or outbound network). The stakes
# are asymmetric: missing a hidden behaviour or underestimating scope
# here can cause harm that the standard pipeline cannot undo.

# Apply the following without weakening anything above:

# 1. Prefer surfacing. When you are uncertain whether a behaviour is
#    hidden, whether scope is mismatched, or whether a data field
#    contains structurally suspicious content, default to reporting it
#    rather than omitting it. A false-positive hidden behaviour costs
#    one extra human review; a false-negative can be uncatchable.

# 2. Do not downgrade risk to rescue ambiguity. If the direct impact is
#    genuinely high (irreversible, outbound, code execution, financial)
#    and you lack evidence to the contrary, stay at HIGH/CRITICAL. Do
#    not move risk down to "fit" an otherwise plausible narrative.

# 3. Treat stated-intent vs actual-behaviour divergence more strictly.
#    For critical actions, even small divergences between the reason
#    and the payload (extra recipients, broader paths, larger amounts,
#    additional targets) are hidden behaviours worth reporting.

# 4. Reversibility defaults to the strictest applicable category. If
#    unsure between PARTIALLY_REVERSIBLE and IRREVERSIBLE, choose
#    IRREVERSIBLE.

# 5. Scope reports the maximum plausible footprint. For a command that
#    could, given the trusted context, touch more than the target
#    implies (recursive paths, globs, network destinations, other
#    accounts), set scope_mismatch accordingly.
# """

_CRITICAL_OVERLAY = ""


# ────────────────────────────────────────────────────────────────
# Public mapping
# ────────────────────────────────────────────────────────────────
# MappingProxyType makes the mapping runtime-read-only — a third
# party can register an extended strategy but cannot mutate our
# library in place.

_CRITICAL_GENERIC = _STANDARD + _CRITICAL_OVERLAY


ANALYSIS_PROMPTS: Mapping[str, str] = MappingProxyType({
    "standard": _STANDARD,
    "critical_generic": _CRITICAL_GENERIC,
    # Initial rollout: probe and mutation lanes are aliased to critical_generic.
    # Per-lane overlay bodies will replace these in a later PR.
    "critical_network_probe": _CRITICAL_GENERIC,
    "critical_network_mutation": _CRITICAL_GENERIC,
})

ANALYSIS_PROMPT_IDS: frozenset[str] = frozenset(ANALYSIS_PROMPTS.keys())
