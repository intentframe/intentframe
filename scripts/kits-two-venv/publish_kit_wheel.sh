#!/usr/bin/env bash
#
# Build the native kit wheel plus workspace dependency wheels for the local wheelhouse.
#
# Flow: uv build each WHEELHOUSE_PACKAGES entry → .intentframe/kits-build/ →
# copy *.whl to INTENTFRAME_KITS_DIR. Only the primary kit wheel is installed by
# bootstrap_kits.sh; other wheels are --find-links deps for kit Requires-Dist.
#
# Extend WHEELHOUSE_PACKAGES below for additional non-PyPI workspace wheels.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"
_kits_require_repo

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required" >&2
  exit 1
fi

BUILD_DIR="${REPO_ROOT}/.intentframe/kits-build"
mkdir -p "${BUILD_DIR}" "${INTENTFRAME_KITS_DIR}"

# Workspace packages the kit declares that are not on PyPI (wheelhouse for offline/find-links).
WHEELHOUSE_PACKAGES=(
  intentframe-native-kit
  command-shield
)

echo "[publish-kit] building wheelhouse packages: ${WHEELHOUSE_PACKAGES[*]}"
cd "${REPO_ROOT}"

for pkg in "${WHEELHOUSE_PACKAGES[@]}"; do
  echo "[publish-kit]   uv build --package ${pkg}"
  uv build --package "${pkg}" --out-dir "${BUILD_DIR}"
done

echo "[publish-kit] copying wheels -> ${INTENTFRAME_KITS_DIR}"
shopt -s nullglob
for whl in "${BUILD_DIR}"/*.whl; do
  cp -f "${whl}" "${INTENTFRAME_KITS_DIR}/"
  echo "[publish-kit]   $(basename "${whl}")"
done
shopt -u nullglob

if ! compgen -G "${INTENTFRAME_KITS_DIR}/intentframe_native_kit-"*.whl >/dev/null; then
  echo "[publish-kit] missing primary kit wheel intentframe_native_kit-*.whl" >&2
  exit 1
fi

echo "[publish-kit] wheelhouse contents:"
ls -la "${INTENTFRAME_KITS_DIR}/"
