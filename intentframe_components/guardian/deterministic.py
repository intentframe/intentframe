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

from action_registry.types import ACTION_DOMAINS
from intentframe_core.types import (
    CommandIntel,
    ExecutionContext,
    IntentFrame,
    UserContext,
)
from intentframe_action_bundle.passive_read.actions import PASSIVE_READ_ACTIONS
from intentframe_action_bundle.registry import run_bundle_deterministic
from intentframe_action_bundle.terminal._read_only import (
    READ_ONLY_INCOMPATIBLE as _READ_ONLY_INCOMPATIBLE,
    is_read_only_fast_path,
)
from intentframe_action_bundle.types import BundleDeterministicContext
from intentframe_components.guardian.checkers import CheckContext, CONSTRAINT_CHECKERS
from intentframe_components.guardian.domains import DOMAIN_MODULES
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


# Passive-read actions — canonical list lives in intentframe_action_bundle.
_PRE_AE_SAFE_READS: frozenset[str] = PASSIVE_READ_ACTIONS


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

        # ── 3–5. Bundle deterministic gates (family-specific) ───────
        bundle_ctx = BundleDeterministicContext(command_intel=command_intel)
        bundle_result = run_bundle_deterministic(intent, permission, bundle_ctx)
        if bundle_result is not None:
            return bundle_result

        # ── 6. Otherwise → AI decides ──────────────────────────────
        # Every mutating write (WRITE_FILE, DELETE_FILE, etc.), every
        # user-IO action, and every action without a positive
        # deterministic-ALLOW gate above falls through here.  There is
        # no passive-write fast-path: content-based "this looks
        # inert" checks cannot be made sound under an adversarial
        # agent (extensions and payload language sniffing are not
        # trust anchors), so writes always pay the LLM review.
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
        """Delegate to terminal bundle read-only helper (tests import this)."""
        return is_read_only_fast_path(intel, deny_caps)


__all__ = [
    "DeterministicDecision",
    "DeterministicGuardian",
    "DeterministicResult",
    "_PRE_AE_SAFE_READS",
    "_READ_ONLY_INCOMPATIBLE",
]
