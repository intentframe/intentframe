#!/usr/bin/env bash
#
# IntentFrame — uninstall
#
# Removes on-disk state created by IntentFrame. Mirrors the layout
# that intentframe_setup.sh provisions. Does NOT touch the source
# checkout itself — that's `rm -rf` of the repo, your decision.
#
# What this removes (default):
#   ~/.intentframe-venvs/   dedicated venvs (executor + future per-agent)
#   ~/.intentframe/         runtime state: data, logs, run (sockets/PIDs),
#                           email ingestion state, audit chain, etc.
#
# What this does NOT remove unless flagged:
#   --remove-cert    macOS code-signing cert "IntentFrame Dev" from login
#                    keychain. Safe to keep across reinstalls.
#   --remove-keychain-vault
#                    Best-effort removal of Keychain Access entries whose
#                    service starts with "com.intentframe.vault.". macOS
#                    only; requires the user's login keychain to be
#                    unlocked (may prompt).
#
# What this CANNOT remove (platform limitation):
#   macOS TCC grants (Calendar, Contacts, Reminders, etc.). macOS does
#   not expose a programmatic API for third-party apps. To revoke, open
#   System Settings → Privacy & Security and remove per-category.
#
# Running processes:
#   Stop the gateway first (`intentframe-gateway-cli` quit command or
#   kill the PIDs under ~/.intentframe/run/). This script will warn
#   if it detects PID files, but will not attempt to stop services.
#
# Usage:
#   bash intentframe_uninstall.sh                  # interactive confirm
#   bash intentframe_uninstall.sh --yes            # non-interactive
#   bash intentframe_uninstall.sh --executor-venv /custom/path
#   bash intentframe_uninstall.sh --remove-cert
#   bash intentframe_uninstall.sh --remove-keychain-vault
#
set -euo pipefail

CERT_NAME="IntentFrame Dev"
VAULT_SERVICE_PREFIX="com.intentframe.vault"

# ── Arg parsing ──────────────────────────────────────────────────

ASSUME_YES=0
REMOVE_CERT=0
REMOVE_KEYCHAIN_VAULT=0
EXECUTOR_VENV_ARG="${INTENTFRAME_EXECUTOR_VENV:-}"

print_usage() {
    cat <<'USAGE'
Usage: bash intentframe_uninstall.sh [options]

Options:
  --yes, -y                  Skip confirmation prompt.
  --executor-venv PATH       Custom executor venv path to remove.
                             Default: $HOME/.intentframe-venvs/executor
  --remove-cert              Also delete macOS code-signing cert
                             'IntentFrame Dev' from the login keychain.
  --remove-keychain-vault    Also remove Keychain entries whose service
                             starts with 'com.intentframe.vault.' (macOS).
  --dry-run                  Print what would be removed, don't remove.
  -h, --help                 Show this help and exit.
USAGE
}

DRY_RUN=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes) ASSUME_YES=1; shift ;;
        --remove-cert) REMOVE_CERT=1; shift ;;
        --remove-keychain-vault) REMOVE_KEYCHAIN_VAULT=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --executor-venv)
            if [[ $# -lt 2 ]]; then
                echo "ERROR: --executor-venv requires a PATH argument." >&2
                exit 2
            fi
            EXECUTOR_VENV_ARG="$2"; shift 2 ;;
        --executor-venv=*)
            EXECUTOR_VENV_ARG="${1#*=}"; shift ;;
        -h|--help) print_usage; exit 0 ;;
        *)
            echo "ERROR: unknown argument: $1" >&2
            print_usage >&2
            exit 2
            ;;
    esac
done

# ── Identity: refuse bare root, resolve owning user ──────────────
#
# Uninstall must target the same user's HOME that setup provisioned.
# Bare root has nothing under /var/root/.intentframe/ and would be
# a no-op at best and misleading at worst.

if [[ "$(id -u)" -eq 0 && -z "${SUDO_USER:-}" ]]; then
    echo ""
    echo "ERROR: don't run uninstall as bare root."
    echo ""
    echo "  Run it as your regular user, or via:"
    echo "    sudo bash intentframe_uninstall.sh"
    echo ""
    exit 1
fi

OWNER_USER="${SUDO_USER:-$(id -un)}"
if [[ -n "${SUDO_USER:-}" ]]; then
    OWNER_HOME="$(eval echo "~$SUDO_USER")"
