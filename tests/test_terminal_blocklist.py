"""
Tests for the multi-layer terminal command blocklist.

Each component independently knows what's dangerous, in its own way:

0. command_shield at Runtime — pre-pipeline gate (CATASTROPHIC/NEEDS_REVIEW/SAFE)
1. Policy Registry — system-level floor (user can only append)
2. Analysis Engine — own catastrophic recognition (deterministic report, no AI)
3. Guardian — TerminalChecker (deterministic constraint enforcement)
4. Executor/Adapter — command_shield.quick_check() safety floor (non-negotiable)
5. command_shield module — standalone deterministic command classification engine

See also: tests/test_pipeline_shield.py for runtime-level (Layer 0) tests.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from policy_registry.constraints.terminal import TerminalConstraints
from policy_registry.models import ActionPermission, UserPolicy
from policy_registry.registry import PolicyRegistry, SYSTEM_TERMINAL_BLOCKED_PATTERNS
from intentframe_components.guardian.checkers.terminal import TerminalChecker
from intentframe_components.analysis.engine import AIAnalysisEngine
from intentframe_core.enums import RiskLevel, Reversibility
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
            )
        return UserPolicy(
            user_id="test",
            allowed_actions={
                "RUN_COMMAND": ActionPermission(safe=False, constraints=constraints),
            },
        )

    def test_system_patterns_merged_when_user_has_none(self):
        """RUN_COMMAND with no constraints gets system floor."""
        registry = PolicyRegistry()
        policy = UserPolicy(
            user_id="test",
            allowed_actions={"RUN_COMMAND": ActionPermission(safe=False)},
        )
        registry.set_user_policy(policy)
        resolved = _run(registry.get_user_policy_resolved("test"))

        perm = resolved.allowed_actions["RUN_COMMAND"]
        assert isinstance(perm.constraints, TerminalConstraints)
        for pattern in SYSTEM_TERMINAL_BLOCKED_PATTERNS:
            assert pattern in perm.constraints.blocked_patterns

    def test_system_patterns_merged_with_user_patterns(self):
        """User's custom patterns are preserved alongside system floor."""
        registry = PolicyRegistry()
        registry.set_user_policy(self._make_policy(
            blocked_patterns=["curl", "wget"],
        ))
        resolved = _run(registry.get_user_policy_resolved("test"))

        patterns = resolved.allowed_actions["RUN_COMMAND"].constraints.blocked_patterns
        for sys_pattern in SYSTEM_TERMINAL_BLOCKED_PATTERNS:
            assert sys_pattern in patterns
        assert "curl" in patterns
        assert "wget" in patterns

    def test_user_cannot_remove_system_patterns(self):
        """Even if user sets empty blocked_patterns, system floor is merged back."""
        registry = PolicyRegistry()
        registry.set_user_policy(self._make_policy(blocked_patterns=[]))
        resolved = _run(registry.get_user_policy_resolved("test"))

        patterns = resolved.allowed_actions["RUN_COMMAND"].constraints.blocked_patterns
        for sys_pattern in SYSTEM_TERMINAL_BLOCKED_PATTERNS:
            assert sys_pattern in patterns

    def test_allowed_commands_preserved(self):
        """System floor merge doesn't clobber user's allowed_commands."""
        registry = PolicyRegistry()
        registry.set_user_policy(self._make_policy(
            blocked_patterns=[],
            allowed_commands=["ls *", "pwd"],
        ))
        resolved = _run(registry.get_user_policy_resolved("test"))

        constraints = resolved.allowed_actions["RUN_COMMAND"].constraints
        assert "ls *" in constraints.allowed_commands
        assert "pwd" in constraints.allowed_commands

    def test_no_duplicates_when_user_includes_system_pattern(self):
        """If user already has a system pattern, it's not duplicated."""
        registry = PolicyRegistry()
        registry.set_user_policy(self._make_policy(
            blocked_patterns=["sudo", "custom_pattern"],
        ))
        resolved = _run(registry.get_user_policy_resolved("test"))

        patterns = resolved.allowed_actions["RUN_COMMAND"].constraints.blocked_patterns
        assert patterns.count("sudo") == 1

    def test_system_floor_constant_not_empty(self):
        assert len(SYSTEM_TERMINAL_BLOCKED_PATTERNS) >= 6


