"""Unit tests for prompt-id routing (DefaultPromptStrategy).

Covers:
  - AE routing matrix (standard vs critical_generic vs critical_network_probe
    vs critical_network_mutation) with the explicit precedence ordering.
  - Guardian routing matrix (standard vs critical).
  - Fail-closed behaviour on missing / malformed inputs:
      - RUN_COMMAND with command_intel=None → critical_generic
      - RUN_COMMAND with empty capabilities → critical_generic
      - Critical action that isn't RUN_COMMAND → critical_generic
  - Drift guard: ``CRITICAL_ACTIONS`` and
    ``AIAnalysisEngine._PASSIVE_READ_ACTIONS`` must not overlap — a
    single action must never be both passive-read and critical.
  - Library integrity: the strategy only returns ids that the prompt
    library knows about, so the engine never has to fall back.
"""

from __future__ import annotations

import pytest

from action_registry.types import ActionType
from intentframe_components.analysis.engine import AIAnalysisEngine
from intentframe_components.prompt.library import (
    ANALYSIS_PROMPT_IDS,
    GUARDIAN_PROMPT_IDS,
)
from intentframe_components.prompt.strategy import DefaultPromptStrategy
from intentframe_components.routing.criticality import CRITICAL_ACTIONS, is_critical
from intentframe_core.enums import Reversibility, RiskLevel
from intentframe_core.types import AnalysisReport, CommandIntel, FileIntel, IntentFrame


# ───────────────────────────── helpers ─────────────────────────────

def _intent(action: ActionType, target: str = "/tmp/x") -> IntentFrame:
    return IntentFrame(
        action=action,
        target=target,
        reason="test",
        agent_id="strategy_tester",
    )


def _intel(*capabilities: str) -> CommandIntel:
    return CommandIntel(
        verdict="SAFE",
        capabilities=tuple(capabilities),
    )


def _file_intel(
    *,
    language: str | None = None,
    is_binary: bool = False,
    is_oversized: bool = False,
    size_bytes: int = 0,
    has_code_intel_findings: bool = False,
    code_intel_finding_ids: tuple[str, ...] = (),
    signal_ids: tuple[str, ...] = (),
) -> FileIntel:
    return FileIntel(
        language=language,
        is_binary=is_binary,
        is_oversized=is_oversized,
        size_bytes=size_bytes,
        has_code_intel_findings=has_code_intel_findings,
        code_intel_finding_ids=code_intel_finding_ids,
        signal_ids=signal_ids,
    )


def _analysis() -> AnalysisReport:
    return AnalysisReport(
        stated_intent="test",
        risk_factors={"overall": RiskLevel.LOW},
        reversibility=Reversibility.FULLY_REVERSIBLE,
        confidence=1.0,
        recommendation="test",
    )


STRATEGY = DefaultPromptStrategy()


# ═══════════════════════════════════════════════════════════════════════
# Placeholder marker — payload-aware WRITE_FILE lanes
# ═══════════════════════════════════════════════════════════════════════
# WRITE_FILE currently routes flat to ``critical_write_file``.  A future
# split will route positively-classified code payloads to a dedicated
# ``critical_write_file_code`` lane, and passive / document-like payloads
# on benign destinations to ``standard``.  The tests below codify that
# future contract so that when per-lane overlay bodies are authored:
#
#   1. Add the new lane(s) to ``ANALYSIS_PROMPTS``.
#   2. Teach ``DefaultPromptStrategy.select_ae_prompt_id`` to branch on
#      ``file_intel``.
#   3. Remove this marker.
#
# ``strict=False`` so XPASS does not fail the suite — it's a hint to the
# author, not a gate.
_WRITE_FILE_LANE_PLACEHOLDER = pytest.mark.xfail(
    strict=False,
    reason=(
        "WRITE_FILE routing is flat today — every write lands in "
        "``critical_write_file``.  Payload-aware lanes "
        "(``critical_write_file_code`` for code payloads, ``standard`` for "
        "passive docs on benign destinations) are deferred until per-lane "
        "overlay bodies are authored.  Remove this marker when the split "
        "ships."
    ),
)


