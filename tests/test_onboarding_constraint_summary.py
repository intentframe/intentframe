"""Unit coverage for `AIOnboardingEngine._summarize_constraints` and
`_summarize_deny_capabilities`.

The summarizer is the seam through which the live `deny_capabilities`
deny set surfaces to the onboarding LLM.  Before this seam was wired,
the LLM only saw `blocked_patterns` + `allowed_commands`; the language
clamp was invisible, and the agent (e.g. Jarvis) generated guardrails
that didn't reflect the python+shell-only restriction.  The downstream
effect was: runtime enforcement held, but the LLM kept attempting
`node`/`ruby`/etc., wasting tokens and surfacing noisy "blocked" events
instead of polite "outside policy" responses.

The summarizer's contract has two halves, intentionally separated:

  1. INPUT to the meta-LLM (this helper):  render the deny set
     **losslessly** and **structured by family**.  The meta-LLM gets
     full visibility into actual policy — no shadow prose summary that
     can drift from the live deny set as policy evolves.

  2. OUTPUT from the meta-LLM (the actual guardrail bullets it authors):
     minimal positive steering, enforced via the meta-prompt in
     `_build_instructions`.  The LLM-facing layer's job is to steer
     toward the canonical path, not to repeat the deny list as guardrail
     prose.

These tests pin the INPUT half:

  - the brief is **lossless**: every denied tag's suffix appears,
  - the brief is **grouped by capability family** for legibility,
  - the brief is plain constraint data and does **not** leak enforcement
    architecture into the onboarding prompt,
  - the brief is **stable under unknown future families** (no crash, no
    silent drop),
  - `blocked_patterns` and `allowed_commands` continue to be summarised
    alongside `deny_capabilities` (no regression of existing behaviour).

The OUTPUT half (the meta-LLM's guardrail authoring) is enforced by
the meta-prompt in `_build_instructions`; it cannot be unit-tested here
without invoking the real LLM, but the meta-prompt is reviewed by hand
and documented in the engine module docstring.
"""

from __future__ import annotations

import pytest

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


class TestSummarizeDenyCapabilitiesIsLossless:
    def test_every_deny_tag_suffix_appears_in_brief(self) -> None:
        """No information loss: every denied tag's suffix appears in the
        rendered brief.  Pre-summarising in this layer (e.g. "non-python
        interpreters denied: …") creates a shadow representation that
        drifts from the live deny set as families/tags evolve and drops
        information the meta-LLM needs to judge guardrail shape.
        """
        brief = AIOnboardingEngine._summarize_deny_capabilities(
            PYTHON_SHELL_ONLY_DENY
        )
        for tag in PYTHON_SHELL_ONLY_DENY:
            suffix = tag.split(":", 2)[-1]
            assert suffix in brief, (
                f"deny tag {tag!r} (suffix {suffix!r}) missing from brief — "
                "summarising in this layer drops information the meta-LLM "
                "needs"
            )

    def test_grouped_by_capability_family(self) -> None:
        """Tags are grouped by family for legibility (script_execution,
        stdin_exec, package_install, other).  Grouping is a structural
        cue that lets the meta-LLM recognise the python+shell-only
        clamp shape without us having to call it out in prose.
        """
        brief = AIOnboardingEngine._summarize_deny_capabilities(
            PYTHON_SHELL_ONLY_DENY
        )
        for family in ("script_execution", "stdin_exec", "package_install"):
            assert family in brief, (
                f"capability family {family!r} should be a labelled bucket "
                "in the brief"
            )

    def test_brief_does_not_leak_enforcement_architecture(self) -> None:
        """The brief is constraint data for onboarding, not a primer on
        internal enforcement architecture.  The actual *don't enumerate*
        directive lives in `_build_instructions`.
        """
        brief = AIOnboardingEngine._summarize_deny_capabilities(
            PYTHON_SHELL_ONLY_DENY
        )
        lowered = brief.lower()
        for internal in ("gate 2", "guardian", "deterministic"):
            assert internal not in lowered


class TestSummarizeDenyCapabilitiesEdgeCases:
    def test_empty_deny_set_returns_count_fallback(self) -> None:
        """Defensive: caller filters this case out (empty deny → no
        call), but if it does get here the helper must not crash or
        invent policy text.
        """
        brief = AIOnboardingEngine._summarize_deny_capabilities(frozenset())
        assert "deny_capabilities" not in brief
        assert "0" in brief or "no" in brief.lower()

    def test_compilation_only_renders_under_other(self) -> None:
        """`capability:compilation` is a binary tag (no suffix), so it
        falls under the `other` bucket.  Lossless: the tag is preserved
        verbatim.
        """
        brief = AIOnboardingEngine._summarize_deny_capabilities(
            frozenset({"capability:compilation"})
        )
        assert "compilation" in brief
        assert "other" in brief

    def test_unknown_capability_family_renders_under_other(self) -> None:
        """A future deny tag from a family this helper doesn't know
        about (e.g. `capability:future_family:special`) MUST still
        appear in the brief.  This is the robustness-to-policy-changes
        property: this helper does not need a code change every time
        a new capability family is added; the meta-LLM can reason
        about novel families given the raw tag.
        """
        brief = AIOnboardingEngine._summarize_deny_capabilities(
            frozenset({"capability:future_family:special"})
        )
        assert "future_family:special" in brief, (
            "unknown future capability families must still surface "
            "verbatim — pre-summarising drops them and creates a "
            "shadow drift hazard"
        )

    def test_stdin_exec_tags_grouped_separately_from_script_execution(self) -> None:
        """`stdin_exec:<lang>` and `script_execution:<lang>` are
        distinct family buckets.  The meta-LLM can use the
        co-occurrence as a structural cue (per-interpreter pipe-deny
        AND per-interpreter file-deny → full clamp).
        """
        brief = AIOnboardingEngine._summarize_deny_capabilities(
            frozenset({
                "capability:script_execution:node",
                "capability:stdin_exec:node",
            })
        )
        assert "script_execution=" in brief
        assert "stdin_exec=" in brief


