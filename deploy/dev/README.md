# IntentFrame dev container (HashiCorp Vault, vault-sourced secrets)

Run the **whole IntentFrame runtime in a container built from a GitHub branch**
(default `refactor-substrate`), backed by your **existing host HashiCorp Vault**,
then run your local tests against it.

This is the *dev* counterpart to `../prod/` (the production B2B deploy). The key
difference is the secret flow:

| | `deploy/prod/` | `deploy/dev/` (this) |
|---|---|---|
| Image source | local working tree (`COPY .`) | `git clone` a GitHub branch |
| OpenAI key | passed in env, inherited by supervisor | **seeded into Vault, then fetched from Vault** and injected |
| Vault | your cluster | **bundled** dev Vault service (or override to external) |

## Flow

```
┌─ vault (HashiCorp, dev mode) ──────────────────────────────┐
│ KV v2 at secret/   ◄── seeded ──┐        ▲                 │
└─────────────────────────────────┼────────┼─────────────────┘
                                   │        │ fetch
┌─ intentframe-runtime container ──┼────────┼────────────────┐
│ entrypoint.dev.sh                │        │                │
│  1. credential-vault   (IF_VAULT_BACKEND=hashicorp)        │
│  2. wait /health                                           │
│  3. seed_vault.py        OPENAI_API_KEY ─┘                 │
│        (runtime_env, env_name=OPENAI_API_KEY)              │
│  4. inject_and_exec.py   Vault ─► runtime_env ─► supervisor│
│        policy-registry / resource-registry /              │
│        executor / intentframe-core   (all UDS)            │
└───────────────┬─────────────────────────────────────────────┘
                │ if-run volume (sockets)
┌───────────────▼─ intentframe-edge container ──────────────┐
│ HTTP :8443  →  policy / resource / core sockets           │
└───────────────┬─────────────────────────────────────────────┘
                │ HTTP
       your Mac: tests / agents  (base_url = http://localhost:8443)
```

`OPENAI_API_KEY` is **dropped from the env** before the fetch in step 4, so the
value the supervisor (and `intentframe-core`) sees provably comes from Vault.

## Prerequisites

Just Docker. The compose bundles a dev-mode HashiCorp Vault (auto-initialised,
auto-unsealed, KV v2 mounted at `secret/`), so no external Vault is required.
The runtime waits for it to be healthy before seeding.

> Using an **external** Vault instead? Set `VAULT_ADDR`
> (e.g. `http://host.docker.internal:8200`) and `VAULT_TOKEN` (or
> `VAULT_ROLE_ID` + `VAULT_SECRET_ID`); it must have a KV v2 engine at
> `VAULT_KV_MOUNT` (default `secret`).

## 1. Build + run

```bash
cd deploy/dev

export OPENAI_API_KEY=sk-...
docker compose -f docker-compose.dev.yml up --build
```

