"""Unit tests for DeterministicGuardian (Bundle B / Phase 4).

Covers the six rules of the pre-AE pass:

  1. Permission check          → BLOCK / passthrough
  2. Constraint check          → BLOCK / passthrough
  2.5 Domain module check      → BLOCK / passthrough
  4. Passive-read ALLOW        → ALLOW on safe passive reads
  5. RUN_COMMAND read-only     → ALLOW on read-only capability tags
  7. Default                   → UNDECIDED (AE + AIGuardian handle it)

Also covers:

  - Fail-closed exception path (UNDECIDED, never ALLOW)
  - deny_capabilities blocks the read-only fast-path
  - Incompatible capability tags disqualify the read-only fast-path
  - Code-intel findings / edge signals disqualify the fast-path
  - network_probe tags disqualify the fast-path even with read-only
"""

from __future__ import annotations

import pytest

from action_registry.types import ActionType
from intentframe_components.guardian.deterministic import (
    DeterministicDecision,
    DeterministicGuardian,
    DeterministicResult,
    _PRE_AE_SAFE_READS,
    _READ_ONLY_INCOMPATIBLE,
)
from intentframe_core.types import CommandIntel, IntentFrame, UserContext
from policy_registry.constraints.terminal import TerminalConstraints
from policy_registry.models import ActionPermission


# ───────────────────────────── helpers ─────────────────────────────

def _intent(action: ActionType, target: str = "", **data) -> IntentFrame:
    return IntentFrame(
        action=action,
        target=target,
        data=dict(data) if data else None,
        reason="test",
        agent_id="test_agent",
    )


def _user(**actions: ActionPermission) -> UserContext:
    return UserContext(user_id="tester", allowed_actions=dict(actions))


def _intel(
    *capabilities: str,
    verdict: str = "SAFE",
    has_edge: bool = False,
    has_code: bool = False,
) -> CommandIntel:
    return CommandIntel(
        verdict=verdict,
        capabilities=tuple(capabilities),
        has_edge_signals=has_edge,
        has_code_intel_findings=has_code,
    )


# ═══════════════════════════════════════════════════════════════════════
# STEP 1 — Permission check (deny-by-default)
# ═══════════════════════════════════════════════════════════════════════

class TestPermissionGate:
    dg = DeterministicGuardian()

    def test_action_not_in_allowed_actions_blocks(self):
        result = self.dg.decide(
            _intent(ActionType.READ_FILE, "/tmp/x"),
            _user(),  # nothing allowed
        )
        assert result.decision is DeterministicDecision.BLOCK
        assert result.matched_gate == "permission"
        assert "not permitted" in result.reason.lower()

    def test_action_in_allowed_actions_passes_gate(self):
        # safe=False so passive-read ALLOW doesn't fire
        result = self.dg.decide(
            _intent(ActionType.READ_FILE, "/tmp/x"),
            _user(READ_FILE=ActionPermission(safe=False)),
        )
        # Would fall through to UNDECIDED (no constraint, no passive-safe)
        assert result.decision is DeterministicDecision.UNDECIDED


# ═══════════════════════════════════════════════════════════════════════
# STEP 2 — Per-category constraint check
# ═══════════════════════════════════════════════════════════════════════

class TestConstraintGate:
    dg = DeterministicGuardian()

    def test_deny_capability_blocks_before_ae(self):
        """deny_capabilities is enforced by TerminalChecker via
        CheckContext; DG must wire command_intel through for this
        to work from the pre-AE pass."""
        constraints = TerminalConstraints(
            deny_capabilities=frozenset({"capability:package_install:*"}),
        )
        result = self.dg.decide(
            _intent(ActionType.RUN_COMMAND, target="pip install foo"),
            _user(RUN_COMMAND=ActionPermission(safe=False, constraints=constraints)),
            command_intel=_intel("capability:package_install:pip"),
        )
        assert result.decision is DeterministicDecision.BLOCK
        assert result.matched_gate == "constraint"
        assert "package_install" in result.reason

    def test_blocked_pattern_blocks_before_ae(self):
        constraints = TerminalConstraints(blocked_patterns=["sudo"])
        result = self.dg.decide(
            _intent(ActionType.RUN_COMMAND, target="sudo ls"),
            _user(RUN_COMMAND=ActionPermission(safe=False, constraints=constraints)),
            command_intel=_intel(),
        )
        assert result.decision is DeterministicDecision.BLOCK
        assert result.matched_gate == "constraint"
        assert "sudo" in result.reason

    def test_no_constraints_passes_gate(self):
        result = self.dg.decide(
            _intent(ActionType.RUN_COMMAND, target="echo hi && echo bye"),
            _user(RUN_COMMAND=ActionPermission(safe=False)),
            command_intel=_intel(verdict="SAFE"),  # no caps → no read-only ALLOW
        )
        assert result.decision is DeterministicDecision.UNDECIDED