# ═════════════════════════════════════════════════════════════════════════
# LAYER 2: Analysis Engine — own catastrophic command recognition
# ═════════════════════════════════════════════════════════════════════════

class TestAnalysisEngineCatastrophic:
    """AE returns deterministic CRITICAL report for catastrophic commands."""

    engine = AIAnalysisEngine(verbose=False)

    def test_sudo_returns_critical(self):
        report = self.engine._try_catastrophic_report(_make_intent("sudo reboot"))
        assert report is not None
        assert report.risk_factors["overall"] == RiskLevel.CRITICAL
        assert report.reversibility == Reversibility.IRREVERSIBLE
        assert report.confidence == 1.0

    def test_rm_rf_root_returns_critical(self):
        report = self.engine._try_catastrophic_report(_make_intent("rm -rf /"))
        assert report is not None
        assert report.risk_factors["overall"] == RiskLevel.CRITICAL

    def test_mkfs_returns_critical(self):
        report = self.engine._try_catastrophic_report(_make_intent("mkfs.ext4 /dev/sda"))
        assert report is not None
        assert "format" in report.actual_behaviors[0]["actual_behavior"].lower()

    def test_dd_returns_critical(self):
        report = self.engine._try_catastrophic_report(_make_intent("dd if=/dev/zero of=/dev/sda"))
        assert report is not None

    def test_dev_write_returns_critical(self):
        report = self.engine._try_catastrophic_report(_make_intent("echo x > /dev/sda"))
        assert report is not None

    def test_chmod_777_returns_critical(self):
        report = self.engine._try_catastrophic_report(_make_intent("chmod 777 /etc/passwd"))
        assert report is not None

    def test_safe_command_returns_none(self):
        """Safe commands return None — full AI analysis needed."""
        report = self.engine._try_catastrophic_report(_make_intent("echo hello"))
        assert report is None

    def test_non_run_command_returns_none(self):
        """Only RUN_COMMAND triggers catastrophic check."""
        intent = MagicMock()
        intent.action = ActionType.READ_FILE
        intent.target = "/etc/passwd"
        intent.data = {}
        report = self.engine._try_catastrophic_report(intent)
        assert report is None

    def test_pattern_list_not_empty(self):
        assert len(AIAnalysisEngine._CATASTROPHIC_COMMAND_PATTERNS) >= 6


# ═════════════════════════════════════════════════════════════════════════
# LAYER 3: Guardian — TerminalChecker + TerminalConstraints
# ═════════════════════════════════════════════════════════════════════════

