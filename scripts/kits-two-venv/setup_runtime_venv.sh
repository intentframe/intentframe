#!/usr/bin/env bash
#
# Create .venv-runtime with substrate only — no intentframe-native-kit, no [native] extra.
# Freezes runtime-constraints.txt so later kit installs cannot override runtime-owned packages.
#
# Steps: venv → pip install intentframe-supervisor → edge third-party deps only →
# uninstall leftover kit → freeze constraints → strict freeze check → import verify.
#
# Re-run after substrate changes. See kits-two-venv/README.md#script-internals.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"
_kits_require_repo

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required (https://docs.astral.sh/uv/)" >&2
  exit 1
fi

echo "[setup-runtime] repo=${REPO_ROOT}"
echo "[setup-runtime] venv=${RUNTIME_VENV}"

cd "${REPO_ROOT}"

if [[ ! -d "${RUNTIME_VENV}" ]]; then
  uv venv "${RUNTIME_VENV}" --python 3.14
fi

# Substrate only: supervisor -> runtime -> policy-registry + executor + server (+ transitive SDKs).
# Do NOT install intentframe-native-kit, command-shield, or intentframe-supervisor[native] here —
# those arrive via kit wheel install with full dependency resolution under runtime constraints.
uv pip install --python "${RUNTIME_PYTHON}" \
  "${REPO_ROOT}/packages/intentframe-supervisor"

# Edge is not a separate wheel yet; only its third-party deps go into the runtime venv.
uv pip install --python "${RUNTIME_PYTHON}" \
  "httpx>=0.28.1" \
  fastapi \
  "uvicorn[standard]" \
  "pydantic>=2.12.5" \
  "pyyaml>=6.0.3"

mkdir -p "${INTENTFRAME_KITS_DIR}" "${PID_DIR}"

# Drop any kit from a previous bootstrap so constraints describe substrate only.
uv pip uninstall --python "${RUNTIME_PYTHON}" intentframe-native-kit 2>/dev/null || true
uv pip uninstall --python "${RUNTIME_PYTHON}" command-shield 2>/dev/null || true

_kits_freeze_runtime_constraints

echo "[setup-runtime] validate substrate environment"
uv pip freeze --python "${RUNTIME_PYTHON}" --strict

echo "[setup-runtime] verify imports"
"${RUNTIME_PYTHON}" -c 'import supervisor, executor, intentframe_server; print("substrate imports ok")'
if "${RUNTIME_PYTHON}" -c 'import intentframe_native_kit' 2>/dev/null; then
  echo "[setup-runtime] WARNING: intentframe_native_kit is importable — kit should only come from ${INTENTFRAME_KITS_DIR}" >&2
else
  echo "[setup-runtime] intentframe_native_kit not present (expected)"
fi

echo "[setup-runtime] done"