# ═══════════════════════════════════════════════════════════════════════
# STEP 4 — Passive-read ALLOW short-circuit
# ═══════════════════════════════════════════════════════════════════════

class TestPassiveReadFastPath:
    dg = DeterministicGuardian()

    def test_passive_read_safe_allows(self):
        result = self.dg.decide(
            _intent(ActionType.READ_FILE, "/tmp/x"),
            _user(READ_FILE=ActionPermission(safe=True)),
        )
        assert result.decision is DeterministicDecision.ALLOW
        assert result.matched_gate == "passive_read"

    def test_passive_read_unsafe_falls_through(self):
        """safe=False means the user asked for AI review — DG must
        not ALLOW just because the action is conceptually passive."""
        result = self.dg.decide(
            _intent(ActionType.READ_FILE, "/tmp/x"),
            _user(READ_FILE=ActionPermission(safe=False)),
        )
        assert result.decision is DeterministicDecision.UNDECIDED

    def test_non_passive_safe_action_falls_through(self):
        """SEND_EMAIL marked safe is NOT passive — DG falls through
        so AE can still inspect the prompt content."""
        result = self.dg.decide(
            _intent(ActionType.SEND_EMAIL, target="x@y.com"),
            _user(SEND_EMAIL=ActionPermission(safe=True)),
        )
        assert result.decision is DeterministicDecision.UNDECIDED

    def test_passive_read_set_matches_ae_passive_set(self):
        """DG and AE must agree on what counts as a passive read
        so their fast-path universes stay aligned."""
        from intentframe_components.analysis.engine import AIAnalysisEngine
        assert _PRE_AE_SAFE_READS == frozenset(AIAnalysisEngine._PASSIVE_READ_ACTIONS)


# ═══════════════════════════════════════════════════════════════════════
# STEP 5 — RUN_COMMAND read-only ALLOW short-circuit
# ═══════════════════════════════════════════════════════════════════════

class TestReadOnlyFastPath:
    dg = DeterministicGuardian()

    perm = ActionPermission(safe=False)

    def _decide(self, command: str, intel: CommandIntel) -> DeterministicResult:
        return self.dg.decide(
            _intent(ActionType.RUN_COMMAND, target=command),
            _user(RUN_COMMAND=self.perm),
            command_intel=intel,
        )

    def test_read_only_safe_command_allows(self):
        intel = _intel("capability:read_only:filesystem_list", verdict="SAFE")
        result = self._decide("ls -la", intel)
        assert result.decision is DeterministicDecision.ALLOW
        assert result.matched_gate == "run_command_read_only"

    def test_needs_review_verdict_blocks_fast_path(self):
        intel = _intel("capability:read_only:filesystem_list", verdict="NEEDS_REVIEW")
        result = self._decide("ls -la | grep foo", intel)
        assert result.decision is DeterministicDecision.UNDECIDED

    def test_no_capabilities_no_fast_path(self):
        intel = _intel(verdict="SAFE")
        result = self._decide("echo hi && echo bye", intel)
        assert result.decision is DeterministicDecision.UNDECIDED

    @pytest.mark.parametrize("bad_cap", sorted(_READ_ONLY_INCOMPATIBLE))
    def test_incompatible_capability_blocks_fast_path(self, bad_cap):
        """Each incompatible tag alone disqualifies the fast path —
        defense against classifier co-emitting read_only + dangerous."""
        intel = _intel(
            "capability:read_only:filesystem_list",
            bad_cap,
            verdict="SAFE",
        )
        result = self._decide("cmd", intel)
        assert result.decision is DeterministicDecision.UNDECIDED

    def test_network_probe_blocks_fast_path(self):
        """Belt-and-braces: network_probe and read_only are structurally
        disjoint at the classifier, but a future interaction must not
        silently license outbound traffic."""
        intel = _intel(
            "capability:read_only:system_info",
            "capability:network_probe:icmp",
            verdict="SAFE",
        )
        result = self._decide("cmd", intel)
        assert result.decision is DeterministicDecision.UNDECIDED

    def test_code_intel_findings_block_fast_path(self):
        intel = _intel(
            "capability:read_only:filesystem_read",
            verdict="SAFE",
            has_code=True,
        )
        result = self._decide("cat script.py", intel)
        assert result.decision is DeterministicDecision.UNDECIDED

    def test_edge_signals_block_fast_path(self):
        intel = _intel(
            "capability:read_only:filesystem_read",
            verdict="SAFE",
            has_edge=True,
        )
        result = self._decide("cat something", intel)
        assert result.decision is DeterministicDecision.UNDECIDED

    def test_deny_capabilities_policy_blocks_fast_path(self):
        """deny_capabilities in policy should veto the fast-path
        even if every other gate would ALLOW."""
        constraints = TerminalConstraints(
            deny_capabilities=frozenset({"capability:read_only:*"}),
        )
        perm = ActionPermission(safe=False, constraints=constraints)
        result = self.dg.decide(
            _intent(ActionType.RUN_COMMAND, target="ls"),
            _user(RUN_COMMAND=perm),
            command_intel=_intel("capability:read_only:filesystem_list"),
        )
        # TerminalChecker (Step 2) catches this FIRST — so it's a
        # constraint BLOCK, not a fast-path miss.  Either way it's
        # not an ALLOW.
        assert result.decision is DeterministicDecision.BLOCK

    def test_command_intel_none_skips_fast_path(self):
        """Without CommandIntel, the fast-path cannot fire."""
        result = self.dg.decide(
            _intent(ActionType.RUN_COMMAND, target="ls"),
            _user(RUN_COMMAND=self.perm),
            command_intel=None,
        )
        assert result.decision is DeterministicDecision.UNDECIDED