# ═══════════════════════════════════════════════════════════════════════
# AE routing
# ═══════════════════════════════════════════════════════════════════════

class TestAERouting:
    def test_non_critical_action_routes_to_standard(self):
        assert STRATEGY.select_ae_prompt_id(
            _intent(ActionType.LIST_CALENDARS), None,
        ) == "standard"

    def test_write_file_with_no_file_intel_routes_to_critical_write_file(self):
        # Fail-closed: a missing FileIntel on WRITE_FILE means upstream
        # plumbing is broken (the pipeline must compute FileIntel
        # whenever ``data.content`` is a string).  Safer default is
        # the payload-aware overlay than the standard prompt — the
        # symmetric stance for RUN_COMMAND with no CommandIntel below.
        assert STRATEGY.select_ae_prompt_id(
            _intent(ActionType.WRITE_FILE, "/tmp/x"), None,
        ) == "critical_write_file"

    @pytest.mark.parametrize("action", [
        ActionType.PAY_INVOICE,
        ActionType.DELETE_FILE,
        ActionType.DELETE_EVENT,
        ActionType.DELETE_REMINDER,
        ActionType.DELETE_CONTACT,
        ActionType.DELETE_NOTE,
        ActionType.DELETE_EMAIL,
        ActionType.SEND_EMAIL,
        ActionType.HTTP_POST,
    ])
    def test_non_run_critical_actions_route_to_critical_generic(self, action):
        assert STRATEGY.select_ae_prompt_id(_intent(action), None) == "critical_generic"

    def test_run_command_with_no_intel_routes_to_critical_generic(self):
        # Fail-closed: a missing CommandIntel on RUN_COMMAND means
        # upstream plumbing is broken; the safer default is the
        # critical overlay, not the standard prompt.
        assert STRATEGY.select_ae_prompt_id(
            _intent(ActionType.RUN_COMMAND, "ls -la"), None,
        ) == "critical_generic"

    def test_run_command_with_empty_caps_routes_to_critical_generic(self):
        assert STRATEGY.select_ae_prompt_id(
            _intent(ActionType.RUN_COMMAND, "do thing"), _intel(),
        ) == "critical_generic"

    def test_run_command_with_unrelated_caps_routes_to_critical_generic(self):
        assert STRATEGY.select_ae_prompt_id(
            _intent(ActionType.RUN_COMMAND, "do thing"),
            _intel("capability:filesystem_write"),
        ) == "critical_generic"

    # ── network_probe sub-routing ───────────────────────────────────

    @pytest.mark.parametrize("sub", ["icmp", "trace", "dns", "whois", "http_get"])
    def test_network_probe_subtags_route_to_probe_lane(self, sub):
        caps = _intel(f"capability:network_probe:{sub}")
        assert STRATEGY.select_ae_prompt_id(
            _intent(ActionType.RUN_COMMAND, "cmd"), caps,
        ) == "critical_network_probe"

    @pytest.mark.parametrize("sub", [
        "http_mutate", "http_download", "port_scan", "file_transfer",
    ])
    def test_network_mutation_subtags_route_to_mutation_lane(self, sub):
        caps = _intel(f"capability:network_probe:{sub}")
        assert STRATEGY.select_ae_prompt_id(
            _intent(ActionType.RUN_COMMAND, "cmd"), caps,
        ) == "critical_network_mutation"

    def test_mutation_beats_probe_when_both_present(self):
        # Precedence: mutation > probe > critical_generic > standard.
        caps = _intel(
            "capability:network_probe:dns",
            "capability:network_probe:http_mutate",
        )
        assert STRATEGY.select_ae_prompt_id(
            _intent(ActionType.RUN_COMMAND, "cmd"), caps,
        ) == "critical_network_mutation"

    def test_mutation_wins_even_with_read_only_and_probe_caps(self):
        caps = _intel(
            "capability:read_only:filesystem_list",
            "capability:network_probe:http_get",
            "capability:network_probe:port_scan",
        )
        assert STRATEGY.select_ae_prompt_id(
            _intent(ActionType.RUN_COMMAND, "cmd"), caps,
        ) == "critical_network_mutation"

    def test_unrelated_capability_not_matching_subtag_falls_through(self):
        # A network_probe:* tag we don't recognise (newer classifier,
        # older strategy) must not silently route to probe lane.
        caps = _intel("capability:network_probe:experimental_new_thing")
        assert STRATEGY.select_ae_prompt_id(
            _intent(ActionType.RUN_COMMAND, "cmd"), caps,
        ) == "critical_generic"