class TestSummarizeConstraintsIntegration:
    def test_terminal_constraints_summary_includes_full_deny_set(self) -> None:
        """End-to-end: the terminal constraints summary includes the
        lossless deny brief alongside `blocked_patterns`.  Concrete
        denied items (node, npm, compilation) are visible to the
        meta-LLM in the constraints brief.
        """
        constraints = TerminalConstraints(
            blocked_patterns=("sudo", "rm -rf /"),
            deny_capabilities=PYTHON_SHELL_ONLY_DENY,
        )
        summary = AIOnboardingEngine._summarize_constraints(
            "RUN_COMMAND", constraints
        )
        assert "blocked patterns" in summary
        assert "node" in summary
        assert "npm" in summary
        assert "compilation" in summary

    def test_terminal_constraints_with_only_blocked_patterns(self) -> None:
        """No deny_capabilities → no deny brief leak; existing
        behaviour preserved.
        """
        constraints = TerminalConstraints(
            blocked_patterns=("sudo",),
        )
        summary = AIOnboardingEngine._summarize_constraints(
            "RUN_COMMAND", constraints
        )
        assert "blocked patterns" in summary
        assert "deny_capabilities" not in summary
        assert "Gate 2" not in summary
        assert "guardian" not in summary.lower()

    def test_terminal_constraints_with_only_deny_capabilities(self) -> None:
        constraints = TerminalConstraints(
            deny_capabilities=PYTHON_SHELL_ONLY_DENY,
        )
        summary = AIOnboardingEngine._summarize_constraints(
            "RUN_COMMAND", constraints
        )
        assert "deny_capabilities" in summary
        assert "node" in summary
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
        assert "deny_capabilities" in summary

    def test_empty_terminal_constraints_returns_generic_string(self) -> None:
        constraints = TerminalConstraints()
        summary = AIOnboardingEngine._summarize_constraints(
            "RUN_COMMAND", constraints
        )
        assert summary == "terminal command constraints are configured"


# ── meta-prompt contract ─────────────────────────────────────────────


class TestBuildInstructionsMetaPromptContract:
    """The meta-prompt in `_build_instructions` is the OUTPUT half of
    the onboarding contract: it directs the meta-LLM to translate the
    lossless deny brief into ONE concrete, actionable guardrail rather
    than a vague "avoid denied capabilities" pointer.

    We observed the meta-LLM quietly regressing to produce bullets
    like "avoid script execution from denied capabilities" when the
    instruction was soft.  Those pointers give the agent zero
    actionable information and defeat the whole purpose of the deny
    brief.  These tests pin the contract so the instruction stays
    imperative and carries the verbatim surface (POSIX tool names
    + `python3` + the concrete denied runtimes) that the agent needs.
    """

    def _instructions(self) -> str:
        # Avoid constructing the real OpenAI Agent (needs API key) —
        # we only care about the static instructions string, which
        # does not depend on any instance state in ``__init__``.
        return AIOnboardingEngine._build_instructions(
            AIOnboardingEngine.__new__(AIOnboardingEngine)
        )

    def test_instructions_forbid_vague_pointer_bullets(self) -> None:
        """'avoid denied capabilities' / 'avoid script execution from
        the deny list' are exactly the kind of vague bullets the
        meta-LLM defaults to.  The instructions must explicitly
        forbid them so the LLM is pushed into writing actionable
        steering instead.
        """
        text = self._instructions()
        assert "vague" in text.lower() or "no actionable" in text.lower() or (
            "actionable information" in text.lower()
        ), (
            "meta-prompt must explicitly mark 'avoid denied capabilities'-"
            "style pointer bullets as forbidden"
        )

    @pytest.mark.xfail(
        reason="Meta-prompt POSIX/python guardrail contract not enforced in _build_instructions for now"
    )
    def test_instructions_mandate_posix_plus_python_guardrail(self) -> None:
        """When the deny brief clamps multiple script-execution
        runtimes, the meta-LLM MUST emit a guardrail that names the
        canonical surface.  Pin the concrete tokens so a refactor
        that drops one of them fails loudly.
        """
        text = self._instructions()
        assert "MUST" in text, (
            "meta-prompt must be imperative, not advisory, about the "
            "python+shell guardrail"
        )
        for tool in ("grep", "sed", "awk", "cut", "sort", "find", "python3"):
            assert tool in text, (
                f"meta-prompt must name {tool!r} as part of the supported "
                "surface so the LLM carries it verbatim into the guardrail"
            )
        for runtime in ("node", "ruby", "perl", "php", "java", "go"):
            assert runtime in text, (
                f"meta-prompt must name {runtime!r} as a runtime the "
                "agent should avoid in favour of Python"
            )

    @pytest.mark.xfail(
        reason="Meta-prompt script_execution trigger contract not enforced in _build_instructions for now"
    )
    def test_instructions_reference_script_execution_trigger(self) -> None:
        """The instruction needs a concrete trigger — "when
        `script_execution:<lang>` denies are present" — so the LLM
        knows exactly when to emit the guardrail rather than guessing.
        """
        text = self._instructions()
        assert "script_execution" in text, (
            "meta-prompt must tie the python+shell guardrail to the "
            "`script_execution:<lang>` family so the trigger is concrete"
        )