else
    OWNER_HOME="$HOME"
fi

run_as_owner() {
    if [[ -n "${SUDO_USER:-}" ]]; then
        sudo -u "$SUDO_USER" -H "$@"
    else
        "$@"
    fi
}

# ── Paths to remove ──────────────────────────────────────────────

if [[ -n "$EXECUTOR_VENV_ARG" ]]; then
    case "$EXECUTOR_VENV_ARG" in
        "~"|"~/"*) EXECUTOR_VENV="$OWNER_HOME${EXECUTOR_VENV_ARG#\~}" ;;
        /*)        EXECUTOR_VENV="$EXECUTOR_VENV_ARG" ;;
        *)
            echo "ERROR: --executor-venv must be absolute (or start with ~)." >&2
            exit 2
            ;;
    esac
else
    EXECUTOR_VENV="$OWNER_HOME/.intentframe-venvs/executor"
fi

VENVS_DIR="$OWNER_HOME/.intentframe-venvs"
STATE_DIR="$OWNER_HOME/.intentframe"

# ── Preview ──────────────────────────────────────────────────────

echo ""
echo "========================================="
echo "  IntentFrame uninstall"
echo "========================================="
echo ""
echo "  Owner user:    $OWNER_USER"
echo "  Owner HOME:    $OWNER_HOME"
echo ""
echo "  Will remove:"
if [[ -e "$EXECUTOR_VENV" ]]; then
    echo "    - $EXECUTOR_VENV (executor venv)"
fi
# If user didn't pass --executor-venv, blow away the whole venvs dir
# so future per-agent venvs get cleaned too.
if [[ -z "$EXECUTOR_VENV_ARG" && -e "$VENVS_DIR" ]]; then
    echo "    - $VENVS_DIR (venvs root; includes any per-agent venvs)"
fi
if [[ -e "$STATE_DIR" ]]; then
    echo "    - $STATE_DIR (runtime state: data, logs, sockets, PID files)"
fi
if [[ $REMOVE_CERT -eq 1 ]]; then
    echo "    - macOS login keychain cert: '$CERT_NAME'"
fi
if [[ $REMOVE_KEYCHAIN_VAULT -eq 1 ]]; then
    echo "    - macOS Keychain entries: service ${VAULT_SERVICE_PREFIX}.*"
fi
echo ""
echo "  Will NOT remove:"
echo "    - source checkout (this repo)"
if [[ $REMOVE_CERT -eq 0 ]]; then
    echo "    - '$CERT_NAME' signing cert (pass --remove-cert to also remove)"
fi
if [[ $REMOVE_KEYCHAIN_VAULT -eq 0 ]]; then
    echo "    - Keychain vault entries (pass --remove-keychain-vault to remove)"
fi
echo "    - macOS TCC grants (remove manually in System Settings)"
echo ""

# ── Running-process warning ──────────────────────────────────────

if [[ -d "$STATE_DIR/run" ]]; then
    found_pids=0
    for pidfile in "$STATE_DIR/run"/*.pid; do
        [[ -e "$pidfile" ]] || continue
        pid="$(cat "$pidfile" 2>/dev/null || true)"
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            if [[ $found_pids -eq 0 ]]; then
                echo "  WARNING: IntentFrame processes appear to be running:"
            fi
            echo "    - $(basename "$pidfile" .pid) (pid $pid)"
            found_pids=1
        fi
    done
    if [[ $found_pids -eq 1 ]]; then
        echo ""
        echo "  Stop them first (quit the gateway CLI), then re-run this script."
        echo "  Removing state while services are live can leave zombies."
        echo ""
        if [[ $ASSUME_YES -eq 0 ]]; then
            exit 1
        else
            echo "  --yes set: proceeding anyway. You are responsible for cleanup."
            echo ""
        fi
    fi
fi

# ── Confirm ──────────────────────────────────────────────────────

if [[ $ASSUME_YES -eq 0 && $DRY_RUN -eq 0 ]]; then
    read -r -p "Proceed? [y/N] " reply
    case "$reply" in
        y|Y|yes|YES) ;;
        *) echo "Aborted."; exit 0 ;;
    esac
fi

# ── Do it ────────────────────────────────────────────────────────

do_rm() {
    local path="$1"
    if [[ ! -e "$path" ]]; then
        echo "  skip (not present): $path"
        return
    fi
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "  would remove: $path"
        return
    fi
    echo "  removing: $path"
    # Use run_as_owner so sudo-invoked uninstall still deletes files
    # the owning user actually owns (rather than failing on perms).
    run_as_owner rm -rf -- "$path"
}

echo ""
echo "Removing filesystem state..."

if [[ -n "$EXECUTOR_VENV_ARG" ]]; then
    # Custom venv path: remove just that, don't touch siblings.
    do_rm "$EXECUTOR_VENV"
else
    # Default layout: nuke the whole ~/.intentframe-venvs/ tree.
    do_rm "$VENVS_DIR"
fi

do_rm "$STATE_DIR"

# ── Optional: signing cert ───────────────────────────────────────

if [[ $REMOVE_CERT -eq 1 ]]; then
    if [[ "$(uname)" != "Darwin" ]]; then
        echo ""
        echo "  --remove-cert ignored (not macOS)."
    else
        echo ""
        echo "Removing signing cert '$CERT_NAME'..."
        # security delete-certificate exits non-zero if cert not present;
        # we swallow that to stay idempotent.
        if [[ $DRY_RUN -eq 1 ]]; then
            echo "  would run: security delete-certificate -c \"$CERT_NAME\""
        else
            if run_as_owner security delete-certificate -c "$CERT_NAME" 2>/dev/null; then
                echo "  removed."
            else
                echo "  not found (or already removed)."
            fi
        fi
    fi
fi

# ── Optional: keychain vault entries ─────────────────────────────

if [[ $REMOVE_KEYCHAIN_VAULT -eq 1 ]]; then
    if [[ "$(uname)" != "Darwin" ]]; then
        echo ""
        echo "  --remove-keychain-vault ignored (not macOS)."
    else
        echo ""
        echo "Removing Keychain vault entries (service prefix ${VAULT_SERVICE_PREFIX}.*)..."
        # `security` doesn't support prefix search directly. Iterate by
        # repeatedly calling delete-generic-password on the first match
        # that starts with our prefix, until nothing matches. Bounded
        # loop so a pathological keychain can't spin forever.
        if [[ $DRY_RUN -eq 1 ]]; then
            echo "  would iterate: security find-generic-password -s <prefix>.* + delete"
        else
            removed=0
            for _ in $(seq 1 200); do
                # Capture service name of any entry whose svce starts
                # with our prefix. dump-keychain is noisy but reliable.
                svc="$(run_as_owner security dump-keychain 2>/dev/null \
                    | awk -F'"' '/"svce"<blob>=/ {print $4}' \
                    | grep -F -m1 "${VAULT_SERVICE_PREFIX}." || true)"
                if [[ -z "$svc" ]]; then
                    break
                fi
                if run_as_owner security delete-generic-password -s "$svc" >/dev/null 2>&1; then
                    echo "  removed: $svc"
                    removed=$((removed + 1))
                else
                    echo "  WARNING: failed to delete: $svc (skipping)"
                    break
                fi
            done
            if [[ $removed -eq 0 ]]; then
                echo "  no matching entries found."
            else
                echo "  total removed: $removed"
            fi
        fi
    fi
fi

# ── Done ─────────────────────────────────────────────────────────

echo ""
echo "========================================="
if [[ $DRY_RUN -eq 1 ]]; then
    echo "  Dry run complete (nothing removed)"
else
    echo "  Uninstall complete"
fi
echo "========================================="
echo ""
if [[ "$(uname)" == "Darwin" ]]; then
    echo "  Manual cleanup (can't be automated):"
    echo "    - TCC grants: System Settings → Privacy & Security →"
    echo "      Calendar/Contacts/Reminders → remove IntentFrame entries."
    if [[ $REMOVE_KEYCHAIN_VAULT -eq 0 ]]; then
        echo "    - Keychain entries: open Keychain Access, search for"
        echo "      '${VAULT_SERVICE_PREFIX}', delete any results."
        echo "      (Or re-run with --remove-keychain-vault.)"
    fi
    if [[ $REMOVE_CERT -eq 0 ]]; then
        echo "    - '$CERT_NAME' signing cert: Keychain Access →"
        echo "      login keychain → search '$CERT_NAME' → delete."
        echo "      (Or re-run with --remove-cert.)"
    fi
    echo ""
fi
echo "  To reinstall:"
echo "    bash intentframe_setup.sh"
echo ""