# ═══════════════════════════════════════════════════════════════════════
# WRITE_FILE AE routing — flat today, payload-aware tomorrow
# ═══════════════════════════════════════════════════════════════════════
# Current behaviour: every WRITE_FILE routes to ``critical_write_file``
# regardless of payload shape or destination.  ``FileIntel`` is accepted
# on the strategy signature and forwarded into the AE payload as
# context, but it does not influence prompt-id selection.
#
# Future behaviour (guarded by ``_WRITE_FILE_LANE_PLACEHOLDER`` xfails):
#
#   critical_write_file_code — payload positively classified as code
#       (language in CODE_LANGUAGES, OR code-intel findings present).
#       Wins over the generic critical lane even when the destination
#       is also a sensitive system path — "what the code does" is the
#       more specific concern.
#
#   critical_write_file — opaque payloads (binary / oversized /
#       missing FileIntel), and anything else that doesn't positively
#       classify as code.
#
#   standard — passive document-like payloads (text / markdown / json
#       with no code signals) on benign destinations.
#
# Sensitive-path destinations are BLOCKed pre-AE by
# :class:`DeterministicGuardian` in the main pipeline, so those cases
# never reach the strategy through the normal path.  The strategy
# still routes them to ``critical_write_file`` as defense in depth
# for callers that invoke the strategy directly (tests, tools) — that
# contract is asserted in ``test_sensitive_path_destinations_route_to_critical``
# below and holds today because every WRITE_FILE lands there anyway.

