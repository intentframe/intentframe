"""
Tests for the multi-layer terminal command blocklist.

Each component independently knows what's dangerous, in its own way:

0. command_shield at Runtime — pre-pipeline gate (CATASTROPHIC/NEEDS_REVIEW/SAFE)
1. Policy Registry — system-level floor (user can only append)
2. Analysis Engine — own catastrophic recognition (deterministic report, no AI)
3. Terminal bundle — ``enforce_constraints`` (deterministic constraint enforcement)
4. Executor/Adapter — command_shield.quick_check() safety floor (non-negotiable)
5. command_shield module — standalone deterministic command classification engine

See also: tests/test_pipeline_shield.py for runtime-level (Layer 0) tests.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from intentframe_native_bundles.actions.terminal.constraints import TerminalConstraints
from policy_registry.models import ActionPermission, UserPolicy
from policy_registry.registry import PolicyRegistry, SYSTEM_TERMINAL_BLOCKED_PATTERNS
from intentframe_native_bundles.actions.terminal.ae_fast_path import (
    CATASTROPHIC_COMMAND_PATTERNS,
    try_catastrophic_report,
)
from intentframe_native_bundles.actions.terminal.bundle import TerminalActionBundle
from intentframe_native_bundles.actions.terminal.evidence import COMMAND_INTEL_KEY, CommandIntel
from intentframe_core.enums import RiskLevel, Reversibility
from intentframe_core.types import IntentFrame
from intentframe_bundle_sdk.types import (
    ActionPermission as SdkActionPermission,
    BundleContext,
    PhaseDecision,
)
from action_registry.types import ActionType
from executor.platforms.macos.adapters.terminal import TerminalAdapter
from command_shield import quick_check
from command_shield.patterns import COMPILED_PATTERNS


def _run(coro):
    return asyncio.run(coro)


def _make_intent(command: str) -> MagicMock:
    """Minimal IntentFrame mock with command in data."""
    intent = MagicMock()
    intent.target = ""
    intent.data = {"command": command}
    intent.action = ActionType.RUN_COMMAND
    intent.agent_id = "test"
    intent.agent_type = "test"
    intent.task_description = "test"
    intent.reason = "test"
    return intent


_TERMINAL_BUNDLE = TerminalActionBundle()


def _run_command_intent(command: str) -> IntentFrame:
    return IntentFrame(
        action=ActionType.RUN_COMMAND,
        target=command,
        data={"command": command},
        reason="test",
        agent_id="test",
    )


def _enforce_terminal(
    command: str,
    constraints: TerminalConstraints,
    *,
    command_intel: CommandIntel | None = None,
) -> tuple[bool, str]:
    intent = _run_command_intent(command)
    ctx = BundleContext(intent=intent.model_copy(deep=True))
    if command_intel is not None:
        ctx.evidence[COMMAND_INTEL_KEY] = command_intel
    outcome = _TERMINAL_BUNDLE.enforce_constraints(
        intent,
        SdkActionPermission(
            safe=False,
            constraints=constraints.model_dump(mode="python"),
        ),
        ctx,
    )
    if outcome.decision is PhaseDecision.BLOCK:
        return False, outcome.reason
    return True, ""


def _describe_terminal(constraints: TerminalConstraints) -> str:
    return (
        _TERMINAL_BUNDLE.describe_constraints(
            SdkActionPermission(
                safe=False,
                constraints=constraints.model_dump(mode="python"),
            )
        )
        or ""
    )


# ═════════════════════════════════════════════════════════════════════════
# LAYER 1: Policy Registry — system-level floor
# ═════════════════════════════════════════════════════════════════════════

class TestPolicyRegistryFloor:
    """System defaults are merged on read. Users can append, not remove."""

    def _make_policy(self, blocked_patterns=None, allowed_commands=None):
        constraints = None
        if blocked_patterns is not None or allowed_commands is not None:
            constraints = TerminalConstraints(
                blocked_patterns=blocked_patterns or [],
                allowed_commands=allowed_commands or [],
            ).model_dump(mode="python")
        return UserPolicy(
            user_id="test",
            agent_id="terminal-test",
            allowed_actions={
                "RUN_COMMAND": ActionPermission(safe=False, constraints=constraints),
            },
        )

    @staticmethod
    def _terminal(perm: ActionPermission) -> TerminalConstraints:
        return TerminalConstraints.model_validate(perm.constraints)

    def test_system_patterns_merged_when_user_has_none(self):
        """RUN_COMMAND with no constraints gets system floor."""
        registry = PolicyRegistry()
        policy = UserPolicy(
            user_id="test",
            agent_id="terminal-test",
            allowed_actions={"RUN_COMMAND": ActionPermission(safe=False)},
        )
        registry.set_user_policy(policy)
        resolved = _run(registry.get_user_policy_resolved("test", "terminal-test"))

        perm = resolved.allowed_actions["RUN_COMMAND"]
        constraints = self._terminal(perm)
        for pattern in SYSTEM_TERMINAL_BLOCKED_PATTERNS:
            assert pattern in constraints.blocked_patterns

    def test_system_patterns_merged_with_user_patterns(self):
        """User's custom patterns are preserved alongside system floor."""
        registry = PolicyRegistry()
        registry.set_user_policy(self._make_policy(
            blocked_patterns=["curl", "wget"],
        ))
        resolved = _run(registry.get_user_policy_resolved("test", "terminal-test"))

        patterns = self._terminal(resolved.allowed_actions["RUN_COMMAND"]).blocked_patterns
        for sys_pattern in SYSTEM_TERMINAL_BLOCKED_PATTERNS:
            assert sys_pattern in patterns
        assert "curl" in patterns
        assert "wget" in patterns

    def test_user_cannot_remove_system_patterns(self):
        """Even if user sets empty blocked_patterns, system floor is merged back."""
        registry = PolicyRegistry()
        registry.set_user_policy(self._make_policy(blocked_patterns=[]))
        resolved = _run(registry.get_user_policy_resolved("test", "terminal-test"))

        patterns = self._terminal(resolved.allowed_actions["RUN_COMMAND"]).blocked_patterns
        for sys_pattern in SYSTEM_TERMINAL_BLOCKED_PATTERNS:
            assert sys_pattern in patterns

    def test_allowed_commands_preserved(self):
        """System floor merge doesn't clobber user's allowed_commands."""
        registry = PolicyRegistry()
        registry.set_user_policy(self._make_policy(
            blocked_patterns=[],
            allowed_commands=["ls *", "pwd"],
        ))
        resolved = _run(registry.get_user_policy_resolved("test", "terminal-test"))

        constraints = self._terminal(resolved.allowed_actions["RUN_COMMAND"])
        assert "ls *" in constraints.allowed_commands
        assert "pwd" in constraints.allowed_commands

    def test_no_duplicates_when_user_includes_system_pattern(self):
        """If user already has a system pattern, it's not duplicated."""
        registry = PolicyRegistry()
        registry.set_user_policy(self._make_policy(
            blocked_patterns=["sudo", "custom_pattern"],
        ))
        resolved = _run(registry.get_user_policy_resolved("test", "terminal-test"))

        patterns = self._terminal(resolved.allowed_actions["RUN_COMMAND"]).blocked_patterns
        assert patterns.count("sudo") == 1

    def test_system_floor_constant_not_empty(self):
        assert len(SYSTEM_TERMINAL_BLOCKED_PATTERNS) >= 6


