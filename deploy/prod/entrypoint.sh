#!/usr/bin/env bash
#
# IntentFrame runtime bootstrap.
#
#   1. start credential-vault   (HashiCorp backend via IF_VAULT_BACKEND/VAULT_*)
#   2. wait for vault /health
#   3. exec supervisor          (services per the active profile — minimal by
#                                default: policy-registry, executor,
#                                intentframe-core; all UDS)
#
# The supervisor inherits this process's environment, so OPENAI_API_KEY
# (and anything else the services read) must be present here, as must
# INTENTFRAME_SUPERVISOR_CONFIG when a non-default service graph is wanted.
# Vault is the bootstrap dependency: first up, last down.
#
set -euo pipefail

RUN_DIR="${INTENTFRAME_RUN_DIR:-${HOME}/.intentframe/run}"
VAULT_SOCK="${RUN_DIR}/credential-vault.sock"
mkdir -p "${RUN_DIR}"

echo "[entrypoint] run_dir=${RUN_DIR} vault_backend=${IF_VAULT_BACKEND:-keyring}"

echo "[entrypoint] [1/3] starting credential-vault"
python -m uvicorn intentframe_credentials.server:app \
  --uds "${VAULT_SOCK}" --log-level info &
VAULT_PID=$!

echo "[entrypoint] [2/3] waiting for vault health"
for _ in $(seq 1 60); do
  if curl -fsS --unix-socket "${VAULT_SOCK}" http://vault/health >/dev/null 2>&1; then
    echo "[entrypoint] vault healthy"
    break
  fi
  if ! kill -0 "${VAULT_PID}" 2>/dev/null; then
    echo "[entrypoint] vault process died during startup" >&2
    exit 1
  fi
  sleep 1
done

SUP_PID=""
shutdown() {
  echo "[entrypoint] shutting down"
  [ -n "${SUP_PID}" ] && kill -TERM "${SUP_PID}" 2>/dev/null || true
  [ -n "${SUP_PID}" ] && wait "${SUP_PID}" 2>/dev/null || true
  kill -TERM "${VAULT_PID}" 2>/dev/null || true   # vault stops last
  wait "${VAULT_PID}" 2>/dev/null || true
}
trap shutdown SIGTERM SIGINT

echo "[entrypoint] [3/3] starting supervisor (graph: ${INTENTFRAME_SUPERVISOR_CONFIG:-default minimal})"
python -m supervisor.main start &
SUP_PID=$!
wait "${SUP_PID}"