# ═══════════════════════════════════════════════════════════════════════
# Non-passive, non-run-command actions → UNDECIDED
# ═══════════════════════════════════════════════════════════════════════

class TestUndecidedDefault:
    dg = DeterministicGuardian()

    def test_send_email_with_constraints_falls_through(self):
        from policy_registry.constraints.email import EmailConstraints
        perm = ActionPermission(
            safe=False,
            constraints=EmailConstraints(allowed_recipients=["a@b.com"]),
        )
        result = self.dg.decide(
            _intent(ActionType.SEND_EMAIL, target="x", to="a@b.com"),
            _user(SEND_EMAIL=perm),
        )
        assert result.decision is DeterministicDecision.UNDECIDED

    def test_ask_user_safe_does_not_fast_path(self):
        """ASK_USER/GET_CONFIRMATION/SHOW_MESSAGE must always go
        through AE even when marked safe — their prompt content has
        to be inspected for social-engineering / phishing."""
        result = self.dg.decide(
            _intent(ActionType.ASK_USER, target="prompt"),
            _user(ASK_USER=ActionPermission(safe=True)),
        )
        assert result.decision is DeterministicDecision.UNDECIDED


# ═══════════════════════════════════════════════════════════════════════
# Fail-closed: exceptions → UNDECIDED (never ALLOW)
# ═══════════════════════════════════════════════════════════════════════

class TestFailClosedExceptionHandling:

    def test_exception_yields_undecided_not_allow(self, monkeypatch):
        """If a checker raises, DG must fall back to UNDECIDED so the
        AI path still runs.  It must NOT swallow the error as an
        implicit ALLOW.
        """
        dg = DeterministicGuardian()

        def raise_boom(*args, **kwargs):
            raise RuntimeError("boom")

        from intentframe_components.guardian import deterministic as dgmod
        monkeypatch.setattr(
            dgmod,
            "CONSTRAINT_CHECKERS",
            {TerminalConstraints: type("Bad", (), {"check": raise_boom})()},
        )

        constraints = TerminalConstraints(blocked_patterns=["sudo"])
        perm = ActionPermission(safe=False, constraints=constraints)
        result = dg.decide(
            _intent(ActionType.RUN_COMMAND, target="ls"),
            _user(RUN_COMMAND=perm),
            command_intel=_intel("capability:read_only:filesystem_list"),
        )
        assert result.decision is DeterministicDecision.UNDECIDED
        assert result.matched_gate == "exception"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
