#!/bin/bash
set -euo pipefail

QUIET=false
[[ "${1:-}" == "--quiet" ]] && QUIET=true

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PRODUCT="macos-appkit-server"
BUILD_DIR="$PROJECT_DIR/.build/release"
APP_DIR="$BUILD_DIR/$PRODUCT.app"
CONTENTS="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS/MacOS"

# Stop any running instance before building so the new binary can replace it cleanly.
# Two instances on the same socket would cause a bind error on relaunch.
# Use -f (full command line match) because macOS truncates process names to 15 chars.
if pgrep -f "$PRODUCT" > /dev/null 2>&1; then
    echo "Stopping running $PRODUCT..."
    pkill -f "$PRODUCT"
    # Wait for the process to actually exit (up to 5s)
    for i in $(seq 1 10); do
        pgrep -f "$PRODUCT" > /dev/null 2>&1 || break
        sleep 0.5
    done
fi

echo "Building $PRODUCT (release)..."
cd "$PROJECT_DIR"
swift build -c release

echo "Updating .app bundle..."
mkdir -p "$MACOS_DIR"

cp "$BUILD_DIR/$PRODUCT" "$MACOS_DIR/"
cp "$PROJECT_DIR/Resources/Info.plist" "$CONTENTS/"

# Sign the bundle. Use a stable dev certificate if available (preserves TCC grants
# across rebuilds). Falls back to ad-hoc which resets permissions on each rebuild.
CERT_NAME="IntentFrame Dev"
if security find-identity -v -p codesigning 2>/dev/null | grep -q "$CERT_NAME"; then
    echo "Signing with '$CERT_NAME' certificate..."
    codesign --force --sign "$CERT_NAME" "$APP_DIR"
else
    echo "Signing ad-hoc (TCC permissions will reset on each rebuild)."
    echo "  Run: bash Scripts/setup-signing.sh  to create a stable dev certificate."
    codesign --force --sign - "$APP_DIR"
fi

echo "Built: $APP_DIR"

if [[ "$QUIET" == false ]]; then
    echo ""
    echo "To run:"
    echo "  $MACOS_DIR/$PRODUCT"
    echo ""
    echo "Or via open:"
    echo "  open $APP_DIR"
fi
