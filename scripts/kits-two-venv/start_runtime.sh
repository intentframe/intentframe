#!/usr/bin/env bash
#
# Bootstrap kits from INTENTFRAME_KITS_DIR, then start supervisor + edge (background).
#
#   export OPENAI_API_KEY=sk-...
#   ./scripts/kits-two-venv/start_runtime.sh
#
# Supervisor env intentionally omits INTENTFRAME_*_URL — services use UDS in RUN_DIR.
# Edge runs from the runtime venv; kit supplies INTENTFRAME_EDGE_CONFIG.
# Pids: harness SUPERVISOR_PID_FILE / EDGE_PID_FILE; product also writes RUN_DIR/supervisor.pid.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"
_kits_require_repo
_kits_require_runtime_venv

# Refresh kit code when the wheel was rebuilt (does not relax runtime constraints).
export KIT_REINSTALL_PACKAGES="${KIT_REINSTALL_PACKAGES:-intentframe-native-kit}"

# shellcheck source=bootstrap_kits.sh
source "${SCRIPT_DIR}/bootstrap_kits.sh"

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "[start-runtime] WARNING: OPENAI_API_KEY is unset — Guardian / analysis may fail" >&2
fi

mkdir -p "${PID_DIR}"
cd "${REPO_ROOT}"

if [[ -f "${SUPERVISOR_PID_FILE}" ]] && kill -0 "$(cat "${SUPERVISOR_PID_FILE}")" 2>/dev/null; then
  echo "[start-runtime] supervisor already running (pid $(cat "${SUPERVISOR_PID_FILE}"))" >&2
  exit 1
fi

echo "[start-runtime] starting supervisor (profile: ${INTENTFRAME_SUPERVISOR_CONFIG})"
echo "[start-runtime] runtime UDS=${RUN_DIR} (default)"
nohup env \
  OPENAI_API_KEY="${OPENAI_API_KEY:-}" \
  INTENTFRAME_CORE_CONFIG="${INTENTFRAME_CORE_CONFIG}" \
  INTENTFRAME_SUPERVISOR_CONFIG="${INTENTFRAME_SUPERVISOR_CONFIG}" \
  EXECUTOR_CONFIG="${EXECUTOR_CONFIG}" \
  INTENTFRAME_EXECUTOR_MODE="${INTENTFRAME_EXECUTOR_MODE:-real}" \
  "${RUNTIME_PYTHON}" -m supervisor.main start \
  > "${PID_DIR}/supervisor.log" 2>&1 &
echo $! > "${SUPERVISOR_PID_FILE}"

echo "[start-runtime] waiting for intentframe-server UDS health"
for _ in $(seq 1 90); do
  if curl -fsS --unix-socket "${RUN_DIR}/intentframe.sock" http://core/health >/dev/null 2>&1; then
    echo "[start-runtime] core healthy"
    break
  fi
  sleep 1
done
if ! curl -fsS --unix-socket "${RUN_DIR}/intentframe.sock" http://core/health >/dev/null 2>&1; then
  echo "[start-runtime] core did not become healthy — see ${PID_DIR}/supervisor.log" >&2
  tail -n 40 "${PID_DIR}/supervisor.log" >&2 || true
  exit 1
fi

if [[ -f "${EDGE_PID_FILE}" ]] && kill -0 "$(cat "${EDGE_PID_FILE}")" 2>/dev/null; then
  echo "[start-runtime] edge already running (pid $(cat "${EDGE_PID_FILE}"))"
else
  echo "[start-runtime] starting edge on ${EDGE_BASE_URL}"
  nohup env \
    INTENTFRAME_EDGE_CONFIG="${INTENTFRAME_EDGE_CONFIG}" \
    INTENTFRAME_EDGE_HOST="${EDGE_HOST}" \
    INTENTFRAME_EDGE_PORT="${EDGE_PORT}" \
    "${RUNTIME_PYTHON}" -m intentframe_edge \
    --config "${INTENTFRAME_EDGE_CONFIG}" \
    --host "${EDGE_HOST}" \
    --port "${EDGE_PORT}" \
    > "${PID_DIR}/edge.log" 2>&1 &
  echo $! > "${EDGE_PID_FILE}"
fi

echo "[start-runtime] waiting for edge HTTP health"
for _ in $(seq 1 60); do
  if curl -fsS "${EDGE_BASE_URL}/health" >/dev/null 2>&1; then
    echo "[start-runtime] edge healthy"
    curl -fsS "${EDGE_BASE_URL}/health" || true
    echo
    echo "[start-runtime] ready — demo tests (client .venv) via edge:"
    echo "  export OPENAI_API_KEY=sk-...   # if not already set for runtime"
    echo "  ${SCRIPT_DIR}/run_demo_tests.sh demo/tests/test_attacks.py 1 2 3"
    echo "[start-runtime] logs: ${PID_DIR}/supervisor.log ${PID_DIR}/edge.log ${HOME}/.intentframe/logs"
    exit 0
  fi
  sleep 1
done

echo "[start-runtime] edge did not become healthy — see ${PID_DIR}/edge.log" >&2
tail -n 40 "${PID_DIR}/edge.log" >&2 || true
exit 1
