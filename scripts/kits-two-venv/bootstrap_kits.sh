#!/usr/bin/env bash
#
# Install primary kit wheel(s) from INTENTFRAME_KITS_DIR into the runtime venv with full
# dependency resolution (uv), pinned against runtime constraints so kits cannot override
# substrate packages.
#
# MUST be sourced (exports INTENTFRAME_*_CONFIG into the shell):
#   source scripts/kits-two-venv/bootstrap_kits.sh
#
# Flow: resolve primary wheel → uv pip install (--constraints, --find-links, --strict)
# → freeze --strict → export kit profile paths → verify entry points.
# KITS_INSTALL_DRY_RUN=1 resolves without installing.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"
_kits_require_repo
_kits_require_runtime_venv
_kits_require_runtime_constraints

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required for kit install into the runtime venv" >&2
  return 1 2>/dev/null || exit 1
fi

primary_wheels=()
while IFS= read -r line; do
  [[ -n "${line}" ]] && primary_wheels+=( "${line}" )
done < <(_kits_primary_wheels || true)

if [[ ${#primary_wheels[@]} -eq 0 ]]; then
  echo "No primary kit wheel in INTENTFRAME_KITS_DIR=${INTENTFRAME_KITS_DIR}" >&2
  echo "Run: ${SCRIPT_DIR}/publish_kit_wheel.sh" >&2
  echo "Or set KIT_WHEELS='path/to/your_kit.whl'" >&2
  return 1 2>/dev/null || exit 1
fi

echo "[bootstrap-kits] runtime constraints: ${RUNTIME_CONSTRAINTS}"
echo "[bootstrap-kits] wheelhouse (find-links): ${INTENTFRAME_KITS_DIR}"
echo "[bootstrap-kits] installing ${#primary_wheels[@]} primary kit wheel(s) with deps (no substrate overrides)"

if [[ "${KITS_INSTALL_DRY_RUN:-}" == "1" ]]; then
  echo "[bootstrap-kits] dry-run only (KITS_INSTALL_DRY_RUN=1)"
  uv pip install --python "${RUNTIME_PYTHON}" \
    --constraints "${RUNTIME_CONSTRAINTS}" \
    --find-links "${INTENTFRAME_KITS_DIR}" \
    --dry-run \
    --strict \
    "${primary_wheels[@]}"
  return 0 2>/dev/null || exit 0
fi

for whl in "${primary_wheels[@]}"; do
  echo "[bootstrap-kits]   ${whl}"
done

install_args=(
  --python "${RUNTIME_PYTHON}"
  --constraints "${RUNTIME_CONSTRAINTS}"
  --find-links "${INTENTFRAME_KITS_DIR}"
  --strict
)
# Optional: KIT_REINSTALL_PACKAGES="intentframe-native-kit acme-kit" to refresh kit code only.
if [[ -n "${KIT_REINSTALL_PACKAGES:-}" ]]; then
  # shellcheck disable=SC2206
  for pkg in ${KIT_REINSTALL_PACKAGES}; do
    install_args+=( --reinstall-package "${pkg}" )
  done
fi
uv pip install "${install_args[@]}" "${primary_wheels[@]}"

echo "[bootstrap-kits] post-install environment check"
uv pip freeze --python "${RUNTIME_PYTHON}" --strict

KIT_PARENT="$(_kits_kit_parent)"
export INTENTFRAME_CORE_CONFIG="${INTENTFRAME_CORE_CONFIG:-${KIT_PARENT}/core.yaml}"
export INTENTFRAME_SUPERVISOR_CONFIG="${INTENTFRAME_SUPERVISOR_CONFIG:-${KIT_PARENT}/supervisor_profile.yaml}"
export INTENTFRAME_EDGE_CONFIG="${INTENTFRAME_EDGE_CONFIG:-${KIT_PARENT}/edge_profile.yaml}"
export EXECUTOR_CONFIG
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"

for f in "${INTENTFRAME_CORE_CONFIG}" "${INTENTFRAME_SUPERVISOR_CONFIG}" "${INTENTFRAME_EDGE_CONFIG}" "${EXECUTOR_CONFIG}"; do
  if [[ ! -f "${f}" ]]; then
    echo "[bootstrap-kits] missing config: ${f}" >&2
    return 1 2>/dev/null || exit 1
  fi
done

echo "[bootstrap-kits] INTENTFRAME_CORE_CONFIG=${INTENTFRAME_CORE_CONFIG}"
echo "[bootstrap-kits] INTENTFRAME_SUPERVISOR_CONFIG=${INTENTFRAME_SUPERVISOR_CONFIG}"
echo "[bootstrap-kits] INTENTFRAME_EDGE_CONFIG=${INTENTFRAME_EDGE_CONFIG}"
echo "[bootstrap-kits] EXECUTOR_CONFIG=${EXECUTOR_CONFIG}"
echo "[bootstrap-kits] entry points:"
"${RUNTIME_PYTHON}" -c "
from importlib.metadata import entry_points
for g in ('intentframe.bundles', 'intentframe.executor_packs'):
    names = sorted(ep.name for ep in entry_points(group=g))
    print(f'  {g}: {names}')
"