class TestWriteFileAERouting:
    # ── passive payloads on benign destinations → standard ──────
    # xfail: today every WRITE_FILE lands in ``critical_write_file``.
    # Passes once a ``standard`` fast-path for passive docs ships.

    @_WRITE_FILE_LANE_PLACEHOLDER
    def test_passive_text_md_routes_to_standard(self):
        fi = _file_intel(language=None, size_bytes=120)
        assert STRATEGY.select_ae_prompt_id(
            _intent(ActionType.WRITE_FILE, "/home/documents/notes.md"), None, fi,
        ) == "standard"

    @_WRITE_FILE_LANE_PLACEHOLDER
    def test_passive_json_routes_to_standard(self):
        fi = _file_intel(language=None, size_bytes=40)
        assert STRATEGY.select_ae_prompt_id(
            _intent(ActionType.WRITE_FILE, "/home/data/config.json"), None, fi,
        ) == "standard"

    @_WRITE_FILE_LANE_PLACEHOLDER
    def test_benign_extension_on_benign_destination_routes_to_standard(self):
        fi = _file_intel(language=None, size_bytes=10)
        assert STRATEGY.select_ae_prompt_id(
            _intent(ActionType.WRITE_FILE, "/home/documents/report.txt"), None, fi,
        ) == "standard"

    # ── positively-classified code → critical_write_file_code ───
    # xfail: the ``critical_write_file_code`` lane does not exist yet.
    # Passes once the code lane is added to ``ANALYSIS_PROMPTS`` and
    # the strategy learns to branch on ``file_intel.language`` /
    # ``file_intel.has_code_intel_findings``.

    @_WRITE_FILE_LANE_PLACEHOLDER
    def test_python_payload_routes_to_code_lane(self):
        fi = _file_intel(language="python", size_bytes=300)
        assert STRATEGY.select_ae_prompt_id(
            _intent(ActionType.WRITE_FILE, "/home/documents/notes.md"), None, fi,
        ) == "critical_write_file_code"

    @_WRITE_FILE_LANE_PLACEHOLDER
    def test_shell_payload_routes_to_code_lane(self):
        fi = _file_intel(language="shell", size_bytes=200)
        assert STRATEGY.select_ae_prompt_id(
            _intent(ActionType.WRITE_FILE, "/home/scripts/x.sh"), None, fi,
        ) == "critical_write_file_code"

    @_WRITE_FILE_LANE_PLACEHOLDER
    def test_javascript_payload_routes_to_code_lane(self):
        fi = _file_intel(language="javascript", size_bytes=200)
        assert STRATEGY.select_ae_prompt_id(
            _intent(ActionType.WRITE_FILE, "/home/scripts/x.js"), None, fi,
        ) == "critical_write_file_code"

    @_WRITE_FILE_LANE_PLACEHOLDER
    def test_code_intel_findings_route_to_code_lane(self):
        # Findings without a known code language are still a positive
        # code signal — ``command_shield`` flagged something executable.
        fi = _file_intel(
            language=None,
            has_code_intel_findings=True,
            code_intel_finding_ids=("EVAL_USE",),
            size_bytes=50,
        )
        assert STRATEGY.select_ae_prompt_id(
            _intent(ActionType.WRITE_FILE, "/home/documents/x.md"), None, fi,
        ) == "critical_write_file_code"

    @_WRITE_FILE_LANE_PLACEHOLDER
    def test_code_payload_on_autoload_destination_prefers_code_lane(self):
        # Both triggers fire — a Python file written to a sensitive
        # system path.  "What the code does" is the more specific
        # concern, so the code lane wins over the generic critical lane.
        fi = _file_intel(language="python", size_bytes=500)
        assert STRATEGY.select_ae_prompt_id(
            _intent(ActionType.WRITE_FILE, "/home/.zshrc.d/x.py"), None, fi,
        ) == "critical_write_file_code"

    # ── opaque payloads → critical_write_file (non-code) ────────

    def test_binary_payload_routes_to_critical_write_file(self):
        fi = _file_intel(language="binary", is_binary=True, size_bytes=1024)
        assert STRATEGY.select_ae_prompt_id(
            _intent(ActionType.WRITE_FILE, "/home/documents/x.md"), None, fi,
        ) == "critical_write_file"

    def test_oversized_payload_routes_to_critical_write_file(self):
        fi = _file_intel(is_oversized=True, size_bytes=10_000_000)
        assert STRATEGY.select_ae_prompt_id(
            _intent(ActionType.WRITE_FILE, "/home/documents/x.md"), None, fi,
        ) == "critical_write_file"

    def test_missing_file_intel_routes_to_critical_write_file(self):
        # Fail-closed: no deterministic evidence about the payload.
        assert STRATEGY.select_ae_prompt_id(
            _intent(ActionType.WRITE_FILE, "/home/documents/x.md"), None, None,
        ) == "critical_write_file"

    # ── destination-side defense in depth ───────────────────────
    # In the main pipeline these destinations are BLOCKed pre-AE by
    # :class:`DeterministicGuardian` (see
    # ``tests/test_deterministic_guardian.py::TestWriteFileAutoLoadBlock``).
    # The strategy still routes them to the critical lane for callers
    # that bypass DG — if a direct caller somehow lands a WRITE_FILE
    # with one of these targets at the strategy, we pick the strict
    # overlay rather than standard.

    @pytest.mark.parametrize("target", [
        "/home/.zshrc",
        "/home/.bashrc",
        "/home/.profile",
        "/home/library/launchagents/com.example.plist",
        "/home/.ssh/authorized_keys",
        "/home/.git/hooks/pre-commit",
        "/etc/sudoers",
        "/home/project/site-packages/evil.pth",
        "/home/project/sitecustomize.py",
    ])
    def test_sensitive_path_destinations_route_to_critical(self, target):
        fi = _file_intel(language=None, size_bytes=10)
        assert STRATEGY.select_ae_prompt_id(
            _intent(ActionType.WRITE_FILE, target), None, fi,
        ) == "critical_write_file"


