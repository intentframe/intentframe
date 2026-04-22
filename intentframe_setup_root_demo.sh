#!/usr/bin/env bash
#
# IntentFrame — root-demo installer  (OPT-IN, OUT-OF-BAND)
#
# This script is NOT part of the normal setup flow.  It installs a
# narrow NOPASSWD sudoers entry that lets the executor's RUN_COMMAND
# subprocess run the macOS kernel sandbox (``sandbox-exec``) as root.
# This is a *demo* capability: useful for showing IntentFrame
# enforcing policy against a fully-privileged executor (reading
# ``/etc/hosts``, listing ``/``, inspecting system logs) without
# running the rest of the stack as root.
#
# What gets installed
# -------------------
#   1. /etc/sudoers.d/intentframe-run  (mode 0440, root:wheel)
#        <user> ALL=(root) NOPASSWD: SETENV: /usr/bin/sandbox-exec
#
#   2. ~/.intentframe/state/root-demo.json   (owned by <user>)
#        JSON marker recording installed_at, sudoers_path,
#        escalated_binary, and user.  The gateway reads this to
#        advertise INTENTFRAME_ESCALATION_ARMED=1 to the executor.
#
# Attack-surface reasoning
# ------------------------
# The sudoers entry is narrow (one exact binary, one user, NOPASSWD)
# but is NOT a hardening layer on its own -- an attacker with direct
# shell access could obviously invoke ``sudo sandbox-exec -p '(version
# 1)(allow default)' /bin/sh``.  The hardening layer is
# ``command_shield`` (and the pipeline's upstream Guardian/AE), which
# already blocks catastrophic patterns including ``\bsudo\b`` and
# direct ``sandbox-exec`` invocations before any RUN_COMMAND reaches
# the executor.  This installer is therefore safe in the intended
# threat model (agent-authored commands filtered upstream) and
# appropriately dangerous in the "hostile local user" model (out of
# scope for a demo).
#
# Uninstall
# ---------
#   sudo bash intentframe_uninstall_root_demo.sh
#
# Usage
# -----
#   sudo bash intentframe_setup_root_demo.sh
#
set -euo pipefail

SUDOERS_PATH="/etc/sudoers.d/intentframe-run"
MARKER_RELPATH=".intentframe/state/root-demo.json"
INSTALLER_VERSION="1"

# ── Identity gates ───────────────────────────────────────────────

if [[ "$(id -u)" -ne 0 ]]; then
    cat >&2 <<'MSG'
ERROR: this installer must run via sudo.

    sudo bash intentframe_setup_root_demo.sh

It needs root to write /etc/sudoers.d/intentframe-run.  The marker
file will be written back to your user's ~/.intentframe/state/.
MSG
    exit 2
fi

if [[ -z "${SUDO_USER:-}" || "${SUDO_USER}" == "root" ]]; then
    cat >&2 <<'MSG'
ERROR: could not resolve the owning user from SUDO_USER.

Run this via ``sudo`` from a regular user shell, not as bare root.
The marker file must be owned by the user who will later run the
gateway; bare root has no ~/.intentframe/ to write to.
MSG
    exit 2
fi

OWNER_USER="$SUDO_USER"
# Resolve the owning user's HOME from dscl (macOS) so we don't rely
# on the sudo-preserved $HOME, which some configurations strip.
if command -v dscl >/dev/null 2>&1; then
    OWNER_HOME="$(dscl . -read "/Users/${OWNER_USER}" NFSHomeDirectory 2>/dev/null \
        | awk 'NR==1{print $2}')"
else
    OWNER_HOME="$(getent passwd "$OWNER_USER" | cut -d: -f6)"
fi
if [[ -z "${OWNER_HOME:-}" || ! -d "$OWNER_HOME" ]]; then
    echo "ERROR: could not resolve HOME for user $OWNER_USER" >&2
    exit 2
fi

MARKER_PATH="${OWNER_HOME}/${MARKER_RELPATH}"

# ── sandbox-exec discovery ───────────────────────────────────────