# ═════════════════════════════════════════════════════════════════════════
# Terminal bundle — catastrophic pattern helpers (legacy AE backup)
# ═════════════════════════════════════════════════════════════════════════

class TestTerminalCatastrophicPatterns:
    """Catastrophic substring patterns live in the terminal bundle."""

    def test_sudo_returns_critical(self):
        report = try_catastrophic_report(_make_intent("sudo reboot"))
        assert report is not None
        assert report.risk_factors["overall"] == RiskLevel.CRITICAL
        assert report.reversibility == Reversibility.IRREVERSIBLE
        assert report.confidence == 1.0

    def test_rm_rf_root_returns_critical(self):
        report = try_catastrophic_report(_make_intent("rm -rf /"))
        assert report is not None
        assert report.risk_factors["overall"] == RiskLevel.CRITICAL

    def test_mkfs_returns_critical(self):
        report = try_catastrophic_report(_make_intent("mkfs.ext4 /dev/sda"))
        assert report is not None
        assert "format" in report.actual_behaviors[0]["actual_behavior"].lower()

    def test_dd_returns_critical(self):
        report = try_catastrophic_report(_make_intent("dd if=/dev/zero of=/dev/sda"))
        assert report is not None

    def test_dev_write_returns_critical(self):
        report = try_catastrophic_report(_make_intent("echo x > /dev/sda"))
        assert report is not None

    def test_chmod_777_returns_critical(self):
        report = try_catastrophic_report(_make_intent("chmod 777 /etc/passwd"))
        assert report is not None

    def test_safe_command_returns_none(self):
        report = try_catastrophic_report(_make_intent("echo hello"))
        assert report is None

    def test_non_run_command_returns_none(self):
        intent = MagicMock()
        intent.action = ActionType.READ_FILE
        intent.target = "/etc/passwd"
        intent.data = {}
        report = try_catastrophic_report(intent)
        assert report is None

    def test_pattern_list_not_empty(self):
        assert len(CATASTROPHIC_COMMAND_PATTERNS) >= 6


