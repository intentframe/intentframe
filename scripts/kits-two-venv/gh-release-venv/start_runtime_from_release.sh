#!/usr/bin/env bash
#
# Start the IntentFrame runtime (supervisor + edge) from GitHub *release wheels*.
#
# Mirrors start_runtime.sh, but installs substrate + edge + native kit from the
# v<TAG> GitHub release into .venv-release. Environment and run/log dirs match the
# kits-two-venv harness (default ~/.intentframe/run and ~/.intentframe/logs).
#
#   export OPENAI_API_KEY=sk-...
#   bash scripts/kits-two-venv/gh-release-venv/start_runtime_from_release.sh --tag v0.1.1
#
#   bash scripts/kits-two-venv/stop_runtime.sh
#   bash scripts/kits-two-venv/run_demo_tests.sh demo/tests/test_attacks.py 1 2 3
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../common.sh
source "${SCRIPT_DIR}/../common.sh"
_kits_require_repo

REPO="intentframe/intentframe"
TAG="v0.1.1"

while [ $# -gt 0 ]; do
  case "$1" in
    --tag) TAG="${2:?}"; shift 2 ;;
    --repo) REPO="${2:?}"; shift 2 ;;
    -h|--help)
      echo "Usage: start_runtime_from_release.sh [--tag TAG] [--repo OWNER/NAME]"
      exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

VERSION="${TAG#v}"
BASE="https://github.com/${REPO}/releases/download/${TAG}"

