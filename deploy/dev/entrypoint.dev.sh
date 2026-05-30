#!/usr/bin/env bash
#
# IntentFrame dev/container bootstrap (HashiCorp Vault, vault-sourced secrets).
#
#   1. start credential-vault   (HashiCorp backend via IF_VAULT_BACKEND/VAULT_*)
#   2. wait for vault /health
#   3. seed secrets into the vault   (seed_vault.py — reads OPENAI_API_KEY, etc.)
#   4. fetch runtime_env from vault and exec supervisor   (inject_and_exec.py)
#
# Unlike deploy/entrypoint.sh (which expects OPENAI_API_KEY to already be in the
# process env), this path proves the full flow: the key is *seeded into* the
# vault, then *fetched from* the vault and injected into the supervisor.
#
set -euo pipefail

RUN_DIR="${INTENTFRAME_RUN_DIR:-${HOME}/.intentframe/run}"
export INTENTFRAME_RUN_DIR="${RUN_DIR}"
VAULT_SOCK="${RUN_DIR}/credential-vault.sock"
export INTENTFRAME_VAULT_SOCKET="${VAULT_SOCK}"
mkdir -p "${RUN_DIR}"

echo "[entrypoint] run_dir=${RUN_DIR} vault_backend=${IF_VAULT_BACKEND:-keyring} vault_addr=${VAULT_ADDR:-<unset>}"

echo "[entrypoint] [1/4] starting credential-vault"
python -m uvicorn intentframe_credentials.server:app \
  --uds "${VAULT_SOCK}" --log-level info &
VAULT_PID=$!

echo "[entrypoint] [2/4] waiting for vault health"
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

echo "[entrypoint] [3/4] seeding secrets into vault"
python /app/deploy/dev/seed_vault.py

SUP_PID=""
shutdown() {
  echo "[entrypoint] shutting down"
  [ -n "${SUP_PID}" ] && kill -TERM "${SUP_PID}" 2>/dev/null || true
  [ -n "${SUP_PID}" ] && wait "${SUP_PID}" 2>/dev/null || true
  kill -TERM "${VAULT_PID}" 2>/dev/null || true   # vault stops last
  wait "${VAULT_PID}" 2>/dev/null || true
}
trap shutdown SIGTERM SIGINT

echo "[entrypoint] [4/4] fetching runtime_env from vault and starting supervisor"
# inject_and_exec.py execs into the supervisor, so SUP_PID becomes the supervisor.
python /app/deploy/dev/inject_and_exec.py &
SUP_PID=$!
wait "${SUP_PID}"
