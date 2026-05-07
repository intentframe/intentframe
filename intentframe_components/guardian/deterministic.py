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
from intentframe_components.heuristics import is_sensitive_write_path
from policy_registry.constraints._capability_match import any_tag_matches
from policy_registry.constraints.terminal import TerminalConstraints
from resource_registry.floor import canonicalize_real_path, match_deny_prefix


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
#
# Only *base* capability IDs that command_shield emits as bare tags belong
# here (the intersection check below is literal equality).  Refined-only
# families — ``capability:data_read:*``, ``capability:system_mutate:*``,
# ``capability:network_probe:*`` — never materialise a bare base tag, so
# they are handled by explicit ``startswith`` checks in
# ``_is_read_only_fast_path`` instead.
_READ_ONLY_INCOMPATIBLE: frozenset[str] = frozenset({
    "capability:filesystem_write",
    "capability:stdin_exec",
    "capability:network_bind",
    "capability:background_exec",
    "capability:download_and_exec",
    "capability:process_signal",
    "capability:spawns_process",
})


# WRITE_FILE intents do NOT get a deterministic ALLOW in DG.  Every
# write mutates device state, and agent-provided extension / target
# strings are not trustworthy under prompt injection — "looks like a
# .md" is an attacker-controlled claim, not evidence.  The only
# deterministic decision DG makes about a WRITE_FILE is:
#
#   - BLOCK when the virtual destination is a sensitive system location
#     (shell startup files, credential stores, privilege config,
#     persistence daemons, Python runtime hooks — rule 3 below).
#     Deterministic deny based on a curated list — peer to the VFS
#     floor at ``resource_registry.floor``, which catches the same
#     families on the canonicalized real path at I/O time.  DG blocks
#     on the virtual path pre-AE so agents do not even get an LLM
#     round-trip for a write we will refuse at I/O anyway.
#
# Any other WRITE_FILE falls through UNDECIDED to AE + AIGuardian.
# There is no content-based fast-path — the LLM layer is the only
# route to ALLOW for a mutating write.


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

        # ── 3. WRITE_FILE sensitive destination BLOCK ──────────────
        # Non-negotiable deny for virtual paths that map to sensitive
        # system locations (shell startup files, credential stores,
        # privilege config, persistence daemons, Python runtime hooks).
        # Fires even when user policy nominally allows the destination —
        # a broad ``allowed_paths`` policy must not license writes into
        # files the system re-reads on every new shell / login / boot.
        # Pair of the VFS floor at
        # ``resource_registry.floor.DENY_WRITE_PREFIXES`` which
        # enforces the same families on the canonicalized real path at
        # I/O time; DG blocks on the virtual path so agents don't even
        # reach the AE round-trip for a write we will refuse anyway.
        if action == ActionType.WRITE_FILE.value and \
                is_sensitive_write_path(intent.target):
            return DeterministicResult(
                decision=DeterministicDecision.BLOCK,
                reason=(
                    f"Write to sensitive system location is not permitted: "
                    f"{intent.target!r}"
                ),
                matched_gate="write_file_sensitive_path",
            )

        # ── 3b. HOST_FILE mutation floor BLOCK ─────────────────────
        # Parallel to rule 3, but for the HOST_FILE family which speaks
        # canonicalized real paths directly (no VFS mount indirection).
        # Uses the shared floor list via ``match_deny_prefix`` — the
        # exact same primitive the VFS adapter calls post-mount-resolve
        # for WRITE_FILE / DELETE_FILE / APPEND_ROW.  Running it here
        # pre-AE means a host-file write/delete aimed at a launchd
        # plist / shell rc / keychain / ``~/.ssh`` is refused without
        # an LLM round-trip, matching the WRITE_FILE short-circuit.
        #
        # Separate matched_gate ids on purpose: the WRITE_FILE rule is
        # a virtual-path heuristic (``is_sensitive_write_path``); these
        # two rules are the canonical-real-path floor.  Audit logs must
        # distinguish the two signals.
        if action == ActionType.WRITE_HOST_FILE.value:
            canonical = canonicalize_real_path(intent.target)
            matched = match_deny_prefix(canonical)
            if matched is not None:
                return DeterministicResult(
                    decision=DeterministicDecision.BLOCK,
                    reason=(
                        f"Write to deny-floor host path is not permitted: "
                        f"{matched!r}"
                    ),
                    matched_gate="write_host_file_floor",
                )

        if action == ActionType.DELETE_HOST_FILE.value:
            canonical = canonicalize_real_path(intent.target)
            matched = match_deny_prefix(canonical)
            if matched is not None:
                return DeterministicResult(
                    decision=DeterministicDecision.BLOCK,
                    reason=(
                        f"Delete of deny-floor host path is not permitted: "
                        f"{matched!r}"
                    ),
                    matched_gate="delete_host_file_floor",
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
        # Defensive: sensitive data reads and host-state mutations must
        # never ride a read-only fast-path.  classifier.py's Option-A
        # gate (``_safe_for_read_only``) already suppresses
        # ``read_only:*`` on the same command when any ``data_read:*``
        # or ``system_mutate:*`` tag is emitted; this second layer is
        # belt-and-braces so a future classifier bug cannot silently
        # license a sensitive read / host mutation without AE review.
        if any(c.startswith("capability:data_read:") for c in caps):
            return False
        if any(c.startswith("capability:system_mutate:") for c in caps):
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