SUPERVISOR_PID_FILE="${GH_RELEASE_SUPERVISOR_PID_FILE}"
EDGE_PID_FILE="${GH_RELEASE_EDGE_PID_FILE}"

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

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required (https://docs.astral.sh/uv/)" >&2
  exit 1
fi

_runtime_already_up() {
  if curl -fsS "${EDGE_BASE_URL}/health" >/dev/null 2>&1; then
    return 0
  fi
  if [[ -f "${RUN_DIR}/intentframe.sock" ]] && \
     curl -fsS --unix-socket "${RUN_DIR}/intentframe.sock" http://core/health >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

if _runtime_already_up; then
  echo "[gh-release-runtime] runtime already healthy (edge or core UDS). Stop first:" >&2
  echo "  bash scripts/kits-two-venv/stop_runtime.sh" >&2
  exit 1
fi

echo "[gh-release-runtime] repo=${REPO} tag=${TAG}"
echo "[gh-release-runtime] venv=${RELEASE_VENV}"

if [[ ! -d "${RELEASE_VENV}" ]]; then
  uv venv "${RELEASE_VENV}" --python 3.14
fi

URLS=()
for wheel in "${WHEELS[@]}"; do
  URLS+=("${BASE}/${wheel}")
done

echo "[gh-release-runtime] installing ${#URLS[@]} release wheels"
uv pip install --python "${RELEASE_PYTHON}" "${URLS[@]}"

echo "[gh-release-runtime] verify imports (substrate + edge + kit)"
"${RELEASE_PYTHON}" -c 'import supervisor, executor, intentframe_server, intentframe_edge, intentframe_proxy, intentframe_native_kit; print("imports ok")'

KIT_PARENT="$("${RELEASE_PYTHON}" -c 'import intentframe_native_kit as k, pathlib; print(pathlib.Path(k.__file__).parent)')"
INTENTFRAME_CORE_CONFIG="${KIT_PARENT}/core.yaml"
INTENTFRAME_SUPERVISOR_CONFIG="${KIT_PARENT}/supervisor_profile.yaml"
INTENTFRAME_EDGE_CONFIG="${KIT_PARENT}/edge_profile.yaml"

for f in "${INTENTFRAME_CORE_CONFIG}" "${INTENTFRAME_SUPERVISOR_CONFIG}" "${INTENTFRAME_EDGE_CONFIG}"; do
  if [[ ! -f "${f}" ]]; then
    echo "[gh-release-runtime] expected profile missing in installed kit: ${f}" >&2
    exit 1
  fi
done

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "[gh-release-runtime] WARNING: OPENAI_API_KEY is unset — Guardian / analysis may fail" >&2
fi

mkdir -p "${GH_RELEASE_PID_DIR}"
cd "${REPO_ROOT}"

if [[ -f "${SUPERVISOR_PID_FILE}" ]] && kill -0 "$(cat "${SUPERVISOR_PID_FILE}")" 2>/dev/null; then
  echo "[gh-release-runtime] harness supervisor wrapper already running (pid $(cat "${SUPERVISOR_PID_FILE}"))" >&2
  exit 1
fi

echo "[gh-release-runtime] starting supervisor (profile: ${INTENTFRAME_SUPERVISOR_CONFIG})"
echo "[gh-release-runtime] runtime UDS=${RUN_DIR} (default)"
nohup env \
  OPENAI_API_KEY="${OPENAI_API_KEY:-}" \
  INTENTFRAME_CORE_CONFIG="${INTENTFRAME_CORE_CONFIG}" \
  INTENTFRAME_SUPERVISOR_CONFIG="${INTENTFRAME_SUPERVISOR_CONFIG}" \
  EXECUTOR_CONFIG="${EXECUTOR_CONFIG}" \
  INTENTFRAME_EXECUTOR_MODE="${INTENTFRAME_EXECUTOR_MODE:-real}" \
  "${RELEASE_PYTHON}" -m supervisor.main start \
  > "${GH_RELEASE_PID_DIR}/supervisor.log" 2>&1 &
echo $! > "${SUPERVISOR_PID_FILE}"

echo "[gh-release-runtime] waiting for intentframe-server UDS health"
for _ in $(seq 1 90); do
  if curl -fsS --unix-socket "${RUN_DIR}/intentframe.sock" http://core/health >/dev/null 2>&1; then
    echo "[gh-release-runtime] core healthy"
    break
  fi
  sleep 1
done
if ! curl -fsS --unix-socket "${RUN_DIR}/intentframe.sock" http://core/health >/dev/null 2>&1; then
  echo "[gh-release-runtime] core did not become healthy — see ${GH_RELEASE_PID_DIR}/supervisor.log" >&2
  tail -n 40 "${GH_RELEASE_PID_DIR}/supervisor.log" >&2 || true
  exit 1
fi

if [[ -f "${EDGE_PID_FILE}" ]] && kill -0 "$(cat "${EDGE_PID_FILE}")" 2>/dev/null; then
  echo "[gh-release-runtime] edge already running (pid $(cat "${EDGE_PID_FILE}"))"
else
  echo "[gh-release-runtime] starting edge on ${EDGE_BASE_URL}"
  nohup env \
    INTENTFRAME_EDGE_CONFIG="${INTENTFRAME_EDGE_CONFIG}" \
    INTENTFRAME_EDGE_HOST="${EDGE_HOST}" \
    INTENTFRAME_EDGE_PORT="${EDGE_PORT}" \
    "${RELEASE_PYTHON}" -m intentframe_edge \
    --config "${INTENTFRAME_EDGE_CONFIG}" \
    --host "${EDGE_HOST}" \
    --port "${EDGE_PORT}" \
    > "${GH_RELEASE_PID_DIR}/edge.log" 2>&1 &
  echo $! > "${EDGE_PID_FILE}"
fi

echo "[gh-release-runtime] waiting for edge HTTP health"
for _ in $(seq 1 60); do
  if curl -fsS "${EDGE_BASE_URL}/health" >/dev/null 2>&1; then
    echo "[gh-release-runtime] edge healthy"
    curl -fsS "${EDGE_BASE_URL}/health" || true
    echo
    echo "[gh-release-runtime] ready — runtime is serving from release wheels (${TAG})."
    echo "  Demo tests (client .venv) via edge:"
    echo "    bash scripts/kits-two-venv/run_demo_tests.sh demo/tests/test_attacks.py 1 2 3"
    echo "  Stop:"
    echo "    bash scripts/kits-two-venv/stop_runtime.sh"
    echo "  Logs: ${GH_RELEASE_PID_DIR}/supervisor.log ${GH_RELEASE_PID_DIR}/edge.log ${HOME}/.intentframe/logs"
    exit 0
  fi
  sleep 1
done

echo "[gh-release-runtime] edge did not become healthy — see ${GH_RELEASE_PID_DIR}/edge.log" >&2
tail -n 40 "${GH_RELEASE_PID_DIR}/edge.log" >&2 || true
exit 1