class TestTerminalCheckerBlocklist:
    """TerminalChecker enforces blocked_patterns from user policy."""

    checker = TerminalChecker()

    default_constraints = TerminalConstraints(
        blocked_patterns=["sudo", "rm -rf /", "mkfs", "dd if=", "> /dev/", "chmod 777"],
    )

    def test_blocks_sudo(self):
        ok, reason = self.checker.check(_make_intent("sudo apt install foo"), self.default_constraints)
        assert not ok
        assert "sudo" in reason

    def test_blocks_rm_rf_root(self):
        ok, reason = self.checker.check(_make_intent("rm -rf /"), self.default_constraints)
        assert not ok
        assert "rm -rf /" in reason

    def test_blocks_mkfs(self):
        ok, reason = self.checker.check(_make_intent("mkfs.ext4 /dev/sda1"), self.default_constraints)
        assert not ok
        assert "mkfs" in reason

    def test_blocks_dd(self):
        ok, reason = self.checker.check(_make_intent("dd if=/dev/zero of=/dev/sda"), self.default_constraints)
        assert not ok
        assert "dd if=" in reason

    def test_blocks_dev_write(self):
        ok, reason = self.checker.check(_make_intent("echo x > /dev/sda"), self.default_constraints)
        assert not ok
        assert "> /dev/" in reason

    def test_blocks_chmod_777(self):
        ok, reason = self.checker.check(_make_intent("chmod 777 /etc/passwd"), self.default_constraints)
        assert not ok
        assert "chmod 777" in reason

    def test_allows_safe_command(self):
        ok, _ = self.checker.check(_make_intent("echo hello"), self.default_constraints)
        assert ok

    def test_rm_safe_path_blocked_by_substring(self):
        """Policy-level substring 'rm -rf /' matches 'rm -rf /tmp/junk' too.
        This is intentional — broad policy, users can narrow if needed.
        The adapter's regex layer is more precise."""
        ok, _ = self.checker.check(_make_intent("rm -rf /tmp/junk"), self.default_constraints)
        assert not ok

    def test_empty_blocklist_allows_all(self):
        constraints = TerminalConstraints(blocked_patterns=[], allowed_commands=[])
        ok, _ = self.checker.check(_make_intent("anything"), constraints)
        assert ok

    def test_blocklist_priority_over_allowlist(self):
        constraints = TerminalConstraints(
            blocked_patterns=["sudo"],
            allowed_commands=["*"],
        )
        ok, reason = self.checker.check(_make_intent("sudo ls"), constraints)
        assert not ok
        assert "sudo" in reason

    def test_allowlist_enforced_when_set(self):
        constraints = TerminalConstraints(
            blocked_patterns=[],
            allowed_commands=["ls *", "pwd"],
        )
        ok, _ = self.checker.check(_make_intent("ls /tmp"), constraints)
        assert ok

        ok, reason = self.checker.check(_make_intent("rm foo"), constraints)
        assert not ok
        assert "not in allowed commands" in reason

    def test_user_can_add_custom_patterns(self):
        constraints = TerminalConstraints(blocked_patterns=["curl", "wget"])
        ok, reason = self.checker.check(_make_intent("curl https://evil.com"), constraints)
        assert not ok
        assert "curl" in reason


class TestTerminalCheckerSummarize:
    checker = TerminalChecker()

    def test_summarize_both(self):
        c = TerminalConstraints(blocked_patterns=["sudo"], allowed_commands=["ls *"])
        s = self.checker.summarize(c)
        assert "Blocked" in s
        assert "Allowed" in s

    def test_summarize_empty(self):
        c = TerminalConstraints()
        s = self.checker.summarize(c)
        assert "No terminal constraints" in s


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

        # Analysis Engine
        assert "sudo" in AIAnalysisEngine._CATASTROPHIC_COMMAND_PATTERNS

        # Guardian (via TerminalConstraints with system defaults)
        checker = TerminalChecker()
        constraints = TerminalConstraints(blocked_patterns=list(SYSTEM_TERMINAL_BLOCKED_PATTERNS))
        ok, _ = checker.check(_make_intent("sudo ls"), constraints)
        assert not ok

        # Adapter (via command_shield.quick_check)
        adapter = TerminalAdapter()
        r = _run(adapter.execute("RUN_COMMAND", {"command": "sudo ls"}))
        assert not r.success

        # command_shield standalone
        report = quick_check("sudo ls")
        assert report.is_catastrophic

    def test_each_layer_covers_original_six_patterns(self):
        """Policy registry, analysis engine, and command_shield all know the original six."""
        expected = {"sudo", "rm -rf /", "mkfs", "dd if=", "> /dev/", "chmod 777"}

        assert expected <= set(SYSTEM_TERMINAL_BLOCKED_PATTERNS)
        assert expected <= set(AIAnalysisEngine._CATASTROPHIC_COMMAND_PATTERNS.keys())
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
