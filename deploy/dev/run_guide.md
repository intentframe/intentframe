The dev compose now **bundles its own Vault** (dev mode, KV v2 at `secret/`), so
you no longer need a separate `vault-dev` container running. Here's the exact
sequence to run everything end-to-end.

---

## Step 1 — (only if you have a local Vault on port 8200)

The bundled Vault publishes on host port `8200`. If your old standalone
`vault-dev` is still running on `8200`, either stop it:

```bash
docker stop vault-dev
```

…or leave it and publish the bundled Vault on a different host port:

```bash
export VAULT_HOST_PORT=8201
```

The IntentFrame container reaches the bundled Vault by service name
(`http://vault:8200`) over the compose network regardless of the host port.

---

## Step 2 — push your changes to `refactor-substrate`

The Dockerfile.dev clones from GitHub, so **every change the container needs must be on the branch before you build**. That includes deploy files, executor pack wiring, and the HashiCorp demo configs — not just `deploy/dev/`.

```bash
cd /Users/prince/GitHub/orgs/intentframe/intentframe

git add \
  deploy/dev/ \
  demo/config/executor_hashicorp.yaml \
  demo/config/executor_attacks_hashicorp.yaml \
  pyproject.toml \
  executor/server.py \
  executor/config/schema.py \
  executor/config/executor.yaml \
  executor_sdk/packs.py \
  intentframe_native_kit/intentframe_executor_pack_posix/ \
  intentframe_native_kit/intentframe_executor_pack_console/adapters/simulated_user_io.py \
  intentframe_native_kit/intentframe_executor_pack_console/adapters/__init__.py \
  intentframe_native_kit/intentframe_executor_pack_console/adapters/console_user_io.py \
  intentframe_native_kit/intentframe_executor_pack_macos/

git commit -m "executor: config-driven packs + POSIX base for Linux container"
git push origin refactor-substrate
```

If you changed other executor configs (e.g. `jarvis_pa/executor.yaml`), add those too before pushing.

---

## Step 3 — set your env vars

With the bundled Vault, the **only required** var is your OpenAI key:

```bash
export OPENAI_API_KEY=sk-...               # your actual key
```

`VAULT_ADDR` defaults to `http://vault:8200` and `VAULT_TOKEN` to
`dev-root-token` — override them only if you want to use an external Vault.

**If your tests use workspaces** (anything that calls `ResourceRegistryClient()`
/ sets `INTENTFRAME_RESOURCE_URL`), also enable the first-party kit profiles so
the supervisor starts `resource-registry` and the edge exposes `/workspaces`:

```bash
export INTENTFRAME_SUPERVISOR_CONFIG="/app/packages/intentframe-native-kit/intentframe_native_kit/supervisor_profile.yaml"
export INTENTFRAME_EDGE_CONFIG="/app/packages/intentframe-native-kit/intentframe_native_kit/edge_profile.yaml"
```

Leave both unset for the minimal substrate (policy-registry + executor + core).

---

## Step 4 — build and start the containers

```bash
cd /Users/prince/GitHub/orgs/intentframe/intentframe/deploy/dev
docker compose -f docker-compose.dev.yml up --build
```

The build step clones `refactor-substrate` from GitHub fresh every time. Subsequent starts (no code changes) can skip `--build`.

Compose starts `vault` first, waits for it to be healthy, then starts the
runtime. Watch the runtime logs — the expected sequence is:

```
[entrypoint] [1/4] starting credential-vault
[entrypoint] vault healthy
[entrypoint] [3/4] seeding secrets into vault
[seed] stored openai/api_key (runtime_env -> OPENAI_API_KEY)
[entrypoint] [4/4] fetching runtime_env from vault and starting supervisor
[bootstrap] injected 1 runtime_env var(s) from vault: ['OPENAI_API_KEY']
```

Then the supervisor brings up the services in its active profile (minimal
default: policy-registry, executor, intentframe-core — plus resource-registry if
you exported the kit profile), and once `intentframe-core` is healthy, the edge
container starts. The edge health probe takes up to ~90s from cold start.

---

## Step 5 — verify it's up

```bash
curl -fsS http://localhost:8443/health
```

Expected response (minimal default):

```json
{"status":"ok","backends":{"policy-registry":true,"intentframe-core":true}}
```

With the kit profiles enabled (Step 3) the summary also includes
`"resource-registry":true`.

Also confirm the key actually came from HashiCorp (not container env):

```bash
curl -fsS -H "X-Vault-Token: dev-root-token" \
  http://127.0.0.1:8200/v1/secret/data/intentframe/openai
```

You should see the `api_key` field in the `data.data` object.

---

## Step 6 — run your tests from the Mac

In a separate terminal (not inside the container), set the three URL env vars and run tests exactly as you do today:

```bash
export INTENTFRAME_CORE_URL=http://localhost:8443
export INTENTFRAME_POLICY_URL=http://localhost:8443
export INTENTFRAME_RESOURCE_URL=http://localhost:8443

# run any of your existing test harnesses
python -m demo.tests.test_attacks 1 2 3
python -m demo.tests.test_redteam_attacks
```

Your `PolicyRegistryClient()`, `ResourceRegistryClient()`, `IntentFrameClient()`, and `Actor(...)` all pick up these env vars automatically — no test code changes needed.

> `ResourceRegistryClient()` / `INTENTFRAME_RESOURCE_URL` only work when the
> kit profiles were enabled at Step 3; otherwise `/workspaces` returns 404/502.

> **Defense validation works over HTTP; executor side effects are partial.**
> Most attacks block before the executor runs — audit `BLOCK` / `blocked_count`
> is enough. Filesystem sync only matters for ALLOW paths (e.g. redteam attack 16)
> or allowed prelude reads on `/invoices/`. Changing `EXECUTOR_CONFIG`,
> `INTENTFRAME_CORE_CONFIG`, or `INTENTFRAME_EXECUTOR_MODE` requires restarting the container — see
> [README.md §2d](README.md#2d-when-to-restart-the-container),
> [docs/plugin-profiles.md](../../docs/plugin-profiles.md), and
> [§2c](README.md#2c-limitations-when-running-tests-over-http).

---

## Troubleshooting checklist

| Symptom | Check |
|---|---|
| port `8200` already allocated | Another local Vault is bound — `docker stop vault-dev` or set `VAULT_HOST_PORT=8201` |
| `vault: connection refused` at seed step | Bundled Vault didn't come up — check `docker compose -f docker-compose.dev.yml logs vault` |
| `vault authentication failed` | `VAULT_TOKEN` doesn't match the bundled Vault's root token (default `dev-root-token`) |
| edge health check times out | Edge depends on runtime being healthy first; runtime has 90s start window — wait longer or check supervisor logs |
| tests get 401/404 | Edge isn't up yet — wait for the health check to pass |
| `/workspaces` 404 / `resource-registry` missing from `/health` | Kit profiles not enabled — export `INTENTFRAME_SUPERVISOR_CONFIG` + `INTENTFRAME_EDGE_CONFIG` (Step 3) and `up` again |
| `No module named 'supervisor'` | Clone didn't succeed (private repo?) — add `IF_GIT_REPO=https://<TOKEN>@github.com/...` build-arg |