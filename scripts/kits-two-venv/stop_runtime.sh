#!/usr/bin/env bash
#
# Stop edge and supervisor started by start_runtime.sh, plus orphaned socket/port holders.
#
#   bash scripts/kits-two-venv/stop_runtime.sh
#
# Order: harness edge pid → RUN_DIR/supervisor.pid (process group) → harness supervisor
# pid → lsof UDS holders → lsof EDGE_PORT → remove stale *.sock → verify edge HTTP down.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

_stop_pidfile() {
  local name="$1"
  local file="$2"
  if [[ ! -f "${file}" ]]; then
    return 0
  fi
  local pid
  pid="$(cat "${file}")"
  if kill -0 "${pid}" 2>/dev/null; then
    echo "[stop-runtime] stopping ${name} (pid ${pid})"
    kill -TERM "${pid}" 2>/dev/null || true
    for _ in $(seq 1 30); do
      kill -0 "${pid}" 2>/dev/null || break
      sleep 0.5
    done
    if kill -0 "${pid}" 2>/dev/null; then
      kill -KILL "${pid}" 2>/dev/null || true
    fi
  fi
  rm -f "${file}"
}

_stop_pgid() {
  local pid="$1"
  if [[ -z "${pid}" ]] || ! kill -0 "${pid}" 2>/dev/null; then
    return 0
  fi
  echo "[stop-runtime] stopping process group (pgid ${pid})"
  kill -TERM -- "-${pid}" 2>/dev/null || kill -TERM "${pid}" 2>/dev/null || true
  for _ in $(seq 1 30); do
    kill -0 "${pid}" 2>/dev/null || break
    sleep 0.5
  done
  if kill -0 "${pid}" 2>/dev/null; then
    kill -KILL -- "-${pid}" 2>/dev/null || kill -KILL "${pid}" 2>/dev/null || true
  fi
}

_stop_socket_holders() {
  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi
  local sock path pid
  for sock in policy-registry.sock resource-registry.sock executor.sock intentframe.sock; do
    path="${RUN_DIR}/${sock}"
    [[ -e "${path}" ]] || continue
    while read -r pid; do
      [[ -n "${pid}" ]] || continue
      echo "[stop-runtime] stopping pid ${pid} (holder of ${sock})"
      kill -TERM "${pid}" 2>/dev/null || true
    done < <(lsof -t "${path}" 2>/dev/null || true)
  done
  sleep 1
}

_stop_edge_port() {
  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi
  local pid
  while read -r pid; do
    [[ -n "${pid}" ]] || continue
    echo "[stop-runtime] stopping pid ${pid} (listener on :${EDGE_PORT})"
    kill -TERM "${pid}" 2>/dev/null || true
  done < <(lsof -ti ":${EDGE_PORT}" 2>/dev/null || true)
}

echo "[stop-runtime] run_dir=${RUN_DIR}"

_stop_pidfile "edge" "${EDGE_PID_FILE}"

if [[ -f "${RUN_DIR}/supervisor.pid" ]]; then
  _stop_pgid "$(cat "${RUN_DIR}/supervisor.pid")"
  rm -f "${RUN_DIR}/supervisor.pid"
fi

_stop_pidfile "supervisor" "${SUPERVISOR_PID_FILE}"

_stop_socket_holders
_stop_edge_port

for sock in policy-registry.sock resource-registry.sock executor.sock intentframe.sock; do
  rm -f "${RUN_DIR}/${sock}"
done

if command -v curl >/dev/null 2>&1; then
  if curl -fsS "${EDGE_BASE_URL}/health" >/dev/null 2>&1; then
    echo "[stop-runtime] WARNING: edge still responds at ${EDGE_BASE_URL} — check for stray processes" >&2
  else
    echo "[stop-runtime] edge down (${EDGE_BASE_URL})"
  fi
fi

echo "[stop-runtime] done"
