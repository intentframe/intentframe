#!/usr/bin/env bash
#
# IntentFrame — first-clone bootstrap
#
# Idempotent: safe to re-run at any point. Picks up where it left off.
#
#   bash intentframe_setup.sh
#
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

CERT_NAME="IntentFrame Dev"
PLATFORM_APP="$REPO_ROOT/macos-appkit-server/.build/release/macos-appkit-server.app"

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
echo "  Start IntentFrame:"
echo "    uv run intentframe-gateway-cli"
echo ""
echo "  On first launch the CLI will ask you to"
echo "  store your OpenAI API key in the vault."
echo ""
echo "  If you were already running the gateway CLI,"
echo "  quit and start it again to pick up changes."
echo ""
