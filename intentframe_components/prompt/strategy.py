"""
Prompt-id strategy — deterministic routing to AE/Guardian prompt lanes.

This module is the single place that decides which prompt id the
Analysis Engine and Guardian should use for a given intent.  It is
deliberately kept outside both engines so:

- Routing can be tested without instantiating any :class:`Agent`.
- A future per-criticality-engine architecture (separate engine instances)
  can reuse the same routing decisions by consuming the prompt id and
  dispatching to a different engine.
- Third parties can ship their own :class:`PromptStrategy` by
  satisfying the Protocol, without touching the engines.

Routing model
-------------
Analysis Engine ids, in precedence order (strictest wins):

    critical_network_mutation   (RUN_COMMAND + capability:network_probe:{http_mutate, http_download, port_scan, file_transfer})
    critical_network_probe      (RUN_COMMAND + capability:network_probe:{icmp, trace, dns, whois, http_get})
    critical_run_command        (RUN_COMMAND default — no recognised network caps, or no command_intel)
    critical_write_file         (action == WRITE_FILE — every write)
    critical_generic            (action ∈ CRITICAL_ACTIONS, not RUN_COMMAND or WRITE_FILE)
    standard                    (everything else)

Guardian ids:

    critical                    (action ∈ CRITICAL_ACTIONS)
    standard                    (everything else)

Fail-closed
-----------
If ``command_intel`` is ``None`` for a RUN_COMMAND, we route to
``critical_run_command``, not ``standard``.  A missing ``CommandIntel``
on a RUN_COMMAND indicates a plumbing bug somewhere upstream; the safe
default is the command-specific body (teaches decomposition, compound
reversibility, structural-signal consumption) rather than the generic
standard body.

Role of ``file_intel``
----------------------
``file_intel`` is accepted on both ``select_ae_prompt_id`` and
``select_guardian_prompt_id`` strictly as context that the engines
forward into their prompts (payload language, binary / oversized flags,
code-intel findings).  The default strategy does **not** consult it to
pick a prompt id — every WRITE_FILE lands in ``critical_write_file``
regardless of payload shape.  Content-aware lanes (e.g. a future
``critical_write_file_code``) are deferred; when authored they will be
full-body forks of ``_CRITICAL_WRITE_FILE``, not additive overlays.
"""

from __future__ import annotations

from typing import Protocol

from action_registry.types import ActionType
from intentframe_core.types import AnalysisReport, CommandIntel, FileIntel, IntentFrame
from intentframe_components.routing.criticality import is_critical


# ────────────────────────────────────────────────────────────────
# Capability sub-tags — the sub-routing lookup tables
# ────────────────────────────────────────────────────────────────
# Precedence is encoded by the order we check: mutation before
# probe before generic.  Keep these sets aligned with the
# capability tags emitted by command_shield.classifier.

_NETWORK_MUTATION_SUBTAGS: frozenset[str] = frozenset({
    "http_mutate",
    "http_download",
    "port_scan",
    "file_transfer",
})

_NETWORK_PROBE_SUBTAGS: frozenset[str] = frozenset({
    "icmp",
    "trace",
    "dns",
    "whois",
    "http_get",
})

_NETWORK_PROBE_PREFIX = "capability:network_probe:"


def _has_network_mutation(caps: tuple[str, ...]) -> bool:
    """Return True if any cap is a network_probe mutation sub-tag."""
    for cap in caps:
        if not cap.startswith(_NETWORK_PROBE_PREFIX):
            continue
        sub = cap[len(_NETWORK_PROBE_PREFIX):]
        if sub in _NETWORK_MUTATION_SUBTAGS:
            return True
    return False


def _has_network_probe(caps: tuple[str, ...]) -> bool:
    """Return True if any cap is a network_probe non-mutation sub-tag."""
    for cap in caps:
        if not cap.startswith(_NETWORK_PROBE_PREFIX):
            continue
        sub = cap[len(_NETWORK_PROBE_PREFIX):]
        if sub in _NETWORK_PROBE_SUBTAGS:
            return True
    return False


# WRITE_FILE destination heuristics live in
# :mod:`intentframe_components.heuristics.file_payload`.  The default
# strategy no longer calls into them — WRITE_FILE routes flat to
# ``critical_write_file`` — but :class:`DeterministicGuardian` still
# consumes ``is_sensitive_write_path`` from that module as a BLOCK rule.