# Only trust sandbox-exec if it lives in a system-owned path.  A
# hijacked $PATH pointing at ~/bin/sandbox-exec would otherwise let
# a local attacker smuggle arbitrary code into the NOPASSWD slot.
SANDBOX_EXEC="$(command -v sandbox-exec || true)"
if [[ -z "$SANDBOX_EXEC" ]]; then
    echo "ERROR: sandbox-exec not found on PATH -- macOS only." >&2
    exit 2
fi
case "$SANDBOX_EXEC" in
    /usr/bin/*|/usr/sbin/*)
        ;;
    *)
        cat >&2 <<MSG
ERROR: sandbox-exec resolved to a non-system path: $SANDBOX_EXEC

This installer only trusts /usr/bin or /usr/sbin.  Remove the
shadow binary from PATH and re-run.
MSG
        exit 2
        ;;
esac

# ── Build + validate sudoers fragment ────────────────────────────

TMP_SUDOERS="$(mktemp -t intentframe-sudoers.XXXXXX)"
trap 'rm -f "$TMP_SUDOERS"' EXIT

cat >"$TMP_SUDOERS" <<EOF
# IntentFrame root-demo -- installed by intentframe_setup_root_demo.sh
# Grants user '${OWNER_USER}' permission to run the macOS kernel
# sandbox binary as root without a password.  The executor's
# MacOSSandboxEngine prepends 'sudo -n --preserve-env=...' to
# sandbox-exec ONLY when the gateway advertises
# INTENTFRAME_ESCALATION_ARMED=1.
#
# SETENV: is required so the executor can carry PATH / VIRTUAL_ENV /
# PYTHONNOUSERSITE / TMPDIR across the sudo boundary (sudo defaults
# to env_reset, which would otherwise strip them and force the
# sandboxed shell onto system python3 instead of the executor venv).
# NOPASSWD: keeps the invocation non-interactive so the executor can
# wrap commands without prompting.
#
# Remove by running: sudo bash intentframe_uninstall_root_demo.sh
${OWNER_USER} ALL=(root) NOPASSWD: SETENV: ${SANDBOX_EXEC}
EOF
chmod 0440 "$TMP_SUDOERS"

if ! visudo -cf "$TMP_SUDOERS" >/dev/null; then
    echo "ERROR: visudo rejected the generated sudoers fragment:" >&2
    cat "$TMP_SUDOERS" >&2
    exit 3
fi

install -o root -g wheel -m 0440 "$TMP_SUDOERS" "$SUDOERS_PATH"

# ── Marker file (owned by the invoking user) ─────────────────────

INSTALL_TS="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
MARKER_DIR="$(dirname "$MARKER_PATH")"

sudo -u "$OWNER_USER" mkdir -p "$MARKER_DIR"
sudo -u "$OWNER_USER" tee "$MARKER_PATH" >/dev/null <<EOF
{
  "installed_at": "${INSTALL_TS}",
  "installer_version": "${INSTALLER_VERSION}",
  "sudoers_path": "${SUDOERS_PATH}",
  "escalated_binary": "${SANDBOX_EXEC}",
  "user": "${OWNER_USER}"
}
EOF
sudo -u "$OWNER_USER" chmod 0644 "$MARKER_PATH"

# ── Summary ──────────────────────────────────────────────────────

cat <<EOF

IntentFrame root-demo installed.

  user             ${OWNER_USER}
  sudoers          ${SUDOERS_PATH}
  escalated        ${SANDBOX_EXEC}
  marker           ${MARKER_PATH}
  installed_at     ${INSTALL_TS}

The gateway will now advertise INTENTFRAME_ESCALATION_ARMED=1 to the
executor on startup.  Sandbox commands with ``sandbox.escalate: sudo``
(see jarvis_pa/executor_root.yaml) will run under ``sudo -n
sandbox-exec ...`` so the kernel sandbox itself executes as root.

command_shield continues to block agent-authored ``sudo`` and direct
``sandbox-exec`` invocations, so the capability is only usable by
the executor's internal argv builder.

Uninstall: sudo bash intentframe_uninstall_root_demo.sh

EOF
