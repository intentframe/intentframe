"""Unit tests for the prompt library — structural and content invariants.

These tests pin the contract between the prompt bodies and the rest of
the system.  They intentionally do **not** pin the exact text — prompt
content will evolve over time — but they do pin the structural
invariants that the engines and tests depend on:

  - Every AE / Guardian prompt id is reachable and non-empty.
  - The ``standard`` bodies still contain the keyword fragments that
    ``tests/test_prompt_hardening.py`` and
    ``tests/test_transitive_injection.py`` rely on.
  - ``critical_generic`` equals ``standard`` by deliberate design.
  - ``critical_run_command`` and ``critical_write_file`` are full-body
    forks that contain command- / write-shaped framing, are factual-
    analysis prompts, and do not direct the AE to allow or block.
  - ``critical_network_probe`` and ``critical_network_mutation`` are
    aliased to ``critical_run_command`` in the initial rollout
    (byte-identical).  When per-lane full-body forks replace them, the
    aliasing assertions should be deleted rather than mechanically updated.
  - Guardian's ``critical`` body equals ``standard`` by deliberate design.
  - ``_base_instructions()`` on both engines still returns the
    ``standard`` body — the back-compat promise.
"""

from __future__ import annotations

import pytest

from intentframe_components.analysis.engine import AIAnalysisEngine
from intentframe_components.guardian.engine import AIGuardian
from intentframe_components.prompt.library import (
    ANALYSIS_PROMPTS,
    ANALYSIS_PROMPT_IDS,
    GUARDIAN_PROMPTS,
    GUARDIAN_PROMPT_IDS,
)


# ═══════════════════════════════════════════════════════════════════════
# Shape invariants
# ═══════════════════════════════════════════════════════════════════════

class TestLibraryShape:
    def test_ae_has_expected_prompt_ids(self):
        assert ANALYSIS_PROMPT_IDS == frozenset({
            "standard",
            "critical_run_command",
            "critical_generic",
            "critical_network_probe",
            "critical_network_mutation",
            "critical_write_file",
        })

    def test_guardian_has_expected_prompt_ids(self):
        assert GUARDIAN_PROMPT_IDS == frozenset({"standard", "critical"})

    def test_every_ae_id_has_nonempty_body(self):
        for pid, body in ANALYSIS_PROMPTS.items():
            assert isinstance(body, str) and body.strip(), f"empty body for {pid}"

    def test_every_guardian_id_has_nonempty_body(self):
        for pid, body in GUARDIAN_PROMPTS.items():
            assert isinstance(body, str) and body.strip(), f"empty body for {pid}"

    def test_ae_prompts_mapping_is_read_only(self):
        import pytest
        with pytest.raises(TypeError):
            ANALYSIS_PROMPTS["standard"] = "nope"  # type: ignore[index]

    def test_guardian_prompts_mapping_is_read_only(self):
        import pytest
        with pytest.raises(TypeError):
            GUARDIAN_PROMPTS["standard"] = "nope"  # type: ignore[index]


# ═══════════════════════════════════════════════════════════════════════
# Standard-body invariants (the back-compat contract)
# ═══════════════════════════════════════════════════════════════════════

class TestAEStandardBody:
    def test_contains_semantic_domains_section(self):
        # tests/test_prompt_hardening.py asserts on this exact phrase.
        assert "Semantic domains" in ANALYSIS_PROMPTS["standard"]

    def test_contains_hidden_behaviors_section(self):
        assert "Hidden behaviors" in ANALYSIS_PROMPTS["standard"]

    def test_contains_data_integrity_section(self):
        assert "Data integrity" in ANALYSIS_PROMPTS["standard"]

    def test_contains_factual_analysis_phrase(self):
        assert "factual analysis" in ANALYSIS_PROMPTS["standard"]

    def test_base_instructions_facade_returns_standard(self):
        assert AIAnalysisEngine._base_instructions() == ANALYSIS_PROMPTS["standard"]


class TestGuardianStandardBody:
    def test_contains_allow_block_decisions_phrase(self):
        assert "ALLOW/BLOCK" in GUARDIAN_PROMPTS["standard"]

    def test_contains_intent_limits_section(self):
        assert "Intent Limits" in GUARDIAN_PROMPTS["standard"]

    def test_contains_ask_user_carve_out(self):
        assert "ASK_USER" in GUARDIAN_PROMPTS["standard"]

    def test_base_instructions_facade_returns_standard(self):
        assert AIGuardian._base_instructions() == GUARDIAN_PROMPTS["standard"]


# ═══════════════════════════════════════════════════════════════════════
# Critical-overlay invariants (additive, one-direction)
# ═══════════════════════════════════════════════════════════════════════

