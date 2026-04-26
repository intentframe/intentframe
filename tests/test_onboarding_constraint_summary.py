"""Unit coverage for `AIOnboardingEngine._summarize_constraints` and
`_summarize_deny_capabilities`.

The summarizer is the seam through which the live `deny_capabilities`
deny set surfaces to the onboarding LLM.  Before this seam was wired,
the LLM only saw `blocked_patterns` + `allowed_commands`; the language
clamp was invisible, and the agent (e.g. Jarvis) generated guardrails
that didn't reflect the python+shell-only restriction.  The downstream
effect was: defense held at Gate 2 (DG denied), but the LLM kept
attempting `node`/`ruby`/etc., wasting tokens and surfacing noisy
"blocked" events instead of polite "outside policy" responses.

These tests pin:

  - `deny_capabilities` IS surfaced in the constraint summary string
  - the summary recognises the python+shell-only shape and emits the
    high-level statement first
  - per-family details enumerate denied interpreters / package
    managers (legible for the LLM without dumping raw capability
    strings)
  - empty deny set → no language-clamp text leaks into the summary
  - `blocked_patterns` and `allowed_commands` continue to be summarised
    alongside `deny_capabilities` (no regression of the existing
    behaviour)
"""

from __future__ import annotations

from intentframe_components.onboarding.engine import AIOnboardingEngine
from policy_registry.constraints.terminal import TerminalConstraints


PYTHON_SHELL_ONLY_DENY = frozenset({
    "capability:script_execution:node",
    "capability:script_execution:ruby",
    "capability:script_execution:perl",
    "capability:script_execution:java",
    "capability:script_execution:go",
    "capability:script_execution:php",
    "capability:script_execution:local_binary",
    "capability:compilation",
    "capability:stdin_exec:node",
    "capability:stdin_exec:ruby",
    "capability:stdin_exec:perl",
    "capability:stdin_exec:php",
    "capability:package_install:npm",
    "capability:package_install:gem",
    "capability:package_install:cargo",
    "capability:package_install:go",
    "capability:package_install:composer",
})


class TestSummarizeDenyCapabilitiesShape:
    def test_python_shell_clamp_emits_headline(self) -> None:
        summary = AIOnboardingEngine._summarize_deny_capabilities(
            PYTHON_SHELL_ONLY_DENY
        )
        assert "language clamp" in summary
        assert "python" in summary.lower() and "shell" in summary.lower()

    def test_enumerates_denied_interpreters(self) -> None:
        summary = AIOnboardingEngine._summarize_deny_capabilities(
            PYTHON_SHELL_ONLY_DENY
        )
        for lang in ("node", "ruby", "perl", "java", "go", "php"):
            assert lang in summary, (
                f"summary {summary!r} should enumerate interpreter {lang!r}"
            )

    def test_enumerates_denied_package_managers(self) -> None:
        summary = AIOnboardingEngine._summarize_deny_capabilities(
            PYTHON_SHELL_ONLY_DENY
        )
        for pkg in ("npm", "gem", "cargo", "composer"):
            assert pkg in summary, (
                f"summary {summary!r} should enumerate package manager {pkg!r}"
            )

    def test_mentions_compilation(self) -> None:
        summary = AIOnboardingEngine._summarize_deny_capabilities(
            PYTHON_SHELL_ONLY_DENY
        )
        assert "compil" in summary.lower()

    def test_mentions_stdin_pipe_shape(self) -> None:
        summary = AIOnboardingEngine._summarize_deny_capabilities(
            PYTHON_SHELL_ONLY_DENY
        )
        assert "stdin" in summary.lower(), (
            "stdin-piped exec is the user-surfaced gap class — the "
            "summary must mention it so the LLM knows `cat foo.js | "
            "node` is denied just as `node app.js` is"
        )


class TestSummarizeDenyCapabilitiesEdgeCases:
    def test_empty_deny_set_returns_count_fallback(self) -> None:
        # Defensive: caller filters this case out (empty deny → no
        # call), but if it does get here the helper must not crash
        # or invent language-clamp text.
        summary = AIOnboardingEngine._summarize_deny_capabilities(frozenset())
        assert "language clamp" not in summary

    def test_only_compilation_does_not_claim_language_clamp(self) -> None:
        # If a profile only denies compilation but not script_execution
        # or package_install, that is NOT the python+shell-only clamp
        # and the headline must not be emitted.
        summary = AIOnboardingEngine._summarize_deny_capabilities(
            frozenset({"capability:compilation"})
        )
        assert "language clamp" not in summary
        assert "compil" in summary.lower()

    def test_unknown_capability_family_does_not_break(self) -> None:
        summary = AIOnboardingEngine._summarize_deny_capabilities(
            frozenset({"capability:future_family:special"})
        )
        # Unknown families fall through to the count fallback rather
        # than crashing with a KeyError.
        assert "denied" in summary.lower() or "configured" in summary.lower()


class TestSummarizeConstraintsIntegration:
    def test_terminal_constraints_summary_includes_deny_capabilities(self) -> None:
        constraints = TerminalConstraints(
            blocked_patterns=("sudo", "rm -rf /"),
            deny_capabilities=PYTHON_SHELL_ONLY_DENY,
        )
        summary = AIOnboardingEngine._summarize_constraints(
            "RUN_COMMAND", constraints
        )
        assert "blocked patterns" in summary
        assert "language clamp" in summary

    def test_terminal_constraints_with_only_blocked_patterns(self) -> None:
        # No deny_capabilities → no language-clamp leak; existing
        # behaviour preserved.
        constraints = TerminalConstraints(
            blocked_patterns=("sudo",),
        )
        summary = AIOnboardingEngine._summarize_constraints(
            "RUN_COMMAND", constraints
        )
        assert "blocked patterns" in summary
        assert "language clamp" not in summary
        assert "deny" not in summary.lower()

    def test_terminal_constraints_with_only_deny_capabilities(self) -> None:
        constraints = TerminalConstraints(
            deny_capabilities=PYTHON_SHELL_ONLY_DENY,
        )
        summary = AIOnboardingEngine._summarize_constraints(
            "RUN_COMMAND", constraints
        )
        assert "language clamp" in summary
        assert "blocked patterns" not in summary

    def test_terminal_constraints_with_allowed_and_deny(self) -> None:
        constraints = TerminalConstraints(
            allowed_commands=("git status",),
            deny_capabilities=PYTHON_SHELL_ONLY_DENY,
        )
        summary = AIOnboardingEngine._summarize_constraints(
            "RUN_COMMAND", constraints
        )
        assert "allowed commands" in summary
        assert "language clamp" in summary

    def test_empty_terminal_constraints_returns_generic_string(self) -> None:
        constraints = TerminalConstraints()
        summary = AIOnboardingEngine._summarize_constraints(
            "RUN_COMMAND", constraints
        )
        assert summary == "terminal command constraints are configured"
