"""Unit tests for DeterministicGuardian (pre-AE deterministic pass).

Covers the rules of the pre-AE pass:

  1. Permission check          → BLOCK / passthrough
  2. Constraint check          → BLOCK / passthrough
  2.5 Domain module check      → BLOCK / passthrough
  3. WRITE_FILE sensitive path → BLOCK on known-dangerous destinations
  4. Passive-read ALLOW        → ALLOW on safe passive reads
  5. RUN_COMMAND read-only     → ALLOW on read-only capability tags
  6. Default                   → UNDECIDED (AE + AIGuardian handle it)

WRITE_FILE has NO deterministic ALLOW gate: every mutating write pays
LLM review unless rule 3 fires first (hard BLOCK).  Payload-content
heuristics (extension / language sniff) are not trusted as evidence of
benignness under an adversarial agent.

Also covers:

  - Fail-closed exception path (BLOCK + matched_gate=hook_crash, never ALLOW/AI)
  - deny_capabilities blocks the read-only fast-path
  - Incompatible capability tags disqualify the read-only fast-path
  - Code-intel findings / edge signals disqualify the fast-path
  - network_probe tags disqualify the fast-path even with read-only
"""

from __future__ import annotations

import pytest

from action_registry.types import ActionType
from intentframe_native_bundles.actions.terminal.evidence import CommandIntel
from intentframe_native_bundles import passive_read_action_ids
from intentframe_native_bundles.actions.terminal._read_only import READ_ONLY_INCOMPATIBLE
from intentframe_components.guardian.deterministic import (
    DeterministicDecision,
    DeterministicGuardian,
    DeterministicResult,
)
from intentframe_core.types import IntentFrame, UserContext
from tests.deterministic_accuracy._helpers import decide_dg_sync, run_dg_with_intel
from intentframe_native_bundles.actions.terminal.constraints import TerminalConstraints
from policy_registry.models import ActionPermission


# ───────────────────────────── helpers ─────────────────────────────

def _intent(action: ActionType, target: str = "", **data) -> IntentFrame:
    payload = dict(data) if data else {}
    if (
        action == ActionType.RUN_COMMAND
        and target
        and "command" not in payload
    ):
        payload["command"] = target
    return IntentFrame(
        action=action,
        target=target,
        data=payload or None,
        reason="test",
        agent_id="test_agent",
    )


def _user(**actions: ActionPermission) -> UserContext:
    return UserContext(user_id="tester", allowed_actions=dict(actions))