class TestAECriticalGenericBody:
    """Pin the ``critical_generic`` body contract.

    ``critical_generic`` is deliberately equal to ``standard`` — it covers
    PAY_INVOICE, DELETE_*, SEND_EMAIL, HTTP_POST whose rubric is already
    well-served by the standard body and whose examples are exactly these
    typed, structured actions.  These tests document that intentionally.
    """

    def test_critical_generic_equals_standard_body(self):
        # Deliberate design: critical_generic IS standard.
        # If this ever becomes a full-body fork, replace this assertion
        # with content-specific markers (like TestAECriticalRunCommandBody).
        assert ANALYSIS_PROMPTS["critical_generic"] == ANALYSIS_PROMPTS["standard"]

    def test_critical_generic_does_not_instruct_ae_to_allow_or_block(self):
        body = ANALYSIS_PROMPTS["critical_generic"]
        forbidden = [
            "you must ALLOW",
            "you must BLOCK",
            "you allow",
            "you block",
            "You ALLOW",
            "You BLOCK",
        ]
        for phrase in forbidden:
            assert phrase not in body, f"critical_generic body contains directive {phrase!r}"


class TestAECriticalWriteFileBody:
    """Pin WRITE_FILE-specific markers in the ``critical_write_file`` body.

    The body is a fork of ``_STANDARD`` (not an overlay): it re-teaches
    the full analysis rubric with write-specific framing (destination-
    payload cross-check, payload-signals consumption, consumer
    awareness).  These assertions catch accidents — e.g. reverting the
    key to point at ``_STANDARD``, or pasting a Guardian body into this
    lane.
    """

    def test_body_contains_write_framing(self):
        body = ANALYSIS_PROMPTS["critical_write_file"]
        markers = (
            "WRITE_FILE",
            "file-write",
            "destination",
            "payload",
        )
        assert any(m in body for m in markers), (
            f"critical_write_file body must mention write-shaped framing; "
            f"got: {body[:120]!r}"
        )

    def test_body_is_factual_analysis(self):
        # Same invariant as the standard body — AE understands, does not decide.
        assert "factual analysis" in ANALYSIS_PROMPTS["critical_write_file"]

    def test_body_does_not_instruct_ae_to_allow_or_block(self):
        body = ANALYSIS_PROMPTS["critical_write_file"]
        forbidden = [
            "you must ALLOW",
            "you must BLOCK",
            "you allow",
            "you block",
            "You ALLOW",
            "You BLOCK",
        ]
        for phrase in forbidden:
            assert phrase not in body, (
                f"critical_write_file body contains directive {phrase!r}"
            )


class TestAECriticalRunCommandBody:
    """Pin RUN_COMMAND-specific markers in the ``critical_run_command`` body.

    The body is a fork of ``_STANDARD`` (not an overlay): it re-teaches
    the full analysis rubric with command-specific framing.  These
    assertions catch accidents — e.g. reverting the key to point at
    ``_STANDARD``, or pasting a Guardian body into this lane.
    """

    def test_body_contains_command_framing(self):
        body = ANALYSIS_PROMPTS["critical_run_command"]
        # Any of these structural markers is fine — we're pinning the
        # command-shaped framing, not the exact text.
        markers = (
            "TERMINAL COMMAND",
            "shell command",
            "decompose",
            "compound",
        )
        assert any(m in body for m in markers), (
            f"critical_run_command body must mention command-shaped framing; "
            f"got: {body[:120]!r}"
        )

    def test_body_is_factual_analysis(self):
        # Same invariant as the standard body — AE understands, does not decide.
        assert "factual analysis" in ANALYSIS_PROMPTS["critical_run_command"]

    def test_body_does_not_instruct_ae_to_allow_or_block(self):
        body = ANALYSIS_PROMPTS["critical_run_command"]
        forbidden = [
            "you must ALLOW",
            "you must BLOCK",
            "you allow",
            "you block",
            "You ALLOW",
            "You BLOCK",
        ]
        for phrase in forbidden:
            assert phrase not in body, (
                f"critical_run_command body contains directive {phrase!r}"
            )


class TestGuardianCriticalBody:
    """Pin the Guardian ``critical`` body contract.

    ``critical`` is deliberately equal to ``standard`` — Guardian's
    standard body is already enforcement-heavy (BLOCK on HIGH/CRITICAL
    risk, scope mismatch, hidden behaviours, limit violations) and a
    separate critical body would risk instruction drift without adding
    value.  These tests document that intentionally.
    """

    def test_critical_equals_standard_body(self):
        # Deliberate design: critical IS standard.
        # If this ever becomes a full-body fork, replace this assertion
        # with content-specific markers.
        assert GUARDIAN_PROMPTS["critical"] == GUARDIAN_PROMPTS["standard"]


# ═══════════════════════════════════════════════════════════════════════
# Initial-rollout aliasing (delete this class when per-lane full-body
# forks are authored for probe / mutation lanes)
# ═══════════════════════════════════════════════════════════════════════

class TestInitialRolloutAliasing:
    """Probe / mutation lanes are aliased to critical_run_command on initial rollout.

    These tests document that intentionally.  When per-lane full-body forks
    replace either lane, delete the corresponding assertion here rather than
    mechanically updating it — the whole point is that the alias is temporary.
    """

    def test_probe_lane_aliased_to_critical_run_command(self):
        assert ANALYSIS_PROMPTS["critical_network_probe"] == ANALYSIS_PROMPTS[
            "critical_run_command"
        ]

    def test_mutation_lane_aliased_to_critical_run_command(self):
        assert ANALYSIS_PROMPTS["critical_network_mutation"] == ANALYSIS_PROMPTS[
            "critical_run_command"
        ]
