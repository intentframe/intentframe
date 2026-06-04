#!/usr/bin/env bash
#
# Stop edge and supervisor for the kits-two-venv harness and the gh-release-venv
# path, plus orphaned UDS/port holders.
#
#   bash scripts/kits-two-venv/stop_runtime.sh
#
# Stops (best-effort, in order):
#   1. Harness edge wrappers (kits-two-venv + gh-release-venv + legacy pid dirs)
#   2. Product supervisor process group (~/.intentframe/run/supervisor.pid)
#   3. Harness supervisor wrappers
#   4. UDS socket holders, then listeners on EDGE_PORT
#   5. Stale *.sock cleanup and edge health check
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
  pid="$(tr -d '[:space:]' < "${file}")"
  if [[ ! "${pid}" =~ ^[0-9]+$ ]]; then
    rm -f "${file}"
    return 0
  fi
  if kill -0 "${pid}" 2>/dev/null; then
    echo "[stop-runtime] stopping ${name} (pid ${pid}, ${file})"
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
  if [[ -z "${pid}" ]] || [[ ! "${pid}" =~ ^[0-9]+$ ]] || ! kill -0 "${pid}" 2>/dev/null; then
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
  sleep 1
  while read -r pid; do
    [[ -n "${pid}" ]] || continue
    kill -KILL "${pid}" 2>/dev/null || true
  done < <(lsof -ti ":${EDGE_PORT}" 2>/dev/null || true)
}

_harness_edge_pid_files() {
  printf '%s\n' \
    "${EDGE_PID_FILE}" \
    "${GH_RELEASE_EDGE_PID_FILE}" \
    "${GH_RELEASE_PID_DIR_LEGACY}/edge.pid"
}

_harness_supervisor_pid_files() {
  printf '%s\n' \
    "${SUPERVISOR_PID_FILE}" \
    "${GH_RELEASE_SUPERVISOR_PID_FILE}" \
    "${GH_RELEASE_PID_DIR_LEGACY}/supervisor.pid"
}

echo "[stop-runtime] run_dir=${RUN_DIR} edge=${EDGE_BASE_URL}"

while IFS= read -r edge_pid_file; do
  [[ -n "${edge_pid_file}" ]] || continue
  _stop_pidfile "edge" "${edge_pid_file}"
done < <(_harness_edge_pid_files)

if [[ -f "${RUN_DIR}/supervisor.pid" ]]; then
  _stop_pgid "$(tr -d '[:space:]' < "${RUN_DIR}/supervisor.pid")"
  rm -f "${RUN_DIR}/supervisor.pid"
fi

while IFS= read -r sup_pid_file; do
  [[ -n "${sup_pid_file}" ]] || continue
  _stop_pidfile "supervisor wrapper" "${sup_pid_file}"
done < <(_harness_supervisor_pid_files)

_stop_socket_holders
_stop_edge_port

for sock in policy-registry.sock resource-registry.sock executor.sock intentframe.sock; do
  rm -f "${RUN_DIR}/${sock}"
done

if command -v curl >/dev/null 2>&1; then
  for _ in $(seq 1 10); do
    if ! curl -fsS "${EDGE_BASE_URL}/health" >/dev/null 2>&1; then
      echo "[stop-runtime] edge down (${EDGE_BASE_URL})"
      break
    fi
    sleep 0.5
  done
  if curl -fsS "${EDGE_BASE_URL}/health" >/dev/null 2>&1; then
    echo "[stop-runtime] WARNING: edge still responds at ${EDGE_BASE_URL} — check for stray processes" >&2
    echo "[stop-runtime] try: lsof -ti :${EDGE_PORT} | xargs kill -9" >&2
  fi
fi

echo "[stop-runtime] done"
