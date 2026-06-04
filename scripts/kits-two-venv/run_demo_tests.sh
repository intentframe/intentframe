#!/usr/bin/env bash
#
# Run demo tests from the client venv (.venv) against the runtime edge over HTTP.
# Runtime must already be up (start_runtime.sh). Sets INTENTFRAME_*_URL to EDGE_BASE_URL.
#
#   ./scripts/kits-two-venv/run_demo_tests.sh demo/tests/test_attacks.py 1 2 3
#
# Args are passed to client Python (pytest node ids by default). OPENAI_API_KEY is
# required on the runtime process, not in this shell, for Guardian/analysis.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"
_kits_require_repo
_kits_require_client_venv

export INTENTFRAME_CORE_URL="${INTENTFRAME_CORE_URL:-${EDGE_BASE_URL}}"
export INTENTFRAME_POLICY_URL="${INTENTFRAME_POLICY_URL:-${EDGE_BASE_URL}}"
export INTENTFRAME_RESOURCE_URL="${INTENTFRAME_RESOURCE_URL:-${EDGE_BASE_URL}}"

if ! curl -fsS "${EDGE_BASE_URL}/health" >/dev/null 2>&1; then
  echo "Edge not healthy at ${EDGE_BASE_URL}. Start runtime first:" >&2
  echo "  export OPENAI_API_KEY=sk-..." >&2
  echo "  ${SCRIPT_DIR}/start_runtime.sh" >&2
  exit 1
fi

# Invoice attack suites need the attack executor profile in the *runtime*, not dashboard.
if [[ "${1:-}" == *test_attacks* ]] || [[ "${1:-}" == *test_advanced_attacks* ]] || [[ "${1:-}" == *test_redteam* ]]; then
  if [[ "${EXECUTOR_CONFIG:-}" != *executor_attacks* ]]; then
    echo "[run-demo-tests] WARNING: attack tests expect runtime EXECUTOR_CONFIG=*executor_attacks*" >&2
    echo "  Stop runtime, then:" >&2
    echo "  export EXECUTOR_CONFIG=${REPO_ROOT}/demo/config/executor_attacks_hashicorp.yaml" >&2
    echo "  ${SCRIPT_DIR}/start_runtime.sh" >&2
  fi
fi

echo "[run-demo-tests] edge=${EDGE_BASE_URL}"
echo "[run-demo-tests] client=${CLIENT_PYTHON}"
echo "[run-demo-tests] cmd: $*"

cd "${REPO_ROOT}"
if [[ $# -eq 0 ]]; then
  set -- demo/tests/test_attacks.py 1 2 3
fi

exec "${CLIENT_PYTHON}" "$@"
