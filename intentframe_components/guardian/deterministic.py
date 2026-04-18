"""Layer 4 — Deterministic Guardian (pre-AE pass).

Splits Guardian's deterministic stage out of :class:`AIGuardian` so the
pipeline can render BLOCK / ALLOW decisions **before** paying the
Analysis-Engine LLM cost.  Nothing here is new policy: steps 1–3
(permission, constraint, domain) are a lift-and-rearrange of logic that
used to run inside :class:`AIGuardian.validate`.  Steps 4 and 5 are the
additive ALLOW short-circuits powered by :mod:`command_shield`'s
capability tags.

This module is an internal split of the Guardian layer, not a new
architectural layer.  The defense-in-depth invariant is unchanged:

    command_shield (L0)  — own catastrophic recognition
    policy_registry (L1) — system-floor patterns
    analysis_engine (L2) — own catastrophic + passive-read gates
    DeterministicGuardian (L3a) — this module
    AIGuardian (L3b)     — its own deterministic gates remain intact
                           (redundant when DG ran first, but critical
                           for any caller that invokes AIGuardian
                           standalone)
    executor/adapter (L4) — command_shield quick_check floor

Fail-closed posture:
    - BLOCK is only returned from explicit matched gates.
    - Any internal exception yields UNDECIDED so the AI path still
      runs (it will re-evaluate the same gates).  We do NOT silently
      ALLOW on error.
    - ALLOW is only returned from a named gate — never by default.

No-self-IO:
    DeterministicGuardian reads the already-snapshotted
    :class:`UserContext`, the pre-computed :class:`CommandIntel`, and
    the registered per-category checkers / domain modules.  It does
    not touch the network, disk, or the user.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from action_registry.types import ACTION_DOMAINS, ActionType
from intentframe_core.types import (
    CommandIntel,
    ExecutionContext,
    IntentFrame,
    UserContext,
)
from intentframe_components.guardian.checkers import CheckContext, CONSTRAINT_CHECKERS
from intentframe_components.guardian.domains import DOMAIN_MODULES
from policy_registry.constraints._capability_match import any_tag_matches
from policy_registry.constraints.terminal import TerminalConstraints


class DeterministicDecision(str, Enum):
    """Outcome of the pre-AE deterministic pass."""

    BLOCK = "BLOCK"
    ALLOW = "ALLOW"
    UNDECIDED = "UNDECIDED"


@dataclass(frozen=True)
class DeterministicResult:
    """Decision + audit metadata.

    ``matched_gate`` identifies WHICH rule fired so audit logs and
    metrics distinguish permission-BLOCK from constraint-BLOCK and
    passive-read-ALLOW from read-only-ALLOW.  It is always populated —
    including for ``UNDECIDED`` — to keep downstream formatting simple.
    """

    decision: DeterministicDecision
    reason: str = ""
    matched_gate: str = ""


# Actions that are "passive system reads" — no user-facing content,
# no state mutation, no side-effecting IO.  Sourced directly from
# :pydata:`AIAnalysisEngine._PASSIVE_READ_ACTIONS` so AE's internal
# fast-path and DG's pre-AE ALLOW cover exactly the same universe.
# Keeping a single source of truth removes the drift risk that
# duplicating the list would introduce.  User-facing IO (ASK_USER,
# SHOW_MESSAGE, GET_CONFIRMATION) is deliberately excluded there —
# prompt contents must be AE-inspected.
from intentframe_components.analysis.engine import AIAnalysisEngine as _AIAnalysisEngine

_PRE_AE_SAFE_READS: frozenset[str] = frozenset(_AIAnalysisEngine._PASSIVE_READ_ACTIONS)


# Capability tags that disqualify a RUN_COMMAND from the read-only
# fast-path even when a read_only:* tag is also present.  command_shield's
# structural gate already keeps these families mutually exclusive on the
# same command — this set is belt-and-braces on the consumer side.
_READ_ONLY_INCOMPATIBLE: frozenset[str] = frozenset({
    "capability:filesystem_write",
    "capability:stdin_exec",
    "capability:network_bind",
    "capability:background_exec",
    "capability:download_and_exec",
    "capability:process_signal",
    "capability:spawns_process",
})


class DeterministicGuardian:
    """Pre-AE deterministic stage of Guardian.

    Usage (from the pipeline):

        result = det_guardian.decide(
            intent, user_context,
            active_domains=active_domains,
            execution_context=self._execution_context,
            command_intel=command_intel,
        )
        if result.decision is DeterministicDecision.BLOCK: ...
        if result.decision is DeterministicDecision.ALLOW: ...
        # otherwise proceed to AE + AIGuardian

    Not async — every operation is local and deterministic.  The
    sync signature makes the "this never touches IO" invariant
    grepably obvious.
    """

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose

    def decide(
        self,
        intent: IntentFrame,
        user_context: UserContext,
        active_domains: Optional[set[str]] = None,
        execution_context: Optional[ExecutionContext] = None,
        command_intel: Optional[CommandIntel] = None,
    ) -> DeterministicResult:
        """Run the deterministic pass.  See module docstring for rules.

        ``active_domains`` and ``execution_context`` are accepted for
        forward-compatibility with richer gates; today the six rules
        below ignore them.  Carrying the parameters means DG can be
        wired into the pipeline without another signature change when
        a future rule needs them.
        """
        del active_domains, execution_context  # reserved; see docstring

        try:
            return self._decide_inner(intent, user_context, command_intel)
        except Exception as exc:  # noqa: BLE001 - fail-open to UNDECIDED, never ALLOW
            if self.verbose:
                print(f"    │  DG exception: {exc!r} — UNDECIDED")
            return DeterministicResult(
                decision=DeterministicDecision.UNDECIDED,
                reason=f"deterministic guardian error: {exc!r}",
                matched_gate="exception",
            )

    def _decide_inner(
        self,
        intent: IntentFrame,
        user_context: UserContext,
        command_intel: Optional[CommandIntel],
    ) -> DeterministicResult:
        action = intent.action.value

        # ── 1. Permission check (deny-by-default) ──────────────────
        if action not in user_context.allowed_actions:
            return DeterministicResult(
                decision=DeterministicDecision.BLOCK,
                reason=f"Action '{action}' is not permitted by user policy",
                matched_gate="permission",
            )

        permission = user_context.allowed_actions[action]

        # ── 2. Constraint check (per-category checker) ─────────────
        if permission.constraints is not None:
            checker = CONSTRAINT_CHECKERS.get(type(permission.constraints))
            if checker is not None:
                ctx = CheckContext(command_intel=command_intel)
                passed, reason = checker.check(
                    intent, permission.constraints, ctx
                )
                if not passed:
                    return DeterministicResult(
                        decision=DeterministicDecision.BLOCK,
                        reason=f"Constraint violation: {reason}",
                        matched_gate="constraint",
                    )

        # ── 2.5 Domain module enforcement (structural hard gate) ───
        domain = ACTION_DOMAINS.get(intent.action)
        if domain is not None and domain in DOMAIN_MODULES:
            domain_constraints = self._get_domain_constraints(
                user_context, domain
            )
            if domain_constraints is not None:
                module = DOMAIN_MODULES[domain]
                passed, reason = module.check(intent, domain_constraints)
                if not passed:
                    return DeterministicResult(
                        decision=DeterministicDecision.BLOCK,
                        reason=f"Domain violation ({domain.value}): {reason}",
                        matched_gate="domain",
                    )

        # ── 4. Passive-read ALLOW short-circuit ────────────────────
        # Same semantics as AE's _PASSIVE_READ_ACTIONS fast-path, but
        # skips AE + AIGuardian entirely.  Requires permission.safe
        # so a user who explicitly marked a read action as "needs AI
        # review" (safe=False) still gets one.
        if action in _PRE_AE_SAFE_READS and permission.safe:
            return DeterministicResult(
                decision=DeterministicDecision.ALLOW,
                reason=f"Permitted (deterministic: passive read): {action}",
                matched_gate="passive_read",
            )

        # ── 5. RUN_COMMAND read-only ALLOW short-circuit ───────────
        if action == ActionType.RUN_COMMAND.value and command_intel is not None:
            deny_caps = self._deny_capabilities(permission.constraints)
            if self._is_read_only_fast_path(command_intel, deny_caps):
                return DeterministicResult(
                    decision=DeterministicDecision.ALLOW,
                    reason="Permitted (deterministic: read-only command)",
                    matched_gate="run_command_read_only",
                )

        # ── 7. Otherwise → AI decides ──────────────────────────────
        # (Step 6 in the design spec — the permission.safe+no-risk
        # short-circuit — is intentionally NOT implemented here.
        # AE already covers it for passive reads; applying it more
        # broadly pre-AE would bypass content inspection for actions
        # like SEND_EMAIL or ASK_USER even when the user marked them
        # safe, which weakens social-engineering defense.)
        return DeterministicResult(
            decision=DeterministicDecision.UNDECIDED,
            reason="",
            matched_gate="undecided",
        )

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _get_domain_constraints(user_context: UserContext, domain):
        """Mirror of :py:meth:`AIGuardian._get_domain_constraints`.

        Duplicated (not imported) to keep DG standalone — so an
        AIGuardian refactor cannot accidentally change DG's domain
        lookup semantics.
        """
        dc_map = user_context.domain_constraints or {}
        return dc_map.get(domain.value)

    @staticmethod
    def _deny_capabilities(constraints) -> frozenset[str]:
        """Extract deny_capabilities from TerminalConstraints if present.

        Returns empty frozenset for all other constraint types — the
        field is TerminalConstraints-specific today and any other
        shape means "no capability policy".
        """
        if isinstance(constraints, TerminalConstraints):
            return constraints.deny_capabilities
        return frozenset()

    @staticmethod
    def _is_read_only_fast_path(
        intel: CommandIntel,
        deny_caps: frozenset[str],
    ) -> bool:
        """Return True iff the RUN_COMMAND qualifies for ALLOW without AE.

        The checks mirror the TODO design literally; each one is a
        structural exclusion, and a command must clear every one.
        """
        if intel.verdict != "SAFE":
            return False
        caps = set(intel.capabilities)
        if not any(c.startswith("capability:read_only:") for c in caps):
            return False
        if caps & _READ_ONLY_INCOMPATIBLE:
            return False
        # Defensive: network-probe and read-only are disjoint at the
        # shield-classifier level.  Re-check here so a future family
        # interaction cannot silently license outbound traffic.
        if any(c.startswith("capability:network_probe:") for c in caps):
            return False
        if deny_caps and any_tag_matches(caps, deny_caps) is not None:
            return False
        if intel.has_edge_signals:
            return False
        if intel.has_code_intel_findings:
            return False
        return True


__all__ = [
    "DeterministicDecision",
    "DeterministicGuardian",
    "DeterministicResult",
    "_PRE_AE_SAFE_READS",
    "_READ_ONLY_INCOMPATIBLE",
]
