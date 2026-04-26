"""Unit tests for ``intentframe_gateway.escalation``.

The helper must be fault-tolerant — it's called on every gateway
startup and on every ``/system/health`` hit — and should never raise
regardless of what the user-space marker file looks like.
"""

from __future__ import annotations

import json
from pathlib import Path

from intentframe_gateway.escalation import (
    EscalationState,
    detect_escalation_state,
    is_escalation_armed,
)


def _write_marker(path: Path, payload: dict | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload)
    else:
        path.write_text(json.dumps(payload))
    return path


class TestDetectEscalationState:
    def test_missing_marker_reports_disarmed(self, tmp_path: Path) -> None:
        marker = tmp_path / "does" / "not" / "exist.json"
        state = detect_escalation_state(marker_path=marker)
        assert state.armed is False
        assert "marker file missing" in state.reason
        assert state.marker_path == str(marker)

    def test_unreadable_marker_reports_disarmed(self, tmp_path: Path) -> None:
        marker = _write_marker(tmp_path / "m.json", "not json at all {")
        state = detect_escalation_state(marker_path=marker)
        assert state.armed is False
        assert "unreadable" in state.reason

    def test_non_object_marker_reports_disarmed(self, tmp_path: Path) -> None:
        marker = _write_marker(tmp_path / "m.json", "[1,2,3]")
        state = detect_escalation_state(marker_path=marker)
        assert state.armed is False
        assert "not a JSON object" in state.reason

    def test_marker_present_but_sudoers_missing_reports_disarmed(
        self, tmp_path: Path,
    ) -> None:
        marker = _write_marker(
            tmp_path / "m.json",
            {
                "sudoers_path": str(tmp_path / "nope" / "sudoers"),
                "escalated_binary": "/usr/bin/sandbox-exec",
                "installed_at": "2026-01-01T00:00:00Z",
                "user": "alice",
            },
        )
        state = detect_escalation_state(marker_path=marker)
        assert state.armed is False
        assert "sudoers file missing" in state.reason
        # Metadata still surfaces so CLI can explain the partial state.
        assert state.escalated_binary == "/usr/bin/sandbox-exec"
        assert state.installer_user == "alice"

    def test_fully_configured_reports_armed(self, tmp_path: Path) -> None:
        sudoers = tmp_path / "intentframe-run"
        sudoers.write_text("# stand-in for sudoers\n")
        marker = _write_marker(
            tmp_path / "m.json",
            {
                "sudoers_path": str(sudoers),
                "escalated_binary": "/usr/bin/sandbox-exec",
                "installed_at": "2026-01-01T00:00:00Z",
                "user": "alice",
            },
        )
        state = detect_escalation_state(marker_path=marker)
        assert state.armed is True
        assert state.sudoers_path == str(sudoers)
        assert state.escalated_binary == "/usr/bin/sandbox-exec"
        assert state.installer_user == "alice"

    def test_health_payload_shape(self, tmp_path: Path) -> None:
        sudoers = tmp_path / "intentframe-run"
        sudoers.write_text("ok")
        marker = _write_marker(
            tmp_path / "m.json",
            {"sudoers_path": str(sudoers), "escalated_binary": "/usr/bin/sandbox-exec"},
        )
        state = detect_escalation_state(marker_path=marker)
        payload = state.as_health_payload()
        # Keys the CLI banner + /system/health response rely on.
        for key in (
            "escalation_armed",
            "reason",
            "marker_path",
            "sudoers_path",
            "escalated_binary",
            "installed_at",
            "installer_user",
        ):
            assert key in payload
        assert payload["escalation_armed"] is True


class TestIsEscalationArmed:
    def test_shorthand_returns_bool(self, monkeypatch, tmp_path: Path) -> None:
        """``is_escalation_armed`` uses the default marker path, which we
        redirect through the module constant for this test."""
        from intentframe_gateway import escalation as esc_mod
        monkeypatch.setattr(
            esc_mod, "DEFAULT_MARKER_PATH", tmp_path / "nope.json",
        )
        assert is_escalation_armed() is False
