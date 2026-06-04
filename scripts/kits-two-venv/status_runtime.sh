#!/usr/bin/env bash
#
# Read-only health summary for the kits two-venv stack (UDS sockets + core UDS + edge HTTP).
# Always exits 0; prints ok/down per check. Does not start or stop services.
#
#   bash scripts/kits-two-venv/status_runtime.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"
_kits_require_repo

echo "[status] run_dir=${RUN_DIR}"
echo "[status] edge=${EDGE_BASE_URL}"

for sock in policy-registry.sock resource-registry.sock executor.sock intentframe.sock; do
  path="${RUN_DIR}/${sock}"
  if [[ -S "${path}" ]]; then
    echo "[status] socket ok: ${path}"
  else
    echo "[status] socket missing: ${path}"
  fi
done

if curl -fsS --unix-socket "${RUN_DIR}/intentframe.sock" http://core/health >/dev/null 2>&1; then
  echo "[status] core UDS: ok"
else
  echo "[status] core UDS: down"
fi

if curl -fsS "${EDGE_BASE_URL}/health" 2>/dev/null; then
  echo
  echo "[status] edge HTTP: ok"
else
  echo "[status] edge HTTP: down"
fi

if [[ -f "${SUPERVISOR_PID_FILE}" ]]; then
  echo "[status] harness supervisor pid: $(cat "${SUPERVISOR_PID_FILE}")"
fi
if [[ -f "${RUN_DIR}/supervisor.pid" ]]; then
  echo "[status] run_dir supervisor pid: $(cat "${RUN_DIR}/supervisor.pid")"
fi