# ═════════════════════════════════════════════════════════════════════════
# LAYER 3: Terminal bundle — enforce_constraints + TerminalConstraints
# ═════════════════════════════════════════════════════════════════════════

class TestTerminalBundleBlocklist:
    """TerminalActionBundle.enforce_constraints applies blocked_patterns."""

    default_constraints = TerminalConstraints(
        blocked_patterns=["sudo", "rm -rf /", "mkfs", "dd if=", "> /dev/", "chmod 777"],
    )

    def test_blocks_sudo(self):
        ok, reason = _enforce_terminal("sudo apt install foo", self.default_constraints)
        assert not ok
        assert "sudo" in reason

    def test_blocks_rm_rf_root(self):
        ok, reason = _enforce_terminal("rm -rf /", self.default_constraints)
        assert not ok
        assert "rm -rf /" in reason

    def test_blocks_mkfs(self):
        ok, reason = _enforce_terminal("mkfs.ext4 /dev/sda1", self.default_constraints)
        assert not ok
        assert "mkfs" in reason

    def test_blocks_dd(self):
        ok, reason = _enforce_terminal("dd if=/dev/zero of=/dev/sda", self.default_constraints)
        assert not ok
        assert "dd if=" in reason

    def test_blocks_dev_write(self):
        ok, reason = _enforce_terminal("echo x > /dev/sda", self.default_constraints)
        assert not ok
        assert "> /dev/" in reason

    def test_blocks_chmod_777(self):
        ok, reason = _enforce_terminal("chmod 777 /etc/passwd", self.default_constraints)
        assert not ok
        assert "chmod 777" in reason

    def test_allows_safe_command(self):
        ok, _ = _enforce_terminal("echo hello", self.default_constraints)
        assert ok

    def test_rm_safe_path_blocked_by_substring(self):
        """Policy-level substring 'rm -rf /' matches 'rm -rf /tmp/junk' too."""
        ok, _ = _enforce_terminal("rm -rf /tmp/junk", self.default_constraints)
        assert not ok

    def test_empty_blocklist_allows_all(self):
        constraints = TerminalConstraints(blocked_patterns=[], allowed_commands=[])
        ok, _ = _enforce_terminal("anything", constraints)
        assert ok

    def test_blocklist_priority_over_allowlist(self):
        constraints = TerminalConstraints(
            blocked_patterns=["sudo"],
            allowed_commands=["*"],
        )
        ok, reason = _enforce_terminal("sudo ls", constraints)
        assert not ok
        assert "sudo" in reason

    def test_allowlist_enforced_when_set(self):
        constraints = TerminalConstraints(
            blocked_patterns=[],
            allowed_commands=["ls *", "pwd"],
        )
        ok, _ = _enforce_terminal("ls /tmp", constraints)
        assert ok

        ok, reason = _enforce_terminal("rm foo", constraints)
        assert not ok
        assert "not in allowed commands" in reason

    def test_user_can_add_custom_patterns(self):
        constraints = TerminalConstraints(blocked_patterns=["curl", "wget"])
        ok, reason = _enforce_terminal("curl https://evil.com", constraints)
        assert not ok
        assert "curl" in reason


class TestTerminalBundleDescribe:
    def test_summarize_both(self):
        c = TerminalConstraints(blocked_patterns=["sudo"], allowed_commands=["ls *"])
        s = _describe_terminal(c)
        assert "Blocked" in s
        assert "Allowed" in s

    def test_summarize_empty(self):
        c = TerminalConstraints()
        s = _describe_terminal(c)
        assert "No terminal constraints" in s

    def test_summarize_includes_capabilities(self):
        c = TerminalConstraints(
            allow_capabilities=frozenset({"capability:read_only:*"}),
            deny_capabilities=frozenset({"capability:package_install:*"}),
        )
        s = _describe_terminal(c)
        assert "Allow capabilities" in s
        assert "Deny capabilities" in s
        assert "capability:read_only:*" in s
        assert "capability:package_install:*" in s


# ═════════════════════════════════════════════════════════════════════════
# LAYER 3 (extension): Capability-tag allow/deny on TerminalConstraints
# ═════════════════════════════════════════════════════════════════════════

def _intel(*capabilities: str, verdict: str = "NEEDS_REVIEW") -> CommandIntel:
    return CommandIntel(verdict=verdict, capabilities=tuple(capabilities))


