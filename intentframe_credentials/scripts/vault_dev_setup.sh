#!/usr/bin/env bash
#
# Spin up a local HashiCorp Vault (dev mode) and configure a *production-like*
# AppRole for the IntentFrame credential backend: a scoped policy plus a role
# with a short, renewable token TTL so the backend's renewal loop is exercised.
#
# This is for local development / integration testing ONLY. Dev mode keeps
# everything in memory and is wiped when the container stops.
#
# Usage:
#   ./scripts/vault_dev_setup.sh            # recreate container + configure
#   eval "$(./scripts/vault_dev_setup.sh)"  # also export VAULT_* into your shell
#
# After running, the script prints the env vars (VAULT_ADDR, VAULT_ROLE_ID,
# VAULT_SECRET_ID, ...) so you can point the backend at AppRole auth.

set -euo pipefail

CONTAINER="${VAULT_CONTAINER:-vault-dev}"
IMAGE="${VAULT_IMAGE:-hashicorp/vault:latest}"
PORT="${VAULT_PORT:-8200}"
ROOT_TOKEN="${VAULT_DEV_ROOT_TOKEN_ID:-dev-root-token}"
KV_MOUNT="${VAULT_KV_MOUNT:-secret}"
PATH_PREFIX="${VAULT_PATH_PREFIX:-intentframe}"
ROLE_NAME="${VAULT_ROLE_NAME:-intentframe}"

# Short, renewable TTLs so the renewal loop fires within seconds and eventually
# hits token_max_ttl, forcing an AppRole re-login (exercises both code paths).
TOKEN_TTL="${VAULT_TOKEN_TTL:-20s}"
TOKEN_MAX_TTL="${VAULT_TOKEN_MAX_TTL:-60s}"

log() { echo "[vault-setup] $*" >&2; }

# -- (re)create the dev container ---------------------------------------------
log "recreating container '$CONTAINER' from $IMAGE"
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER" \
  --cap-add=IPC_LOCK \
  -p "${PORT}:8200" \
  -e "VAULT_DEV_ROOT_TOKEN_ID=${ROOT_TOKEN}" \
  "$IMAGE" >/dev/null

# vault CLI calls inside the container talk to the dev server as root.
vex() { docker exec -e "VAULT_ADDR=http://127.0.0.1:8200" -e "VAULT_TOKEN=${ROOT_TOKEN}" "$CONTAINER" "$@"; }

# -- wait for readiness --------------------------------------------------------
log "waiting for Vault to become ready..."
for _ in $(seq 1 30); do
  if vex vault status >/dev/null 2>&1; then break; fi
  sleep 0.5
done
vex vault status >/dev/null

# -- scoped policy -------------------------------------------------------------
# KV v2 splits data and metadata paths. The backend needs read/write on data
# and read/list/delete on metadata (to remove a secret when its last field is
# deleted). renew-self / lookup-self come from the built-in default policy.
log "writing policy '${ROLE_NAME}'"
vex sh -c "cat <<'POLICY' | vault policy write ${ROLE_NAME} -
path \"${KV_MOUNT}/data/${PATH_PREFIX}/*\" {
  capabilities = [\"create\", \"update\", \"read\", \"delete\"]
}
path \"${KV_MOUNT}/metadata/${PATH_PREFIX}/*\" {
  capabilities = [\"read\", \"list\", \"delete\"]
}
POLICY" >&2

# -- AppRole -------------------------------------------------------------------
log "enabling approle auth method"
vex vault auth enable approle >/dev/null 2>&1 || true

log "creating role '${ROLE_NAME}' (token_ttl=${TOKEN_TTL} token_max_ttl=${TOKEN_MAX_TTL})"
vex vault write "auth/approle/role/${ROLE_NAME}" \
  token_policies="${ROLE_NAME}" \
  token_ttl="${TOKEN_TTL}" \
  token_max_ttl="${TOKEN_MAX_TTL}" \
  secret_id_ttl=0 \
  token_num_uses=0 \
  secret_id_num_uses=0 >/dev/null

ROLE_ID="$(vex vault read -field=role_id "auth/approle/role/${ROLE_NAME}/role-id")"
SECRET_ID="$(vex vault write -field=secret_id -f "auth/approle/role/${ROLE_NAME}/secret-id")"

log "done. AppRole configured."

# -- emit env (so callers can `eval`) -----------------------------------------
cat <<ENV
export VAULT_ADDR=http://127.0.0.1:${PORT}
export VAULT_KV_MOUNT=${KV_MOUNT}
export VAULT_PATH_PREFIX=${PATH_PREFIX}
export VAULT_ROLE_ID=${ROLE_ID}
export VAULT_SECRET_ID=${SECRET_ID}
# Root token (admin tasks only — do NOT use as the app's auth):
# export VAULT_TOKEN=${ROOT_TOKEN}
ENV