For running tests from another terminal, prefer detached mode — see [Logs](#logs).

> If you already run a local Vault on host port `8200`, either stop it or set
> `VAULT_HOST_PORT=8201` so the bundled Vault publishes on a free port.

Private repo? Pass an authenticated clone URL:

```bash
export IF_GIT_REPO=https://<TOKEN>@github.com/intentframe/intentframe.git
# (optional) export IF_GIT_BRANCH=refactor-substrate
docker compose -f docker-compose.dev.yml up --build
```

Verify the edge and backends are healthy:

```bash
curl -fsS http://localhost:8443/health
# → {"status":"ok","backends":{"policy-registry":true,"resource-registry":true,"intentframe-core":true}}
```

Confirm the key really came from Vault — the runtime logs show:

```
[seed] stored openai/api_key (runtime_env -> OPENAI_API_KEY)
[bootstrap] injected 1 runtime_env var(s) from vault: ['OPENAI_API_KEY']
```

## 2. Run your tests from the Mac

The registry/runtime clients accept a `base_url` and also read it from the
environment, so existing harnesses run unmodified — just point them at the edge.
The executor config to use depends on which test suite you're running:

### 2a. Dashboard + basic pipeline tests

```bash
# default EXECUTOR_CONFIG (executor_hashicorp.yaml — mounts demo_data)
cd deploy/dev
export OPENAI_API_KEY=sk-...
docker compose -f docker-compose.dev.yml up --build

# Mac:
export INTENTFRAME_CORE_URL=http://localhost:8443
export INTENTFRAME_POLICY_URL=http://localhost:8443
export INTENTFRAME_RESOURCE_URL=http://localhost:8443
python demo/demo_dashboard.py
```

### 2b. Invoice attack suites (`test_attacks`, `test_advanced_attacks`, `test_redteam_attacks`)

These tests populate `demo_data/attack_invoices_sandbox` per-attack and register
a workspace that points at that subdirectory. The executor config must match.

```bash
# override EXECUTOR_CONFIG before up:
export EXECUTOR_CONFIG=demo/config/executor_attacks_hashicorp.yaml
export OPENAI_API_KEY=sk-...
docker compose -f docker-compose.dev.yml up --build

# Mac:
export INTENTFRAME_CORE_URL=http://localhost:8443
export INTENTFRAME_POLICY_URL=http://localhost:8443
export INTENTFRAME_RESOURCE_URL=http://localhost:8443
python demo/tests/test_attacks.py 1 2 3
python demo/tests/test_advanced_attacks.py
python demo/tests/test_redteam_attacks.py
```

> Mixing configs is the most common footgun — running attack tests against the
> dashboard config (or vice versa) causes VFS mount mismatches where `READ_FILE`
> returns "temporarily unavailable" even though Guardian decisions are correct.
> Each test prints an ALERT banner stating which config the supervisor must be
> running with; if it doesn't match, restart the stack with the right
> `EXECUTOR_CONFIG`.

## 3. Root dry-run tests against the container

The root-demo attack/benign/gray_area sweeps can run against the container in
**dry-run mode**. Dry-run exercises the full pipeline (policy → deterministic
gates → Analysis Engine → Guardian → Actor/server path) but replaces only the
final executor with an in-process synthetic one, so no real commands are run.
This is the correct mode for this Linux container.

**Step 1 — start the runtime in dry-run + root context:**

```bash
cd deploy/dev
export OPENAI_API_KEY=sk-...
export INTENTFRAME_EXECUTOR_MODE=dry_run
export INTENTFRAME_DRY_RUN_CONTEXT=root
docker compose -f docker-compose.dev.yml up --build
```

`INTENTFRAME_DRY_RUN_CONTEXT=root` makes the runtime's dry-run executor report
`uid=0` so the root-demo runner's preflight (`RUN_COMMAND whoami`) accepts the
response and Guardian reasons in a root context. It has no effect when
`INTENTFRAME_EXECUTOR_MODE=real`.

**Step 2 — run the suites from the Mac (containers must be up first):**

```bash
export INTENTFRAME_CORE_URL=http://localhost:8443
export INTENTFRAME_POLICY_URL=http://localhost:8443
export INTENTFRAME_RESOURCE_URL=http://localhost:8443

# attacks sweep
python demo/tests/root_demo/test_attacks.py

# benign sweep (utility counterpart)
python demo/tests/root_demo/test_benign.py \
  --policy demo/tests/root_demo/test_policy_root_benign.yaml

# per-tactic subsets
python demo/tests/root_demo/test_attacks_persistence.py
python demo/tests/root_demo/test_attacks_reason_lies.py

# gray area
python demo/tests/root_demo/test_gray_area.py \
  --policy demo/tests/root_demo/test_policy_root_admin_assistant.yaml
```

> **Real root mode (`sudo -n sandbox-exec`, real stdout) is macOS-only** and
> cannot run in this Linux container — `sandbox-exec` and the macOS executor
> pack are not present. Run real root on your Mac host directly
> (see `demo/tests/root_demo/README.md §2c/2d`).

| Mode | Against this container | Why |
|---|---|---|
| Root **dry-run** (attack/benign/gray_area sweeps) | ✅ | Pure pipeline; no host commands needed |
| **Real root** (`sudo -n sandbox-exec`, real stdout) | ❌ | macOS-only; run on Mac host |

## Logs

Run the stack in the background so you can tail logs from another terminal
(foreground `up` attaches to stdout; **Ctrl+C stops the whole stack**):

```bash
cd deploy/dev
docker compose -f docker-compose.dev.yml up -d --build
```

### Compose log stream (bootstrap + uvicorn stdout)

All services:

```bash
docker compose -f docker-compose.dev.yml logs -f
```

One service:

```bash
docker compose -f docker-compose.dev.yml logs -f intentframe-runtime
docker compose -f docker-compose.dev.yml logs -f intentframe-edge
docker compose -f docker-compose.dev.yml logs -f vault
```

### Per-service log files inside the runtime container

The supervisor writes each supervised service to its own file under
`/home/intentframe/.intentframe/logs/` (on the `if-data` volume):

| File | Service |
|---|---|
| `intentframe-core.log` | Pipeline / Guardian / dry-run or executor bridge |
| `policy-registry.log` | Policy registry |
| `resource-registry.log` | Resource registry |
| `executor.log` | Executor (only when `INTENTFRAME_EXECUTOR_MODE=real`) |

Tail **intentframe-core** (most useful while running tests):

```bash
docker compose -f docker-compose.dev.yml exec intentframe-runtime \
  tail -f /home/intentframe/.intentframe/logs/intentframe-core.log
```

Tail all supervised services at once:

```bash
docker compose -f docker-compose.dev.yml exec intentframe-runtime \
  tail -f /home/intentframe/.intentframe/logs/*.log
```

Follow a specific service:

```bash
docker compose -f docker-compose.dev.yml exec intentframe-runtime \
  tail -f /home/intentframe/.intentframe/logs/policy-registry.log
```

Stop the stack when done:

```bash
docker compose -f docker-compose.dev.yml down
```

## Files

| File | Role |
|---|---|
| `Dockerfile.dev` | clone `refactor-substrate` from GitHub, `uv sync` |
| `entrypoint.dev.sh` | vault → seed → fetch+inject → supervisor |
| `seed_vault.py` | store `OPENAI_API_KEY` in Vault as `runtime_env` |
| `inject_and_exec.py` | fetch `runtime_env` from Vault, `exec` the supervisor |
| `docker-compose.dev.yml` | runtime + edge, wired to host Vault |
| `../../demo/config/executor_hashicorp.yaml` | default executor config (dashboard + basic pipeline tests) |
| `../../demo/config/executor_attacks_hashicorp.yaml` | executor config for invoice attack suites |

Both HashiCorp configs are Linux/container-safe: they load the portable POSIX pack
(`intentframe_executor_pack_posix`) plus the neutral console pack
(`intentframe_executor_pack_console`), and enable `simulated_user_io` for
headless user interaction (no stdin, no macOS dialogs). Override with
`EXECUTOR_CONFIG` before `docker compose up` when running attack tests (see §2b).

## Notes

- **Re-seeding each start is intentional.** The secret *value* lives in
  HashiCorp, but the `runtime_env` *metadata* (delivery_mode, env_name) lives in
  the container's local SQLite (`~/.intentframe/data/credentials.db`). `if-data`
  persists it across restarts; a fresh volume is re-seeded automatically. `store`
  is idempotent.
- **Single-writer:** one runtime container = one supervisor = one writer.
  `replicas: 1`; never point a second runtime at the same `if-run` volume.
- **Executor credential backend stays `service`** — the executor talks to the
  vault service over UDS; only the *vault service* talks HashiCorp
  (`IF_VAULT_BACKEND=hashicorp`).
- For a pipeline-only run with no host I/O, set
  `INTENTFRAME_EXECUTOR_MODE=dry_run`.