def _perm(constraints, *, safe: bool = False) -> ActionPermission:
    if hasattr(constraints, "model_dump"):
        constraints = constraints.model_dump(mode="python")
    return ActionPermission(safe=safe, constraints=constraints)


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
        result = decide_dg_sync(self.dg,
            _intent(ActionType.READ_FILE, "/tmp/x"),
            _user(),  # nothing allowed
        )
        assert result.decision is DeterministicDecision.BLOCK
        assert result.matched_gate == "permission"
        assert "not permitted" in result.reason.lower()

    def test_action_in_allowed_actions_passes_gate(self):
        # safe=False so passive-read ALLOW doesn't fire
        result = decide_dg_sync(self.dg,
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
        result = run_dg_with_intel(
            "pip install foo",
            _user(RUN_COMMAND=_perm(constraints)),
            _intel("capability:package_install:pip"),
            self.dg,
        )
        assert result.decision is DeterministicDecision.BLOCK
        assert result.matched_gate == "constraint"
        assert "package_install" in result.reason

    def test_blocked_pattern_blocks_before_ae(self):
        constraints = TerminalConstraints(blocked_patterns=["sudo"])
        result = run_dg_with_intel(
            "sudo ls",
            _user(RUN_COMMAND=_perm(constraints)),
            _intel(),
            self.dg,
        )
        assert result.decision is DeterministicDecision.BLOCK
        assert result.matched_gate == "constraint"
        assert "sudo" in result.reason

    def test_no_constraints_passes_gate(self):
        result = run_dg_with_intel(
            "echo hi && echo bye",
            _user(RUN_COMMAND=ActionPermission(safe=False)),
            _intel(verdict="SAFE"),
            self.dg,
        )
        assert result.decision is DeterministicDecision.UNDECIDED


# ═══════════════════════════════════════════════════════════════════════
# STEP 4 — Passive-read ALLOW short-circuit
# ═══════════════════════════════════════════════════════════════════════

class TestPassiveReadFastPath:
    dg = DeterministicGuardian()

    def test_passive_read_safe_allows(self):
        result = decide_dg_sync(self.dg,
            _intent(ActionType.READ_FILE, "/tmp/x"),
            _user(READ_FILE=ActionPermission(safe=True)),
        )
        assert result.decision is DeterministicDecision.ALLOW
        assert result.matched_gate == "passive_read"

    def test_passive_read_unsafe_falls_through(self):
        """safe=False means the user asked for AI review — DG must
        not ALLOW just because the action is conceptually passive."""
        result = decide_dg_sync(self.dg,
            _intent(ActionType.READ_FILE, "/tmp/x"),
            _user(READ_FILE=ActionPermission(safe=False)),
        )
        assert result.decision is DeterministicDecision.UNDECIDED

    def test_non_passive_safe_action_falls_through(self):
        """SEND_EMAIL marked safe is NOT passive — DG falls through
        so AE can still inspect the prompt content."""
        result = decide_dg_sync(self.dg,
            _intent(ActionType.SEND_EMAIL, target="x@y.com"),
            _user(SEND_EMAIL=ActionPermission(safe=True)),
        )
        assert result.decision is DeterministicDecision.UNDECIDED

    def test_passive_read_set_is_canonical(self):
        """Passive read ALLOW is declared per owning bundle and enforced by SDK."""
        assert ActionType.READ_FILE.value in passive_read_action_ids()


# ═══════════════════════════════════════════════════════════════════════
# STEP 5 — RUN_COMMAND read-only ALLOW short-circuit
# ═══════════════════════════════════════════════════════════════════════

class TestReadOnlyFastPath:
    dg = DeterministicGuardian()

    perm = ActionPermission(safe=False)

    def _decide(self, command: str, intel: CommandIntel) -> DeterministicResult:
        return run_dg_with_intel(
            command,
            _user(RUN_COMMAND=self.perm),
            intel,
            self.dg,
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

    @pytest.mark.parametrize("bad_cap", sorted(READ_ONLY_INCOMPATIBLE))
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
        perm = _perm(constraints)
        result = run_dg_with_intel(
            "ls",
            _user(RUN_COMMAND=perm),
            _intel("capability:read_only:filesystem_list"),
            self.dg,
        )
        # TerminalChecker (Step 2) catches this FIRST — so it's a
        # constraint BLOCK, not a fast-path miss.  Either way it's
        # not an ALLOW.
        assert result.decision is DeterministicDecision.BLOCK

    def test_empty_command_skips_read_only_allow(self):
        """Without a command string, shield produces no intel and read-only cannot ALLOW."""
        result = decide_dg_sync(self.dg,
            _intent(ActionType.RUN_COMMAND, target=""),
            _user(RUN_COMMAND=self.perm),
        )
        assert result.decision is DeterministicDecision.UNDECIDED


# ═══════════════════════════════════════════════════════════════════════
# STEP 3 — WRITE_FILE sensitive destination BLOCK
# ═══════════════════════════════════════════════════════════════════════
# DG makes one deterministic decision about WRITE_FILE: BLOCK when the
# virtual target is a sensitive system location (shell startup files,
# credential stores, privilege config, persistence daemons, Python
# runtime hooks).  Mirrors the VFS floor at
# resource_registry.floor.DENY_WRITE_PREFIXES which catches the same
# families on the canonicalized real path at I/O time — DG fires on
# the virtual path, pre-AE, so agents don't spend an LLM round-trip
# on a write we will refuse at I/O anyway.
#
# Payload heuristics (extension / sniffed language) do NOT qualify a
# WRITE_FILE for deterministic ALLOW: every write goes UNDECIDED and
# pays the LLM round-trip unless the destination trips the block above.

class TestWriteFileSensitivePathBlock:
    dg = DeterministicGuardian()

    perm_safe = ActionPermission(safe=True)

    def _decide(self, target: str, *, safe: bool = True) -> DeterministicResult:
        # ``path`` in data is the executable contract; target is display-only.
        return decide_dg_sync(self.dg,
            _intent(ActionType.WRITE_FILE, target, path=target),
            _user(WRITE_FILE=self.perm_safe if safe else ActionPermission(safe=False)),
        )

    # ── BLOCK path ──────────────────────────────────────────────

    @pytest.mark.parametrize("target", [
        "/home/.zshrc",
        "/home/.bashrc",
        "/home/.bash_profile",
        "/home/.profile",
        "/home/.zprofile",
        "/home/.zshenv",
        "/home/library/launchagents/com.example.plist",
        "/home/.ssh/authorized_keys",
        "/home/.ssh/config",
        "/home/.gnupg/gpg.conf",
        "/home/.git/hooks/pre-commit",
        "/etc/sudoers",
        "/etc/sudoers.d/00-example",
        "/home/project/site-packages/evil.pth",
        "/home/project/site-packages/sitecustomize.py",
        "/home/project/site-packages/usercustomize.py",
    ])
    def test_sensitive_destination_blocks(self, target):
        """Every sensitive system location is a hard BLOCK."""
        result = self._decide(target)
        assert result.decision is DeterministicDecision.BLOCK
        assert result.matched_gate == "write_file_sensitive_path"
        assert target in result.reason

    def test_sensitive_destination_blocks_regardless_of_permission_safe(self):
        """``permission.safe`` cannot downgrade a sensitive-path BLOCK."""
        result = self._decide("/home/.zshrc", safe=False)
        assert result.decision is DeterministicDecision.BLOCK
        assert result.matched_gate == "write_file_sensitive_path"

    def test_case_insensitive_match(self):
        """Fragment match is case-insensitive — catches mixed-case macOS
        paths like Library/LaunchAgents."""
        result = self._decide(
            "/Users/alice/Library/LaunchAgents/com.example.plist"
        )
        assert result.decision is DeterministicDecision.BLOCK

    # ── no ALLOW fast-path for WRITE_FILE ───────────────────────

    @pytest.mark.parametrize("target", [
        "/home/documents/notes.md",
        "/home/documents/data.json",
        "/home/documents/config.yaml",
        "/tmp/output.txt",
        "/home/documents/README",
        "/home/documents/file.unknown",
    ])
    def test_benign_writes_fall_through_to_undecided(self, target):
        """Ordinary document / data writes go UNDECIDED — AE + Guardian
        still run.  No amount of "looks boring" short-circuits the LLM."""
        result = self._decide(target)
        assert result.decision is DeterministicDecision.UNDECIDED

    def test_code_payload_with_benign_destination_undecided(self):
        """Only destination drives the DG BLOCK; payload type does not.
        A Python file on a non-sensitive path falls through to AE."""
        result = decide_dg_sync(self.dg,
            _intent(ActionType.WRITE_FILE, "/home/documents/notes.md"),
            _user(WRITE_FILE=self.perm_safe),
        )
        assert result.decision is DeterministicDecision.UNDECIDED


# ═══════════════════════════════════════════════════════════════════════
# STEP 3b — HOST_FILE mutation floor (real-path deny prefixes)
# ═══════════════════════════════════════════════════════════════════════
# DG enforces ``resource_registry.floor.DENY_WRITE_PREFIXES`` on
# ``WRITE_HOST_FILE`` / ``DELETE_HOST_FILE`` before the LLM round-trip.
# Unlike the virtual-path ``write_file_sensitive_path`` gate (which works
# on the raw virtual target), the host-file gates canonicalize via
# :func:`resource_registry.floor.canonicalize_real_path` first, then call
# :func:`match_deny_prefix`.  Inputs are therefore picked from the actual
# expanded floor tuple so the test follows the loader, not a static
# whitelist.

class TestHostFileFloorBlock:
    dg = DeterministicGuardian()

    def _run(self, action: ActionType, target: str):
        # ``path`` in data is the executable contract; target is display-only.
        # DELETE_HOST_FILE is in the deletion domain, so ``path`` also satisfies
        # the DeletionIntentData schema gate.
        return decide_dg_sync(self.dg,
            _intent(action, target, path=target),
            _user(**{action.value: ActionPermission(safe=False)}),
        )

    def test_write_host_file_deny_floor_blocks(self):
        # Document the end-to-end flow in one test:
        #   1. ``/etc/sudoers`` is a raw (agent-supplied) real path.
        #   2. ``resource_registry.floor`` canonicalizes every entry in
        #      ``DENY_WRITE_PREFIXES`` at module-load time via
        #      ``os.path.realpath``.  On macOS ``/etc`` is a symlink to
        #      ``/private/etc``, so the stored tuple holds
        #      ``/private/etc/sudoers`` — NOT ``/etc/sudoers``.
        #   3. The DG host-file gate runs the *same* canonicalizer on
        #      ``intent.target`` before calling ``match_deny_prefix``,
        #      so raw ``/etc/sudoers`` resolves to the stored form and
        #      the prefix compare succeeds.
        # Pinning both sides of that flow catches symmetry breaks: if
        # either the floor-load canonicalization or the DG-call
        # canonicalization drifts, the precondition assertion fails
        # loudly with a clear diff instead of a generic "expected BLOCK
        # got UNDECIDED".
        from resource_registry.floor import (
            DENY_WRITE_PREFIXES,
            canonicalize_real_path,
        )
        canonical = canonicalize_real_path("/etc/sudoers")
        assert canonical in DENY_WRITE_PREFIXES or any(
            canonical == p or canonical.startswith(p + "/")
            for p in DENY_WRITE_PREFIXES
        ), (
            f"canonicalized input {canonical!r} is not covered by the "
            f"deny-write floor — DG's BLOCK would be vacuous"
        )
        result = self._run(ActionType.WRITE_HOST_FILE, "/etc/sudoers")
        assert result.decision is DeterministicDecision.BLOCK
        assert result.matched_gate == "write_host_file_floor"

    def test_write_host_file_nested_deny_path_blocks(self):
        # Path under a deny prefix (not the prefix itself).
        result = self._run(
            ActionType.WRITE_HOST_FILE,
            "/etc/sudoers.d/00-malicious",
        )
        assert result.decision is DeterministicDecision.BLOCK
        assert result.matched_gate == "write_host_file_floor"

    def test_delete_host_file_deny_floor_blocks(self):
        result = self._run(
            ActionType.DELETE_HOST_FILE,
            "/etc/sudoers",
        )
        assert result.decision is DeterministicDecision.BLOCK
        assert result.matched_gate == "delete_host_file_floor"

    def test_write_host_file_outside_floor_falls_through(self):
        # Under tmp — never on the floor list.  Still goes UNDECIDED
        # because host-file writes are critical (no deterministic ALLOW
        # outside the floor).
        result = self._run(
            ActionType.WRITE_HOST_FILE,
            "/tmp/intentframe-host-test.txt",
        )
        assert result.decision is DeterministicDecision.UNDECIDED

    def test_delete_host_file_outside_floor_falls_through(self):
        result = self._run(
            ActionType.DELETE_HOST_FILE,
            "/tmp/intentframe-host-test.txt",
        )
        assert result.decision is DeterministicDecision.UNDECIDED

    def test_read_host_file_never_blocked_by_floor(self):
        # The floor is a *write* floor.  Reads under deny prefixes are
        # an exposure risk but not the same destructive hazard; they
        # fall through to AE/AIGuardian for scope review.
        result = decide_dg_sync(self.dg,
            _intent(ActionType.READ_HOST_FILE, "/etc/sudoers"),
            _user(READ_HOST_FILE=ActionPermission(safe=False)),
        )
        assert result.decision is DeterministicDecision.UNDECIDED

    def test_host_file_passive_read_fast_path(self):
        """Host-file reads marked safe take the passive-read ALLOW
        just like virtual-path reads — the _PRE_AE_SAFE_READS set
        already includes READ_HOST_FILE / LIST_HOST_DIRECTORY."""
        for action in (ActionType.READ_HOST_FILE, ActionType.LIST_HOST_DIRECTORY):
            result = decide_dg_sync(self.dg,
                _intent(action, "~/Documents/foo.txt"),
                _user(**{action.value: ActionPermission(safe=True)}),
            )
            assert result.decision is DeterministicDecision.ALLOW
            assert result.matched_gate == "passive_read"


# ═══════════════════════════════════════════════════════════════════════
# Non-passive, non-run-command actions → UNDECIDED
# ═══════════════════════════════════════════════════════════════════════

class TestUndecidedDefault:
    dg = DeterministicGuardian()

    def test_send_email_with_constraints_falls_through(self):
        from intentframe_native_bundles.actions.email.constraints import EmailConstraints
        perm = ActionPermission(
            safe=False,
            constraints=EmailConstraints(allowed_recipients=["a@b.com"]).model_dump(
                mode="python"
            ),
        )
        result = decide_dg_sync(self.dg,
            _intent(ActionType.SEND_EMAIL, target="x", to="a@b.com"),
            _user(SEND_EMAIL=perm),
        )
        assert result.decision is DeterministicDecision.UNDECIDED

    def test_ask_user_safe_does_not_fast_path(self):
        """ASK_USER/GET_CONFIRMATION/SHOW_MESSAGE must always go
        through AE even when marked safe — their prompt content has
        to be inspected for social-engineering / phishing."""
        result = decide_dg_sync(self.dg,
            _intent(ActionType.ASK_USER, target="prompt"),
            _user(ASK_USER=ActionPermission(safe=True)),
        )
        assert result.decision is DeterministicDecision.UNDECIDED


# ═══════════════════════════════════════════════════════════════════════
# Fail-closed: exceptions → BLOCK (never ALLOW, never AI degradation)
# ═══════════════════════════════════════════════════════════════════════

class TestFailClosedExceptionHandling:

    def test_exception_yields_block_not_allow_or_undecided(self, monkeypatch):
        """If a checker raises, DG must BLOCK fail-closed with
        matched_gate=hook_crash and dg_exception set — not fall through
        to the AI path.
        """
        dg = DeterministicGuardian()

        from intentframe_native_bundles.actions.terminal.bundle import TerminalActionBundle
        from intentframe_native_bundles.actions.terminal.constraints import TerminalConstraints

        async def raise_boom(self, intent, action_permission, ctx, *, verbose=False):
            del self, intent, action_permission, ctx, verbose
            raise RuntimeError("boom")

        monkeypatch.setattr(TerminalActionBundle, "enforce_constraints", raise_boom)

        constraints = TerminalConstraints(blocked_patterns=["sudo"])
        perm = _perm(constraints)
        result = run_dg_with_intel(
            "ls",
            _user(RUN_COMMAND=perm),
            _intel("capability:read_only:filesystem_list"),
            dg,
        )
        assert result.decision is DeterministicDecision.BLOCK
        assert result.matched_gate == "hook_crash"
        assert result.dg_exception == "RuntimeError('boom')"
        assert result.decision_path == "hook_crash"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
