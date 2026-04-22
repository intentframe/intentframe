#!/usr/bin/env bash
#
# IntentFrame — root-demo uninstaller
#
# Idempotent: safe to re-run.  Removes both artefacts installed by
# intentframe_setup_root_demo.sh:
#
#   1. /etc/sudoers.d/intentframe-run          (needs root)
#   2. ~/.intentframe/state/root-demo.json     (user-space)
#
# After this script runs, the gateway detects no marker and
# advertises INTENTFRAME_ESCALATION_ARMED=0 on next startup, so
# RUN_COMMAND falls back to unprivileged sandbox-exec regardless of
# what sandbox.escalate says in the executor YAML.
#
# Usage
# -----
#   sudo bash intentframe_uninstall_root_demo.sh
#
set -euo pipefail

SUDOERS_PATH="/etc/sudoers.d/intentframe-run"
MARKER_RELPATH=".intentframe/state/root-demo.json"

if [[ "$(id -u)" -ne 0 ]]; then
    cat >&2 <<'MSG'
ERROR: this uninstaller must run via sudo.

    sudo bash intentframe_uninstall_root_demo.sh

It needs root to remove /etc/sudoers.d/intentframe-run.  The marker
file will be cleaned up from your user's ~/.intentframe/state/.
MSG
    exit 2
fi

if [[ -z "${SUDO_USER:-}" || "${SUDO_USER}" == "root" ]]; then
    echo "WARNING: SUDO_USER not set; skipping marker cleanup." >&2
    OWNER_USER=""
else
    OWNER_USER="$SUDO_USER"
fi

# ── Remove sudoers fragment ──────────────────────────────────────

if [[ -f "$SUDOERS_PATH" ]]; then
    rm -f "$SUDOERS_PATH"
    echo "Removed: $SUDOERS_PATH"
else
    echo "Already absent: $SUDOERS_PATH"
fi

# ── Remove marker (as the owning user) ───────────────────────────

if [[ -n "$OWNER_USER" ]]; then
    if command -v dscl >/dev/null 2>&1; then
        OWNER_HOME="$(dscl . -read "/Users/${OWNER_USER}" NFSHomeDirectory 2>/dev/null \
            | awk 'NR==1{print $2}')"
    else
        OWNER_HOME="$(getent passwd "$OWNER_USER" | cut -d: -f6)"
    fi

    if [[ -n "${OWNER_HOME:-}" && -d "$OWNER_HOME" ]]; then
        MARKER_PATH="${OWNER_HOME}/${MARKER_RELPATH}"
        if [[ -f "$MARKER_PATH" ]]; then
            sudo -u "$OWNER_USER" rm -f "$MARKER_PATH"
            echo "Removed: $MARKER_PATH"
        else
            echo "Already absent: $MARKER_PATH"
        fi
    fi
fi

cat <<'EOF'

IntentFrame root-demo uninstalled.

Restart the gateway (intentframe-gateway-cli quit, then relaunch) for
the executor to pick up the disarmed state.  On next spawn it will
see INTENTFRAME_ESCALATION_ARMED=0 and RUN_COMMAND will run
unprivileged.

EOF
