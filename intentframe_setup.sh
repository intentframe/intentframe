#!/usr/bin/env bash
#
# IntentFrame — first-clone bootstrap
#
# Idempotent: safe to re-run at any point. Picks up where it left off.
# An existing executor venv is never overwritten; re-running preserves
# whatever packages the agent has already installed into it.
#
#   bash intentframe_setup.sh
#   bash intentframe_setup.sh --executor-venv /custom/path/executor
#   INTENTFRAME_EXECUTOR_VENV=/custom/path bash intentframe_setup.sh
#
# Uninstall: bash intentframe_uninstall.sh
#
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

CERT_NAME="IntentFrame Dev"
PLATFORM_APP="$REPO_ROOT/macos-appkit-server/.build/release/macos-appkit-server.app"

# ── Arg parsing ──────────────────────────────────────────────────

EXECUTOR_VENV_ARG="${INTENTFRAME_EXECUTOR_VENV:-}"

print_usage() {
    cat <<'USAGE'
Usage: bash intentframe_setup.sh [options]

Options:
  --executor-venv PATH   Absolute path for the executor venv.
                         Default: $HOME/.intentframe-venvs/executor
                         Also accepts the INTENTFRAME_EXECUTOR_VENV env var.
                         The path MUST NOT live under ~/.intentframe (that
                         subpath is denied by the sandbox; exec would fail).
  -h, --help             Show this help and exit.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --executor-venv)
            if [[ $# -lt 2 ]]; then
                echo "ERROR: --executor-venv requires a PATH argument." >&2
                exit 2
            fi
            EXECUTOR_VENV_ARG="$2"
            shift 2
            ;;
        --executor-venv=*)
            EXECUTOR_VENV_ARG="${1#*=}"
            shift
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        *)
            echo "ERROR: unknown argument: $1" >&2
            print_usage >&2
            exit 2
            ;;
    esac
done

# ── Identity: refuse bare root, resolve owning user ──────────────
#
# The executor venv, the gateway venv, and the runtime state under
# ~/.intentframe/ must all be owned by a single, well-defined user
# (the one who will later run the gateway). Running setup as bare
# root would create root-owned artifacts that the runtime user
# can't touch. Running setup under `sudo` is tolerated: we honor
# SUDO_USER so created files are owned by the invoking user.
#
# The executor itself can still run as root later — it just needs
# to know which user's ~/.intentframe-venvs/executor to look at.
# That resolution lives in executor/sandbox/venv.py and uses the
# same SUDO_USER → uid HOME fallback chain.

if [[ "$(id -u)" -eq 0 && -z "${SUDO_USER:-}" ]]; then
    echo ""
    echo "ERROR: don't run setup as bare root."
    echo ""
    echo "  Run it as your regular user, or via:"
    echo "    sudo bash intentframe_setup.sh"
    echo ""
    echo "  Bare-root setup would create root-owned venvs that the"
    echo "  runtime user can't use."
    exit 1
fi

OWNER_USER="${SUDO_USER:-$(id -un)}"
if [[ -n "${SUDO_USER:-}" ]]; then
    OWNER_HOME="$(eval echo "~$SUDO_USER")"
else
    OWNER_HOME="$HOME"
fi

# Helper: run a command as the owning user, whether or not we were
# invoked via sudo. Keeps file ownership consistent across both
# invocation modes.
run_as_owner() {
    if [[ -n "${SUDO_USER:-}" ]]; then
        sudo -u "$SUDO_USER" -H "$@"
    else
        "$@"
    fi
}

# ── 1. uv ────────────────────────────────────────────────────────

if ! command -v uv &>/dev/null; then
    echo "uv not found — installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
echo "uv: $(uv --version)"

# ── 2. Python workspace (.venv + all deps) ───────────────────────

cd "$REPO_ROOT"
echo ""
echo "Syncing Python workspace..."
uv sync
echo "Python workspace ready."

