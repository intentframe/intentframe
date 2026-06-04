#!/usr/bin/env bash
# Install all IntentFrame release wheels from GitHub into a disposable venv and
# smoke-test imports. Verifies public release assets resolve and the dependency
# graph closes (transitive deps still come from PyPI).
#
# Usage:
#   ./scripts/github-install/verify_release_install.sh
#   ./scripts/github-install/verify_release_install.sh --tag v0.1.0
#   ./scripts/github-install/verify_release_install.sh --tag v0.1.0 --keep-dir /tmp/if-verify
#
# Docs: scripts/github-install/README.md
set -euo pipefail

REPO="intentframe/intentframe"
TAG="v0.1.0"
PY_VERSION="3.14"
KEEP_DIR=""

usage() {
  cat <<'EOF'
Usage: verify_release_install.sh [--tag TAG] [--repo OWNER/NAME] [--python VERSION] [--keep-dir PATH]

  --tag TAG       GitHub release tag (default: v0.1.0)
  --repo REPO     GitHub owner/repo (default: intentframe/intentframe)
  --python VER    Python for the temp venv (default: 3.14)
  --keep-dir PATH Reuse/create venv at PATH instead of mktemp (for debugging)
  -h, --help      Show this help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --tag) TAG="${2:?}"; shift 2 ;;
    --repo) REPO="${2:?}"; shift 2 ;;
    --python) PY_VERSION="${2:?}"; shift 2 ;;
    --keep-dir) KEEP_DIR="${2:?}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

VERSION="${TAG#v}"
BASE="https://github.com/${REPO}/releases/download/${TAG}"

# Wheel basenames for lockstep 0.1.0-style releases (underscore dist names).
WHEELS=(
  "command_shield-${VERSION}-py3-none-any.whl"
  "intentframe_actor-${VERSION}-py3-none-any.whl"
  "intentframe_bundle_sdk-${VERSION}-py3-none-any.whl"
  "intentframe_client-${VERSION}-py3-none-any.whl"
  "intentframe_components-${VERSION}-py3-none-any.whl"
  "intentframe_core-${VERSION}-py3-none-any.whl"
  "intentframe_credentials-${VERSION}-py3-none-any.whl"
  "intentframe_edge-${VERSION}-py3-none-any.whl"
  "intentframe_executor-${VERSION}-py3-none-any.whl"
  "intentframe_executor_client-${VERSION}-py3-none-any.whl"
  "intentframe_executor_sdk-${VERSION}-py3-none-any.whl"
  "intentframe_native_kit-${VERSION}-py3-none-any.whl"
  "intentframe_policy_registry-${VERSION}-py3-none-any.whl"
  "intentframe_prompt_library-${VERSION}-py3-none-any.whl"
  "intentframe_proxy-${VERSION}-py3-none-any.whl"
  "intentframe_runtime-${VERSION}-py3-none-any.whl"
  "intentframe_server-${VERSION}-py3-none-any.whl"
  "intentframe_supervisor-${VERSION}-py3-none-any.whl"
)

URLS=()
for wheel in "${WHEELS[@]}"; do
  URLS+=("${BASE}/${wheel}")
done

if [ -n "${KEEP_DIR}" ]; then
  WORK="${KEEP_DIR}"
  mkdir -p "${WORK}"
else
  WORK="$(mktemp -d)"
fi

cd "${WORK}"
echo "==> workdir: ${WORK}"
echo "==> release: ${BASE}"
echo "==> python: ${PY_VERSION}"

if [ ! -d .venv ]; then
  uv venv --python "${PY_VERSION}"
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> install ${#URLS[@]} wheels from GitHub release"
uv pip install "${URLS[@]}"

echo "==> verify installed versions and imports"
export EXPECTED_VERSION="${VERSION}"
python - <<'PY'
import importlib
import os
import sys
from importlib.metadata import version

expected = os.environ["EXPECTED_VERSION"]

dists = [
    "command-shield",
    "intentframe-actor",
    "intentframe-bundle-sdk",
    "intentframe-client",
    "intentframe-components",
    "intentframe-core",
    "intentframe-credentials",
    "intentframe-edge",
    "intentframe-executor",
    "intentframe-executor-client",
    "intentframe-executor-sdk",
    "intentframe-native-kit",
    "intentframe-policy-registry",
    "intentframe-prompt-library",
    "intentframe-proxy",
    "intentframe-runtime",
    "intentframe-server",
    "intentframe-supervisor",
]

modules = [
    "command_shield",
    "intentframe_actor",
    "intentframe_bundle_sdk",
    "intentframe_client",
    "intentframe_components",
    "intentframe_core",
    "intentframe_credentials",
    "intentframe_edge",
    "executor",
    "executor_client",
    "executor_sdk",
    "intentframe_native_kit",
    "policy_registry",
    "intentframe_prompt_library",
    "intentframe_proxy",
    "intentframe_server",
    "supervisor",
]

print("Installed distributions:")
for dist in dists:
    got = version(dist)
    if got != expected:
        print(f"  FAIL {dist}: expected {expected}, got {got}", file=sys.stderr)
        sys.exit(1)
    print(f"  ok {dist}=={got}")

print("\nImport smoke test:")
for module in modules:
    importlib.import_module(module)
    print(f"  ok {module}")

print("\nSUCCESS: all IntentFrame release wheels installed and importable")
PY

echo "==> done"