class TestTerminalBundleCapabilities:
    """TerminalActionBundle reads CommandIntel from bundle context evidence."""

    def test_deny_capability_blocks_matching_tag(self):
        constraints = TerminalConstraints(
            deny_capabilities=frozenset({"capability:package_install:*"}),
        )
        ok, reason = _enforce_terminal(
            "pip install requests",
            constraints,
            command_intel=_intel("capability:package_install:pip"),
        )
        assert not ok
        assert "capability:package_install:pip" in reason
        assert "denied" in reason.lower()

    def test_deny_capability_ignores_unrelated_tag(self):
        constraints = TerminalConstraints(
            deny_capabilities=frozenset({"capability:package_install:*"}),
        )
        ok, _ = _enforce_terminal(
            "ls -la",
            constraints,
            command_intel=_intel("capability:read_only:file"),
        )
        assert ok

    def test_deny_capability_without_command_intel_is_no_op(self):
        constraints = TerminalConstraints(
            deny_capabilities=frozenset({"capability:package_install:*"}),
        )
        ok, _ = _enforce_terminal("pip install requests", constraints)
        assert ok

    def test_allow_capability_requires_every_tag_covered(self):
        constraints = TerminalConstraints(
            allow_capabilities=frozenset({"capability:read_only:*"}),
        )
        ok, reason = _enforce_terminal(
            "some-cmd",
            constraints,
            command_intel=_intel(
                "capability:read_only:file",
                "capability:network_bind",
            ),
        )
        assert not ok
        assert "capability:network_bind" in reason

    def test_allow_capability_passes_when_all_covered(self):
        constraints = TerminalConstraints(
            allow_capabilities=frozenset({
                "capability:read_only:*",
                "capability:package_install:*",
            }),
        )
        ok, _ = _enforce_terminal(
            "pip install foo",
            constraints,
            command_intel=_intel(
                "capability:read_only:file",
                "capability:package_install:pip",
            ),
        )
        assert ok

    def test_allow_capability_with_no_intel_does_not_block(self):
        constraints = TerminalConstraints(
            allow_capabilities=frozenset({"capability:read_only:*"}),
        )
        ok, _ = _enforce_terminal("echo hi", constraints)
        assert ok

    def test_blocklist_still_beats_capability_allow(self):
        constraints = TerminalConstraints(
            blocked_patterns=["sudo"],
            allow_capabilities=frozenset({"capability:*"}),
        )
        ok, reason = _enforce_terminal(
            "sudo ls",
            constraints,
            command_intel=_intel("capability:read_only:file"),
        )
        assert not ok
        assert "sudo" in reason

    def test_deny_capability_beats_allowlist_glob(self):
        constraints = TerminalConstraints(
            allowed_commands=["pip *"],
            deny_capabilities=frozenset({"capability:package_install:*"}),
        )
        ok, reason = _enforce_terminal(
            "pip install requests",
            constraints,
            command_intel=_intel("capability:package_install:pip"),
        )
        assert not ok
        assert "package_install" in reason

    def test_empty_capability_sets_do_not_affect_blocklist_behaviour(self):
        constraints = TerminalConstraints(
            blocked_patterns=["sudo"],
            allowed_commands=["ls *"],
        )
        ok, _ = _enforce_terminal(
            "ls /tmp",
            constraints,
            command_intel=_intel("capability:read_only:file"),
        )
        assert ok


# ═════════════════════════════════════════════════════════════════════════
# LAYER 4: Adapter — hardcoded regex safety floor
# ═════════════════════════════════════════════════════════════════════════