# ── 2a. Executor venv (dedicated, isolated from <repo>/.venv) ────
#
# Agent-driven `pip install X` and `python foo.py` through the
# sandboxed RUN_COMMAND must not touch <repo>/.venv (the gateway's
# venv) or user-site. A dedicated venv at ~/.intentframe-venvs/executor
# gives those installs an isolated home.
#
# Path chosen outside ~/.intentframe/ on purpose: ~/.intentframe is
# in NON_NEGOTIABLE_DENY_ACCESS (runtime internals — audit DBs, PID
# files, credential-adjacent state) and reads are denied under every
# sandbox template. A venv inside that tree would fail to exec its
# own python3. ~/.intentframe-venvs/ is the sibling directory reserved
# for agent-reachable execution environments.
#
# Provisioned with `uv venv --seed` so pip/setuptools/wheel are
# installed inside — otherwise `pip install` inside the sandbox
# would fail (uv's default venv is pip-less).
#
# Override path via:
#   --executor-venv PATH          (flag)
#   INTENTFRAME_EXECUTOR_VENV     (env var)
#   sandbox.executor_venv_path    (executor.yaml — runtime)
# Useful for daemon deployments (e.g. /var/lib/intentframe-venvs/executor).
#
# Idempotency: if bin/python3 (or bin/python) already exists at the
# target path, we leave the venv untouched. Re-running setup never
# clobbers packages an agent has installed. To force a rebuild, run
# intentframe_uninstall.sh first (or rm -rf the venv path yourself).