# ────────────────────────────────────────────────────────────────
# Protocol
# ────────────────────────────────────────────────────────────────

class PromptStrategy(Protocol):
    """Contract for routing intents to AE/Guardian prompt ids.

    A strategy is sync and pure: given the same inputs it must return
    the same prompt id, every time.  It does not perform IO and does
    not mutate its inputs.

    The engines hold a reference to exactly one strategy instance at
    construction time; the strategy is consulted once per request.
    """

    def select_ae_prompt_id(
        self,
        intent: IntentFrame,
        command_intel: CommandIntel | None,
        file_intel: FileIntel | None = None,
    ) -> str:
        """Return the AE prompt id for this request.

        ``file_intel`` is populated only for WRITE_FILE intents and
        carries payload facts from :func:`command_shield.inspect_code`
        (language, binary/oversized flags, code-intel findings).  The
        default strategy does not route on it — it is accepted on the
        Protocol so the engines can hand the same value to AE's
        payload builder, and so a future custom strategy can split
        WRITE_FILE into payload-aware lanes without a signature change.
        """
        ...

    def select_guardian_prompt_id(
        self,
        intent: IntentFrame,
        analysis: AnalysisReport,
        command_intel: CommandIntel | None,
        file_intel: FileIntel | None = None,
    ) -> str:
        """Return the Guardian prompt id for this request.

        ``analysis`` is passed so future strategies can route on
        AE-classified risk / domains (e.g. finance → finance prompt).
        The default strategy ignores it beyond action-type checks.
        """
        ...


# ────────────────────────────────────────────────────────────────
# Default implementation
# ────────────────────────────────────────────────────────────────

class DefaultPromptStrategy:
    """Deterministic, capability-aware prompt-id selector.

    This is the production default baked into both engines.  It is
    stateless and safe to share across requests / threads.
    """

    # Explicit precedence table.  Do not rely on Python dict
    # ordering — these are ordered predicates.  The first predicate
    # that matches wins.
    _AE_PRECEDENCE: tuple[str, ...] = (
        "critical_network_mutation",
        "critical_network_probe",
        "critical_run_command",
        "critical_write_file",
        "critical_generic",
        "standard",
    )

    _GUARDIAN_PRECEDENCE: tuple[str, ...] = (
        "critical",
        "standard",
    )

    # ── AE ──────────────────────────────────────────────────────

    def select_ae_prompt_id(
        self,
        intent: IntentFrame,
        command_intel: CommandIntel | None,
        file_intel: FileIntel | None = None,
    ) -> str:
        # ``file_intel`` is accepted on the Protocol so engines can pass
        # it through; the default strategy does not route on it.  WRITE_FILE
        # lands in ``critical_write_file`` unconditionally — payload-aware
        # sub-lanes are deferred to a later PR.
        del file_intel

        action_value = intent.action.value

        # RUN_COMMAND sub-routing lives on the AE side only.
        if action_value == ActionType.RUN_COMMAND.value:
            caps = command_intel.capabilities if command_intel else ()
            if _has_network_mutation(caps):
                return "critical_network_mutation"
            if _has_network_probe(caps):
                return "critical_network_probe"
            # RUN_COMMAND without known network sub-tags (or with no
            # command_intel at all) falls through to the command-
            # specific base body.  This is the fail-closed default for
            # a missing-intel plumbing bug — the command-specific body
            # is stricter than _STANDARD (teaches decomposition,
            # compound reversibility, structural-signal consumption).
            return "critical_run_command"

        if action_value in {
            ActionType.WRITE_FILE.value,
            ActionType.WRITE_HOST_FILE.value,
        }:
            return "critical_write_file"

        if is_critical(action_value):
            return "critical_generic"

        return "standard"

    # ── Guardian ────────────────────────────────────────────────

    def select_guardian_prompt_id(
        self,
        intent: IntentFrame,
        analysis: AnalysisReport,
        command_intel: CommandIntel | None,
        file_intel: FileIntel | None = None,
    ) -> str:
        # analysis, command_intel, and file_intel are accepted for future
        # strategies (e.g. finance-domain Guardian prompt, payload-aware
        # Guardian lanes); the default strategy routes purely on action
        # criticality.
        del analysis, command_intel, file_intel

        if is_critical(intent.action.value):
            return "critical"
        return "standard"


__all__ = [
    "PromptStrategy",
    "DefaultPromptStrategy",
]
