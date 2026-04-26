"""Root-demo escalation capability detection.

The one-time ``intentframe_setup_root_demo.sh`` installer writes two
artefacts:

    * ``/etc/sudoers.d/intentframe-run`` -- the NOPASSWD entry that lets
      the invoking user run ``/usr/bin/sandbox-exec`` as root without
      a password.  This is the authoritative OS-level capability gate.
    * ``~/.intentframe/state/root-demo.json`` -- a user-space marker
      recording *who* installed it, *when*, and *which* sudoers file
      the installer wrote.  Deliberately in user-space so uninstall
      can scrub it without root.

At gateway startup we detect whether both artefacts are present and,
if so, advertise the capability to the executor via the
``INTENTFRAME_ESCALATION_ARMED`` env var.  The executor's ``/health``
endpoint and the sandbox engine's argv wrapper both read that single
env var -- no probing, no shelling out, no runtime drift.

The same helper also feeds the gateway ``/system/health`` ``root_demo``
block so the CLI can render a "Profile: root | Escalation: ARMED"
banner without duplicating detection logic.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MARKER_PATH = Path.home() / ".intentframe" / "state" / "root-demo.json"
DEFAULT_SUDOERS_PATH = Path("/etc/sudoers.d/intentframe-run")


@dataclass(frozen=True)
class EscalationState:
    """Detected state of the root-demo escalation capability."""

    armed: bool
    reason: str
    marker_path: str
    sudoers_path: str
    escalated_binary: str | None = None
    installed_at: str | None = None
    installer_user: str | None = None

    def as_health_payload(self) -> dict[str, Any]:
        """Shape returned in the gateway ``/system/health`` response."""
        return {
            "escalation_armed": self.armed,
            "reason": self.reason,
            "marker_path": self.marker_path,
            "sudoers_path": self.sudoers_path,
            "escalated_binary": self.escalated_binary,
            "installed_at": self.installed_at,
            "installer_user": self.installer_user,
        }


def detect_escalation_state(
    marker_path: Path | None = None,
) -> EscalationState:
    """Return the current root-demo escalation state.

    The state is ``armed=True`` iff **both**:
      1. The marker file exists and parses as JSON.
      2. The sudoers file it points at (or the default) exists on disk.

    Any other outcome reports ``armed=False`` with a human-readable
    ``reason`` suitable for CLI surfacing.  Never raises.
    """
    marker = marker_path or DEFAULT_MARKER_PATH
    marker_s = str(marker)

    if not marker.exists():
        return EscalationState(
            armed=False,
            reason="root-demo not installed (marker file missing)",
            marker_path=marker_s,
            sudoers_path=str(DEFAULT_SUDOERS_PATH),
        )

    try:
        data = json.loads(marker.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("root-demo marker unreadable at %s: %s", marker, exc)
        return EscalationState(
            armed=False,
            reason=f"root-demo marker unreadable: {exc}",
            marker_path=marker_s,
            sudoers_path=str(DEFAULT_SUDOERS_PATH),
        )

    if not isinstance(data, dict):
        return EscalationState(
            armed=False,
            reason="root-demo marker is not a JSON object",
            marker_path=marker_s,
            sudoers_path=str(DEFAULT_SUDOERS_PATH),
        )

    sudoers_path = Path(data.get("sudoers_path") or DEFAULT_SUDOERS_PATH)
    escalated_binary = data.get("escalated_binary")
    installed_at = data.get("installed_at")
    installer_user = data.get("user")

    if not sudoers_path.exists():
        return EscalationState(
            armed=False,
            reason=(
                f"root-demo marker present but sudoers file missing at "
                f"{sudoers_path}"
            ),
            marker_path=marker_s,
            sudoers_path=str(sudoers_path),
            escalated_binary=escalated_binary,
            installed_at=installed_at,
            installer_user=installer_user,
        )

    return EscalationState(
        armed=True,
        reason="sudoers entry and marker present",
        marker_path=marker_s,
        sudoers_path=str(sudoers_path),
        escalated_binary=escalated_binary,
        installed_at=installed_at,
        installer_user=installer_user,
    )


def is_escalation_armed() -> bool:
    """Shorthand for callers that only need the boolean."""
    return detect_escalation_state().armed