# ═══════════════════════════════════════════════════════════════════════
# Guardian routing
# ═══════════════════════════════════════════════════════════════════════

class TestGuardianRouting:
    def test_non_critical_action_routes_to_standard(self):
        assert STRATEGY.select_guardian_prompt_id(
            _intent(ActionType.LIST_CALENDARS), _analysis(), None,
        ) == "standard"

    def test_run_command_routes_to_critical(self):
        assert STRATEGY.select_guardian_prompt_id(
            _intent(ActionType.RUN_COMMAND, "cmd"), _analysis(), None,
        ) == "critical"

    def test_pay_invoice_routes_to_critical(self):
        assert STRATEGY.select_guardian_prompt_id(
            _intent(ActionType.PAY_INVOICE), _analysis(), None,
        ) == "critical"

    def test_send_email_routes_to_critical(self):
        assert STRATEGY.select_guardian_prompt_id(
            _intent(ActionType.SEND_EMAIL, "bob@example.com"),
            _analysis(),
            None,
        ) == "critical"

    def test_guardian_ignores_command_intel_and_analysis(self):
        # Guardian routing is purely action-type driven.
        # Passing analysis / command_intel must not change the outcome.
        caps = _intel("capability:network_probe:http_mutate")
        assert STRATEGY.select_guardian_prompt_id(
            _intent(ActionType.LIST_CALENDARS), _analysis(), caps,
        ) == "standard"


# ═══════════════════════════════════════════════════════════════════════
# Library integrity and drift guards
# ═══════════════════════════════════════════════════════════════════════

class TestLibraryIntegrity:
    def test_ae_strategy_returns_only_known_ids(self):
        # Every RUN_COMMAND permutation the strategy can produce must
        # resolve to a real body in the library.  The engine has a
        # fail-closed fallback, but the default strategy must
        # never need to trigger it.
        for action in ActionType:
            pid = STRATEGY.select_ae_prompt_id(_intent(action, "x"), None)
            assert pid in ANALYSIS_PROMPT_IDS, (
                f"AE strategy returned unknown id {pid!r} for {action.value}"
            )

    def test_guardian_strategy_returns_only_known_ids(self):
        for action in ActionType:
            pid = STRATEGY.select_guardian_prompt_id(
                _intent(action, "x"), _analysis(), None,
            )
            assert pid in GUARDIAN_PROMPT_IDS, (
                f"Guardian strategy returned unknown id {pid!r} for {action.value}"
            )


class TestCriticalityDriftGuard:
    def test_critical_and_passive_reads_do_not_overlap(self):
        # An action must never be both a critical-lane candidate AND a
        # passive-read fast-path candidate.  If this fails, someone
        # added a new action to one set and forgot the other.
        passive = set(AIAnalysisEngine._PASSIVE_READ_ACTIONS)
        assert CRITICAL_ACTIONS.isdisjoint(passive), (
            "CRITICAL_ACTIONS overlaps _PASSIVE_READ_ACTIONS: "
            f"{CRITICAL_ACTIONS & passive}"
        )

    def test_is_critical_matches_set_membership(self):
        for action in ActionType:
            expected = action.value in CRITICAL_ACTIONS
            assert is_critical(action.value) is expected

    def test_run_command_is_critical(self):
        assert is_critical(ActionType.RUN_COMMAND.value)

    def test_list_calendars_is_not_critical(self):
        assert not is_critical(ActionType.LIST_CALENDARS.value)