class TestAdapterCommandShieldFloor:
    """command_shield.quick_check() in the adapter is a non-negotiable last resort."""

    adapter = TerminalAdapter()

    def test_blocks_sudo(self):
        r = _run(self.adapter.execute("RUN_COMMAND", {"command": "sudo reboot"}))
        assert not r.success
        assert "catastrophic" in r.error.lower()

    def test_blocks_rm_rf_root(self):
        r = _run(self.adapter.execute("RUN_COMMAND", {"command": "rm -rf /"}))
        assert not r.success
        assert "catastrophic" in r.error.lower()

    def test_blocks_mkfs(self):
        r = _run(self.adapter.execute("RUN_COMMAND", {"command": "mkfs.ext4 /dev/sda1"}))
        assert not r.success
        assert "catastrophic" in r.error.lower()

    def test_blocks_dd(self):
        r = _run(self.adapter.execute("RUN_COMMAND", {"command": "dd if=/dev/zero of=/dev/sda"}))
        assert not r.success
        assert "catastrophic" in r.error.lower()

    def test_blocks_dev_write(self):
        r = _run(self.adapter.execute("RUN_COMMAND", {"command": "echo x > /dev/sda"}))
        assert not r.success
        assert "catastrophic" in r.error.lower()

    def test_blocks_chmod_777(self):
        r = _run(self.adapter.execute("RUN_COMMAND", {"command": "chmod 777 /etc/passwd"}))
        assert not r.success
        assert "catastrophic" in r.error.lower()

    def test_blocked_result_shape(self):
        """Blocked commands return a well-formed ExecutionResult with no data."""
        r = _run(self.adapter.execute("RUN_COMMAND", {"command": "sudo reboot"}))
        assert not r.success
        assert r.error is not None
        assert r.data is None

    def test_allows_safe_command(self):
        r = _run(self.adapter.execute("RUN_COMMAND", {"command": "echo hello"}))
        assert r.success
        assert r.data["stdout"].strip() == "hello"

    def test_allows_rm_safe_path(self):
        r = _run(self.adapter.execute("RUN_COMMAND", {"command": "rm -rf /tmp/__intentframe_nonexistent__"}))
        assert r.error is None or "catastrophic" not in r.error.lower()

    def test_allows_dev_null_redirect(self):
        r = _run(self.adapter.execute("RUN_COMMAND", {"command": "echo hi 2>/dev/null"}))
        assert r.success

    def test_command_shield_patterns_not_empty(self):
        assert len(COMPILED_PATTERNS) >= 50


# ═════════════════════════════════════════════════════════════════════════
# Independence — each component has its own patterns
# ═════════════════════════════════════════════════════════════════════════

class TestComponentIndependence:
    """Each component maintains its own pattern knowledge independently."""

    def test_all_layers_catch_sudo(self):
        """All layers independently catch 'sudo'."""
        # Policy Registry floor
        assert "sudo" in SYSTEM_TERMINAL_BLOCKED_PATTERNS

        # Terminal bundle catastrophic patterns
        from intentframe_native_bundles.actions.terminal.ae_fast_path import CATASTROPHIC_COMMAND_PATTERNS
        assert "sudo" in CATASTROPHIC_COMMAND_PATTERNS

        # Terminal bundle constraint enforcement
        constraints = TerminalConstraints(blocked_patterns=list(SYSTEM_TERMINAL_BLOCKED_PATTERNS))
        ok, _ = _enforce_terminal("sudo ls", constraints)
        assert not ok

        # Adapter (via command_shield.quick_check)
        adapter = TerminalAdapter()
        r = _run(adapter.execute("RUN_COMMAND", {"command": "sudo ls"}))
        assert not r.success

        # command_shield standalone
        report = quick_check("sudo ls")
        assert report.is_catastrophic

    def test_each_layer_covers_original_six_patterns(self):
        """Policy registry, terminal bundle, and command_shield all know the original six."""
        from intentframe_native_bundles.actions.terminal.ae_fast_path import CATASTROPHIC_COMMAND_PATTERNS

        expected = {"sudo", "rm -rf /", "mkfs", "dd if=", "> /dev/", "chmod 777"}

        assert expected <= set(SYSTEM_TERMINAL_BLOCKED_PATTERNS)
        assert expected <= set(CATASTROPHIC_COMMAND_PATTERNS.keys())
        # command_shield covers far more than 6 patterns
        assert len(COMPILED_PATTERNS) >= len(expected)


# ═════════════════════════════════════════════════════════════════════════
# Edge cases
# ═════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    adapter = TerminalAdapter()

    def test_empty_command(self):
        r = _run(self.adapter.execute("RUN_COMMAND", {"command": ""}))
        assert not r.success
        assert "No command" in r.error

    def test_no_command_key(self):
        r = _run(self.adapter.execute("RUN_COMMAND", {}))
        assert not r.success
        assert "No command" in r.error

    def test_wrong_action(self):
        r = _run(self.adapter.execute("SEND_EMAIL", {"command": "echo hi"}))
        assert not r.success
        assert "Unknown action" in r.error

    def test_pattern_in_middle_of_command(self):
        """Patterns match anywhere in the command string."""
        r = _run(self.adapter.execute("RUN_COMMAND", {"command": "echo hi && sudo whoami"}))
        assert not r.success
        assert "catastrophic" in r.error.lower()

    def test_constraints_model_allows_empty(self):
        c = TerminalConstraints()
        assert c.blocked_patterns == []
        assert c.allowed_commands == []

    def test_constraints_model_frozen(self):
        c = TerminalConstraints(blocked_patterns=["sudo"])
        with pytest.raises(Exception):
            c.blocked_patterns = ["other"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
