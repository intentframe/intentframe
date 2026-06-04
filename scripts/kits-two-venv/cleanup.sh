#!/usr/bin/env bash
#
# Stop the kits two-venv runtime (stop_runtime.sh) and remove local harness artifacts
# so you can redo setup from a clean slate. Default: harness pid/logs only.
# --full removes venv, wheelhouse, and constraints. See README.md#cleanupsh.
#
#   bash scripts/kits-two-venv/cleanup.sh              # stop + harness pid/logs
#   bash scripts/kits-two-venv/cleanup.sh --artifacts  # + wheelhouse + constraints
#   bash scripts/kits-two-venv/cleanup.sh --full       # + .venv-runtime
#   bash scripts/kits-two-venv/cleanup.sh --full --logs  # also ~/.intentframe/logs
#
# Options:
#   -n, --dry-run     Print removals without deleting
#   -h, --help        Show usage
#   --artifacts       Remove INTENTFRAME_KITS_DIR, kits-build, runtime-constraints.txt
#   --runtime-venv    Remove .venv-runtime
#   --full            --artifacts and --runtime-venv
#   --logs            Remove ~/.intentframe/logs (product logs, not repo-local)
#   --client          Remove .venv (client test venv; re-run uv sync after)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

KITS_BUILD_DIR="${REPO_ROOT}/.intentframe/kits-build"
INTENTFRAME_LOGS_DIR="${HOME}/.intentframe/logs"

DRY_RUN=0
DO_HARNESS=1
DO_ARTIFACTS=0
DO_RUNTIME_VENV=0
DO_LOGS=0
DO_CLIENT=0

usage() {
  cat <<'EOF'
Stop the kits two-venv runtime and remove local harness artifacts.

  bash scripts/kits-two-venv/cleanup.sh              # stop + harness pid/logs
  bash scripts/kits-two-venv/cleanup.sh --artifacts  # + wheelhouse + constraints
  bash scripts/kits-two-venv/cleanup.sh --full       # + .venv-runtime
  bash scripts/kits-two-venv/cleanup.sh --full --logs

Options:
  -n, --dry-run     Print removals without deleting
  --artifacts       Remove kits dir, kits-build, runtime-constraints.txt
  --runtime-venv    Remove .venv-runtime
  --full            --artifacts and --runtime-venv
  --logs            Remove ~/.intentframe/logs
  --client          Remove .venv (re-run uv sync after)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    --artifacts) DO_ARTIFACTS=1; shift ;;
    --runtime-venv) DO_RUNTIME_VENV=1; shift ;;
    --full) DO_ARTIFACTS=1; DO_RUNTIME_VENV=1; shift ;;
    --logs) DO_LOGS=1; shift ;;
    --client) DO_CLIENT=1; shift ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

_rm_path() {
  local label="$1"
  shift
  local path
  for path in "$@"; do
    [[ -e "${path}" || -L "${path}" ]] || continue
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      echo "[cleanup] would remove ${label}: ${path}"
    else
      echo "[cleanup] removing ${label}: ${path}"
      rm -rf "${path}"
    fi
  done
}

echo "[cleanup] repo=${REPO_ROOT}"
if [[ "${DRY_RUN}" -eq 1 ]]; then
  echo "[cleanup] dry-run (no deletions)"
fi

if [[ "${DRY_RUN}" -eq 0 ]]; then
  bash "${SCRIPT_DIR}/stop_runtime.sh"
else
  echo "[cleanup] would run: ${SCRIPT_DIR}/stop_runtime.sh"
fi

if [[ "${DO_HARNESS}" -eq 1 ]]; then
  _rm_path "harness state" "${PID_DIR}"
fi

if [[ "${DO_ARTIFACTS}" -eq 1 ]]; then
  _rm_path "wheelhouse" "${INTENTFRAME_KITS_DIR}"
  _rm_path "kit build staging" "${KITS_BUILD_DIR}"
  _rm_path "runtime constraints" "${RUNTIME_CONSTRAINTS}"
fi

if [[ "${DO_RUNTIME_VENV}" -eq 1 ]]; then
  _rm_path "runtime venv" "${RUNTIME_VENV}"
fi

if [[ "${DO_LOGS}" -eq 1 ]]; then
  _rm_path "intentframe logs" "${INTENTFRAME_LOGS_DIR}"
fi

if [[ "${DO_CLIENT}" -eq 1 ]]; then
  _rm_path "client venv" "${CLIENT_VENV}"
fi

echo "[cleanup] done"
if [[ "${DO_RUNTIME_VENV}" -eq 1 || "${DO_ARTIFACTS}" -eq 1 ]]; then
  echo "[cleanup] redo: setup_runtime_venv.sh → uv sync → publish_kit_wheel.sh → start_runtime.sh"
fi