# ═══════════════════════════════════════════════════════════════════════
# Engine fail-closed behaviour on bad strategies
# ═══════════════════════════════════════════════════════════════════════

class _BadStrategy:
    """Strategy that returns an id unknown to the library."""

    def select_ae_prompt_id(self, intent, command_intel, file_intel=None):
        return "not_a_real_id"

    def select_guardian_prompt_id(self, intent, analysis, command_intel, file_intel=None):
        return "also_bogus"


class _RaisingStrategy:
    """Strategy whose selector raises — simulates a plugin bug."""

    def select_ae_prompt_id(self, intent, command_intel, file_intel=None):
        raise RuntimeError("boom")

    def select_guardian_prompt_id(self, intent, analysis, command_intel, file_intel=None):
        raise RuntimeError("boom")


class TestEngineFailClosedOnBadStrategy:
    def test_ae_engine_downgrades_unknown_id_to_standard(self):
        engine = AIAnalysisEngine(verbose=False, prompt_strategy=_BadStrategy())
        assert engine._resolve_prompt_id(
            _intent(ActionType.RUN_COMMAND, "cmd"), None,
        ) == "standard"

    def test_ae_engine_downgrades_raising_strategy_to_standard(self):
        engine = AIAnalysisEngine(verbose=False, prompt_strategy=_RaisingStrategy())
        assert engine._resolve_prompt_id(
            _intent(ActionType.RUN_COMMAND, "cmd"), None,
        ) == "standard"

    def test_guardian_engine_downgrades_unknown_id_to_standard(self):
        from intentframe_components.guardian.engine import AIGuardian
        guardian = AIGuardian(verbose=False, prompt_strategy=_BadStrategy())
        assert guardian._resolve_prompt_id(
            _intent(ActionType.RUN_COMMAND, "cmd"), _analysis(), None,
        ) == "standard"

    def test_guardian_engine_downgrades_raising_strategy_to_standard(self):
        from intentframe_components.guardian.engine import AIGuardian
        guardian = AIGuardian(verbose=False, prompt_strategy=_RaisingStrategy())
        assert guardian._resolve_prompt_id(
            _intent(ActionType.RUN_COMMAND, "cmd"), _analysis(), None,
        ) == "standard"


# ═══════════════════════════════════════════════════════════════════════
# Engine construction — Agent-per-id shape
# ═══════════════════════════════════════════════════════════════════════

class TestEngineAgentShape:
    def test_ae_engine_builds_one_agent_per_prompt_id(self):
        engine = AIAnalysisEngine(verbose=False)
        assert set(engine._agents.keys()) == set(ANALYSIS_PROMPT_IDS)

    def test_ae_default_agent_points_to_standard_lane(self):
        engine = AIAnalysisEngine(verbose=False)
        assert engine._agent is engine._agents["standard"]

    def test_guardian_engine_builds_one_agent_per_prompt_id(self):
        from intentframe_components.guardian.engine import AIGuardian
        guardian = AIGuardian(verbose=False)
        assert set(guardian._agents.keys()) == set(GUARDIAN_PROMPT_IDS)

    def test_guardian_default_agent_points_to_standard_lane(self):
        from intentframe_components.guardian.engine import AIGuardian
        guardian = AIGuardian(verbose=False)
        assert guardian._agent is guardian._agents["standard"]

    def test_ae_last_prompt_id_initially_none(self):
        engine = AIAnalysisEngine(verbose=False)
        assert engine.last_prompt_id is None

    def test_guardian_last_prompt_id_initially_none(self):
        from intentframe_components.guardian.engine import AIGuardian
        guardian = AIGuardian(verbose=False)
        assert guardian.last_prompt_id is None
