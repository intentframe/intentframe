"""Unit tests for the prompt library — structural and content invariants.

These tests pin the contract between the prompt bodies and the rest of
the system.  They intentionally do **not** pin the exact text — prompt
content will evolve over time — but they do pin the structural
invariants that the engines and tests depend on:

  - Every AE / Guardian prompt id is reachable and non-empty.
  - The ``standard`` bodies still contain the keyword fragments that
    ``tests/test_prompt_hardening.py`` and
    ``tests/test_transitive_injection.py`` rely on.
  - The ``critical_generic`` body is a strict superset of ``standard``
    (the overlay is additive, never a replacement).
  - The ``critical_generic`` overlay preserves the "understand, not
    decide" invariant (still says Guardian is the decider) and does
    not introduce an allow/block verdict into the AE prompt.
  - ``critical_network_probe`` and ``critical_network_mutation`` are
    aliased to ``critical_generic`` in the initial rollout (byte-identical).
    Per-lane overlay bodies will replace them later; when they do, the
    "alias" test should be deleted rather than mechanically updated.
  - Guardian's ``critical`` body is a strict superset of ``standard``
    with symmetric critical-overlay properties.
  - ``_base_instructions()`` on both engines still returns the
    ``standard`` body — the back-compat promise.

Placeholder tests for overlay content (initial rollout)
-------------------------------------------------------
The six tests that assert on critical-overlay *content* (length
strictly greater than standard, "CRITICAL-ACTION OVERLAY" marker,
"understand/decide" / "enforce/analyse" framing) are marked
``@pytest.mark.xfail(strict=False, ...)`` because ``_CRITICAL_OVERLAY``
is intentionally ``""`` in the initial rollout — the routing plumbing
ships now, the overlay bodies ship later.  ``strict=False`` means: when
the overlays are authored and the tests start passing, pytest will
report them as XPASS rather than failing the suite, giving the author
a clear signal to remove the markers.
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
# Placeholder marker — remove from each test below when the
# corresponding overlay body is authored (see library/__init__.py).
# ═══════════════════════════════════════════════════════════════════════

_OVERLAY_PLACEHOLDER = pytest.mark.xfail(
    strict=False,
    reason=(
        "_CRITICAL_OVERLAY is intentionally empty in the initial rollout; "
        "routing / audit plumbing ships now, overlay bodies deferred to a "
        "later PR.  Remove this marker when the overlay is authored."
    ),
)


# ═══════════════════════════════════════════════════════════════════════
# Shape invariants
# ═══════════════════════════════════════════════════════════════════════

class TestLibraryShape:
    def test_ae_has_expected_prompt_ids(self):
        assert ANALYSIS_PROMPT_IDS == frozenset({
            "standard",
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

class TestAECriticalOverlay:
    def test_critical_generic_starts_with_standard_body(self):
        # Additive: critical_generic must contain the entire standard
        # body verbatim as a prefix.  No rewrites of inherited rules.
        # Passes trivially while overlay is empty (critical_generic ==
        # standard).  Remains the correct invariant once the overlay is authored.
        assert ANALYSIS_PROMPTS["critical_generic"].startswith(
            ANALYSIS_PROMPTS["standard"],
        )

    @_OVERLAY_PLACEHOLDER
    def test_critical_generic_is_strictly_longer_than_standard(self):
        assert len(ANALYSIS_PROMPTS["critical_generic"]) > len(
            ANALYSIS_PROMPTS["standard"],
        )

    @_OVERLAY_PLACEHOLDER
    def test_critical_overlay_mentions_critical_action_framing(self):
        overlay = ANALYSIS_PROMPTS["critical_generic"][len(ANALYSIS_PROMPTS["standard"]):]
        assert "CRITICAL-ACTION OVERLAY" in overlay

    @_OVERLAY_PLACEHOLDER
    def test_critical_overlay_preserves_understand_not_decide(self):
        # The core invariant from concepts/core/layers/03-analysis-engine.md:
        # AE never makes an ALLOW/BLOCK decision.  The overlay must
        # reaffirm this, not undermine it.
        overlay = ANALYSIS_PROMPTS["critical_generic"][len(ANALYSIS_PROMPTS["standard"]):]
        lowered = overlay.lower()
        assert "understand" in lowered
        assert "decide" in lowered
        # Guardian remains the authority.
        assert "Guardian" in overlay

    def test_critical_overlay_does_not_instruct_ae_to_allow_or_block(self):
        # The AE prompt must not contain imperatives that direct the
        # AE itself to ALLOW or BLOCK.  "ALLOW/BLOCK" may appear as
        # context ("Guardian decides ALLOW/BLOCK") but never as an
        # instruction aimed at the AE.
        overlay = ANALYSIS_PROMPTS["critical_generic"][len(ANALYSIS_PROMPTS["standard"]):]
        forbidden = [
            "you must ALLOW",
            "you must BLOCK",
            "you allow",
            "you block",
            "You ALLOW",
            "You BLOCK",
        ]
        for phrase in forbidden:
            assert phrase not in overlay, f"AE overlay contains directive {phrase!r}"


class TestAECriticalWriteFileOverlay:
    """Symmetric overlay invariants for the ``critical_write_file`` lane.

    Mirrors :class:`TestAECriticalOverlay` for ``critical_generic``.  The
    xfailed tests document the future body contract: once a real
    WRITE_FILE-specific overlay is authored (payload context framing,
    executability reminders, etc.), these tests start passing and the
    markers come off.
    """

    def test_critical_write_file_starts_with_standard_body(self):
        # Additive: critical_write_file must contain the entire standard
        # body verbatim as a prefix.  Passes trivially while the overlay
        # is empty (critical_write_file == standard).
        assert ANALYSIS_PROMPTS["critical_write_file"].startswith(
            ANALYSIS_PROMPTS["standard"],
        )

    @_OVERLAY_PLACEHOLDER
    def test_critical_write_file_is_strictly_longer_than_standard(self):
        assert len(ANALYSIS_PROMPTS["critical_write_file"]) > len(
            ANALYSIS_PROMPTS["standard"],
        )

    @_OVERLAY_PLACEHOLDER
    def test_critical_write_file_overlay_mentions_write_framing(self):
        # Pin some identifiable WRITE_FILE framing in the overlay so
        # authoring accidents (e.g. pasting the RUN_COMMAND overlay
        # into this lane) are caught.  The exact phrase is not
        # specified — any of the common markers is acceptable.
        overlay = ANALYSIS_PROMPTS["critical_write_file"][
            len(ANALYSIS_PROMPTS["standard"]):
        ]
        markers = ("WRITE_FILE", "write_file", "file write")
        assert any(m in overlay for m in markers), (
            f"overlay must mention a WRITE_FILE marker; got: {overlay[:120]!r}"
        )

    @_OVERLAY_PLACEHOLDER
    def test_critical_write_file_overlay_preserves_understand_not_decide(self):
        # Same invariant as the generic overlay: AE understands, Guardian
        # decides.  The overlay must reaffirm this, not undermine it.
        overlay = ANALYSIS_PROMPTS["critical_write_file"][
            len(ANALYSIS_PROMPTS["standard"]):
        ]
        lowered = overlay.lower()
        assert "understand" in lowered
        assert "decide" in lowered
        assert "Guardian" in overlay

    def test_critical_write_file_overlay_does_not_instruct_ae_to_allow_or_block(self):
        overlay = ANALYSIS_PROMPTS["critical_write_file"][
            len(ANALYSIS_PROMPTS["standard"]):
        ]
        forbidden = [
            "you must ALLOW",
            "you must BLOCK",
            "you allow",
            "you block",
            "You ALLOW",
            "You BLOCK",
        ]
        for phrase in forbidden:
            assert phrase not in overlay, f"AE overlay contains directive {phrase!r}"


class TestGuardianCriticalOverlay:
    def test_critical_starts_with_standard_body(self):
        # Passes trivially while overlay is empty (critical == standard).
        assert GUARDIAN_PROMPTS["critical"].startswith(GUARDIAN_PROMPTS["standard"])

    @_OVERLAY_PLACEHOLDER
    def test_critical_is_strictly_longer_than_standard(self):
        assert len(GUARDIAN_PROMPTS["critical"]) > len(GUARDIAN_PROMPTS["standard"])

    @_OVERLAY_PLACEHOLDER
    def test_critical_overlay_mentions_critical_action_framing(self):
        overlay = GUARDIAN_PROMPTS["critical"][len(GUARDIAN_PROMPTS["standard"]):]
        assert "CRITICAL-ACTION OVERLAY" in overlay

    @_OVERLAY_PLACEHOLDER
    def test_critical_overlay_preserves_enforce_not_analyse(self):
        overlay = GUARDIAN_PROMPTS["critical"][len(GUARDIAN_PROMPTS["standard"]):]
        lowered = overlay.lower()
        assert "enforce" in lowered
        assert "analyse" in lowered or "analyze" in lowered
        # Analysis Engine remains the factual source.
        assert "Analysis Engine" in overlay


# ═══════════════════════════════════════════════════════════════════════
# Initial-rollout aliasing (delete this class when per-lane overlay
# bodies are authored for probe / mutation lanes)
# ═══════════════════════════════════════════════════════════════════════

class TestInitialRolloutAliasing:
    """Probe / mutation lanes are aliased to critical_generic on initial rollout.

    These tests document that intentionally.  When per-lane overlay bodies
    replace either lane, delete the corresponding assertion here rather than
    mechanically updating it — the whole point is that the alias is temporary.
    """

    def test_probe_lane_aliased_to_critical_generic(self):
        assert ANALYSIS_PROMPTS["critical_network_probe"] == ANALYSIS_PROMPTS[
            "critical_generic"
        ]

    def test_mutation_lane_aliased_to_critical_generic(self):
        assert ANALYSIS_PROMPTS["critical_network_mutation"] == ANALYSIS_PROMPTS[
            "critical_generic"
        ]

    def test_write_file_lane_aliased_to_standard_body(self):
        # ``critical_write_file`` aliases the standard body directly on
        # initial rollout (``_CRITICAL_WRITE_FILE_OVERLAY = ""``).  When
        # a real WRITE_FILE overlay is authored, delete this assertion
        # and rely on :class:`TestAECriticalWriteFileOverlay` instead.
        assert ANALYSIS_PROMPTS["critical_write_file"] == ANALYSIS_PROMPTS[
            "standard"
        ]