if [[ -n "$EXECUTOR_VENV_ARG" ]]; then
    # Accept absolute paths or explicit ~ references; expand ~ against
    # OWNER_HOME so sudo-invoked setups still target the real user.
    case "$EXECUTOR_VENV_ARG" in
        "~"|"~/"*) EXECUTOR_VENV="$OWNER_HOME${EXECUTOR_VENV_ARG#\~}" ;;
        /*)        EXECUTOR_VENV="$EXECUTOR_VENV_ARG" ;;
        *)
            echo "ERROR: --executor-venv must be absolute (or start with ~)." >&2
            echo "  got: $EXECUTOR_VENV_ARG" >&2
            exit 2
            ;;
    esac
else
    EXECUTOR_VENV="$OWNER_HOME/.intentframe-venvs/executor"
fi

# Guardrail: refuse a venv path nested under ~/.intentframe — the
# sandbox deny-access rule would make exec of bin/python3 fail at
# runtime. Surface the mistake here, not at first RUN_COMMAND.
case "$EXECUTOR_VENV/" in
    "$OWNER_HOME/.intentframe/"*)
        echo "" >&2
        echo "ERROR: executor venv path sits under ~/.intentframe/" >&2
        echo "  path: $EXECUTOR_VENV" >&2
        echo "" >&2
        echo "  That subpath is denied by NON_NEGOTIABLE_DENY_ACCESS in the" >&2
        echo "  sandbox, so exec of the venv's python3 would fail with" >&2
        echo "  'Operation not permitted' under every template." >&2
        echo "" >&2
        echo "  Pick a path outside ~/.intentframe/, e.g." >&2
        echo "    ~/.intentframe-venvs/executor   (default)" >&2
        echo "    /var/lib/intentframe-venvs/executor" >&2
        exit 2
        ;;
esac

echo ""
if [[ -x "$EXECUTOR_VENV/bin/python3" || -x "$EXECUTOR_VENV/bin/python" ]]; then
    echo "Executor venv already present (not overwritten): $EXECUTOR_VENV"
else
    echo "Provisioning executor venv: $EXECUTOR_VENV"
    run_as_owner mkdir -p "$(dirname "$EXECUTOR_VENV")"
    run_as_owner uv venv --seed "$EXECUTOR_VENV"
    echo "Executor venv ready."
fi

# ── 3. Swift platform server (macOS only) ────────────────────────

if [[ "$(uname)" != "Darwin" ]]; then
    # Non-macOS: skip platform server, print summary and exit.
    echo ""
    echo "========================================="
    echo "  Setup complete (non-macOS)"
    echo "========================================="
    echo ""
    echo "  Platform server is macOS-only; native"
    echo "  features (Calendar, Contacts, Reminders)"
    echo "  are unavailable on this OS."
    echo ""
    echo "  Gateway venv:    $REPO_ROOT/.venv"
    echo "  Executor venv:   $EXECUTOR_VENV"
    echo ""
    echo "  Start IntentFrame:"
    echo "    uv run intentframe-gateway-cli"
    echo ""
    echo "  On first launch the CLI will ask you to"
    echo "  store your OpenAI API key in the vault."
    echo ""
    exit 0
fi

# ── 3a. Xcode / Swift toolchain ──────────────────────────────────

if ! command -v swift &>/dev/null; then
    echo ""
    echo "ERROR: Swift toolchain not found."
    echo ""
    echo "  Install Xcode Command Line Tools first:"
    echo "    xcode-select --install"
    echo ""
    echo "  Then re-run:  bash intentframe_setup.sh"
    exit 1
fi

# ── 3b. Code-signing certificate ─────────────────────────────────
#
# A stable signing identity keeps macOS TCC grants (Calendar,
# Contacts, Reminders) across rebuilds. Without it every build
# resets permissions and macOS re-prompts.
#
# setup-signing.sh creates a self-signed cert in the login keychain.
# It may trigger a one-time keychain access dialog — the user must
# run it in their own terminal so they can interact with the prompt.

if ! security find-identity -v -p codesigning 2>/dev/null | grep -q "$CERT_NAME"; then
    echo ""
    echo "────────────────────────────────────────"
    echo "  Code-signing certificate not found"
    echo "────────────────────────────────────────"
    echo ""
    echo "  IntentFrame needs a stable signing identity so macOS"
    echo "  doesn't re-prompt for Calendar/Contacts/Reminders"
    echo "  permissions on every rebuild."
    echo ""
    echo "  Run this command (one-time), then re-run this script:"
    echo ""
    echo "    bash macos-appkit-server/Scripts/setup-signing.sh"
    echo ""
    echo "  You may see a keychain dialog — click 'Always Allow'."
    echo "  If Keychain Access opens, find '$CERT_NAME',"
    echo "  double-click → Trust → Code Signing → 'Always Trust'."
    echo ""
    echo "  After that, re-run:"
    echo ""
    echo "    bash intentframe_setup.sh"
    echo ""
    exit 1
fi

echo ""
echo "Signing certificate '$CERT_NAME' found."

# ── 3c. Build the Swift platform server ──────────────────────────

echo "Building platform server..."
bash "$REPO_ROOT/macos-appkit-server/Scripts/bundle.sh" --quiet

# ── 3d. Verify the .app is where the gateway expects it ──────────

if [[ ! -d "$PLATFORM_APP" ]]; then
    echo ""
    echo "ERROR: Platform server build succeeded but .app not found at:"
    echo "  $PLATFORM_APP"
    echo ""
    echo "  The gateway looks for the bundle at this path."
    echo "  Check macos-appkit-server/Scripts/bundle.sh output above."
    exit 1
fi

echo ""
echo "Platform server verified: $PLATFORM_APP"

# ── Done ──────────────────────────────────────────────────────────

echo ""
echo "========================================="
echo "  Setup complete!"
echo "========================================="
echo ""
echo "  Gateway venv:    $REPO_ROOT/.venv"
echo "  Executor venv:   $EXECUTOR_VENV"
echo ""
echo "  Start IntentFrame:"
echo "    uv run intentframe-gateway-cli"
echo ""
echo "  On first launch the CLI will ask you to"
echo "  store your OpenAI API key in the vault."
echo ""
echo "  If you were already running the gateway CLI,"
echo "  quit and start it again to pick up changes."
echo ""
echo "  To reset the executor venv (e.g. after bad installs):"
echo "    rm -rf \"$EXECUTOR_VENV\" && bash intentframe_setup.sh"
echo ""
echo "  To uninstall IntentFrame (state + venv):"
echo "    bash intentframe_uninstall.sh"
echo ""
