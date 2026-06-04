#!/usr/bin/env bash
#
# Start runtime with the invoice attack executor profile (Linux/hashicorp VFS paths).
# Sets EXECUTOR_CONFIG to demo/config/executor_attacks_hashicorp.yaml, then execs
# start_runtime.sh. Use for test_attacks / test_advanced_attacks / test_redteam suites.
#
#   export OPENAI_API_KEY=sk-...
#   bash scripts/kits-two-venv/start_runtime_attacks.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

export EXECUTOR_CONFIG="${REPO_ROOT}/demo/config/executor_attacks_hashicorp.yaml"
exec "${SCRIPT_DIR}/start_runtime.sh"
