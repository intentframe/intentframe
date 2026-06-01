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
│        policy-registry / executor / intentframe-core (UDS) │
│        (+ resource-registry with the kit profile)         │
└───────────────┬─────────────────────────────────────────────┘
                │ if-run volume (sockets)
┌───────────────▼─ intentframe-edge container ──────────────┐
│ HTTP :8443  →  policy / core sockets                      │
│               (+ /workspaces → resource with kit profile) │
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
# minimal default → {"status":"ok","backends":{"policy-registry":true,"intentframe-core":true}}
# with kit profiles → also includes "resource-registry":true
```

> **Most test suites need workspaces.** The supervisor/edge default is the
> minimal substrate (no `resource-registry`, no `/workspaces`). Any suite that
> uses `ResourceRegistryClient()` / `INTENTFRAME_RESOURCE_URL` (dashboard,
> invoice attack suites, root-demo workspace seeding) must run with the
> first-party kit profiles enabled — export **both** before `up`:
>
> ```bash
> export INTENTFRAME_SUPERVISOR_CONFIG=/app/intentframe_native_kit/supervisor_profile.yaml
> export INTENTFRAME_EDGE_CONFIG=/app/intentframe_native_kit/edge_profile.yaml
> ```
>
> These live in the container image at `/app/...`. Changing them requires an
> `up` recreate (container env is fixed at `up` time — see [§2d](#2d-when-to-restart-the-container)).

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
# workspaces are needed by the dashboard — enable the kit profiles:
export INTENTFRAME_SUPERVISOR_CONFIG=/app/intentframe_native_kit/supervisor_profile.yaml
export INTENTFRAME_EDGE_CONFIG=/app/intentframe_native_kit/edge_profile.yaml
docker compose -f docker-compose.dev.yml up --build

# Mac:
export INTENTFRAME_CORE_URL=http://localhost:8443
export INTENTFRAME_POLICY_URL=http://localhost:8443
export INTENTFRAME_RESOURCE_URL=http://localhost:8443
python demo/demo_dashboard.py
```

### 2b. Invoice attack suites (`test_attacks`, `test_advanced_attacks`, `test_redteam_attacks`)

Three separate runners share `demo/config/test_policy.yaml` but differ in setup:

| Runner | Attacks | Calls `populate_attack_sandbox()`? | Typical over HTTP |
|---|---|---|---|
| `test_attacks.py` | 1–6 | Yes (legacy; only attack **4** prelude reads care) | Defense ✅ |
| `test_advanced_attacks.py` | 7–14 | Yes (legacy; all `APPEND_ROW`, block before executor) | Defense ✅ |
| `test_redteam_attacks.py` | 15–24 | **No** — raw JSON only | Defense ✅; attack **16** ALLOWs by design |

For container runs, set `EXECUTOR_CONFIG=demo/config/executor_attacks_hashicorp.yaml` before
`up` (see [§2d](#2d-when-to-restart-the-container)). Defense validation (`blocked_count`
in audit) works over HTTP without shared `demo/` mounts — see [§2c](#2c-limitations-when-running-tests-over-http).

```bash
# override EXECUTOR_CONFIG before up + enable workspace kit profiles:
export EXECUTOR_CONFIG=demo/config/executor_attacks_hashicorp.yaml
export INTENTFRAME_SUPERVISOR_CONFIG=/app/intentframe_native_kit/supervisor_profile.yaml
export INTENTFRAME_EDGE_CONFIG=/app/intentframe_native_kit/edge_profile.yaml
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
>
> **Executor side effects over HTTP are partial** — most attacks block before the
> executor runs, so defense validation (`blocked_count` in audit) works fine.
> See [§2c](#2c-limitations-when-running-tests-over-http) for when filesystem
> sync matters (ALLOW paths only).

### 2c. Limitations when running tests over HTTP

When tests run on your Mac (or CI) and the runtime lives in a container reached
via `INTENTFRAME_*_URL=http://localhost:8443`, **HTTP carries intents, policy,
and audit — not filesystem mutations**.

The pipeline only calls the executor on **ALLOW**:

```
DeterministicGuardian → (BLOCK → return, no executor)
                      → Analysis Engine → Guardian → (BLOCK → return)
                                                    → (ALLOW → executor.execute)
```

So for invoice attack suites, **defense validation over HTTP is usually fine**.
The harness checks `blocked_count` / `decision == "BLOCK"` in the audit log —
that all happens in the container before any executor I/O. Most attacks submit
high-amount `APPEND_ROW` intents or path violations and are blocked by
deterministic gates or AI Guardian without ever reaching the executor.

#### What works over HTTP

| Suite | Over HTTP | Notes |
|---|---|---|
| `demo/demo_dashboard.py` | ✅ | Static `demo_data/` baked into the image |
| Invoice attack **defense** checks (`test_attacks*`, advanced, redteam) | ✅ | Audit `BLOCK` / `blocked_count` — no executor needed for most attacks |
| Root demo **dry-run** sweeps (`demo/tests/root_demo/*`) | ✅ | No executor service; synthetic `RUN_COMMAND` |
| Policy / resource seeding from test harness | ✅ | Registry clients talk to the edge |
| Actor → core pipeline (handshake, submit, audit) | ✅ | One `asyncio.run()` session per run |

#### What is partial or local-only

| Suite | Over HTTP | Why |
|---|---|---|
| Invoice attack **executor side effects** (writes to `/expense_tracker.md`, allowed `APPEND_ROW`s) | ⚠️ Partial | Only matters when Guardian **ALLOW**s — see below |
| Attacks with allowed **prelude reads** on `/invoices/` (e.g. attack 4) | ⚠️ Partial | Early `READ_FILE` / `LIST_DIRECTORY` may reach executor before later intents block |
| Root demo **real** mode (`sudo -n sandbox-exec`) | ❌ | macOS-only |
| `demo/tests/test_adapters.py` | ❌ | macOS adapter imports / PyObjC |

#### When the filesystem split actually matters

Most attack JSON fixtures submit intents **directly** through the stub agent —
they do not depend on reading poisoned invoice markdown. `test_redteam_attacks.py`
does not call `populate_attack_sandbox()` at all.

`test_attacks.py` and `test_advanced_attacks.py` still call
`populate_attack_sandbox()` before each attack, but for most scenarios that call
is **legacy setup** — the submitted intents carry their own `data`/`reason` and
block on policy or AI before executor I/O.

The sandbox split only bites when an intent is **ALLOW**ed and the executor must
touch files:

- **Known gap / allowed path** — redteam attack 16 (salami slicing): five
  `$4,000` `APPEND_ROW`s each under the per-intent limit; today they may ALLOW
  and reach the executor (writes to `/expense_tracker.md` in the **container**,
  not on your Mac).
- **Prelude reads** — attack 4 (path traversal): starts with allowed
  `LIST_DIRECTORY` / `READ_FILE` on `/invoices/` before later reads block; empty
  container sandbox can make those executor reads fail even though later path
  blocks still defend correctly.

For everything else (attacks 1–3, 5–14, most redteam), you are validating
**whether IntentFrame blocked the attack** — that works over HTTP without shared
`demo/` mounts. Verified example: `test_advanced_attacks.py` attacks 7–14 all
block at Guardian with no executor I/O over HTTP.

#### What `populate_attack_sandbox()` does (and when you can ignore it)

**Only** `test_attacks.py` and `test_advanced_attacks.py` call this helper (from
`demo/tests/invoice_attack_pipeline.py`). `test_redteam_attacks.py` does not.

Attack invoice **sources** are in git under `demo/demo_data/attacks/<scenario>/`.
The harness copies them into `demo/demo_data/attack_invoices_sandbox/` (gitignored
scratch dir) before each attack — see `invoice_attack_pipeline.py`. The executor
config mounts that sandbox as `/invoices/`.

Locally, test harness and executor share one filesystem. Over HTTP, Mac-side
`populate_attack_sandbox()` and `reset_expense_tracker()` do **not** update the
container's `/app/demo/demo_data/…` unless you bind-mount or populate inside the
container.

```
Mac (test harness)                         Container (executor)
─────────────────                          ──────────────────────
populate_attack_sandbox()                  only consulted on ALLOW
  writes demo/demo_data/                     or allowed prelude reads
  attack_invoices_sandbox/        ≠          on /invoices/ or /expense_tracker.md
```

#### Workarounds (only if you need executor side-effect fidelity)

Pick one when you care about **what the executor actually wrote**, not just
whether the attack was blocked:

1. **Run attack tests locally** — supervisor on the Mac with
   `EXECUTOR_CONFIG=demo/config/executor_attacks.yaml`.
2. **Bind-mount `demo/`** into `intentframe-runtime` so Mac-side staging is visible
   to the container executor (not in the default compose file today).
3. **Populate inside the container** before attacks that need `/invoices/` reads.

#### Other HTTP caveats

- **`EXECUTOR_CONFIG` must match the suite** — dashboard vs attack configs mount
  different VFS paths (§2b footgun).
- **Rebuild after code changes** — stale Docker cache can serve an old `git clone`
  layer; see [Clean slate](#clean-slate-remove-everything).
- **AI invoice agent / some live agent tests** — agents that call `asyncio.run()`
  separately for handshake and run on the same `Actor` can hit HTTP keep-alive /
  event-loop lifecycle issues; stub-pipeline attack tests avoid this by design.

### 2d. When to restart the container

Mac-side `INTENTFRAME_*_URL` exports do **not** require a restart. Container env
is fixed at **`docker compose up`** time — change it, then recreate the stack.

| Change | Restart? | How |
|---|---|---|
| Run a different test against same stack (same `EXECUTOR_CONFIG`, `real` mode) | No | Export `INTENTFRAME_*_URL` on Mac only |
| Dashboard ↔ invoice attacks (`EXECUTOR_CONFIG`) | **Yes** | `down`, set `EXECUTOR_CONFIG`, `up --build` |
| Enable/disable workspaces (`INTENTFRAME_SUPERVISOR_CONFIG` + `INTENTFRAME_EDGE_CONFIG`) | **Yes** | `down`, export/unset both kit profiles, `up` |
| Real executor ↔ root dry-run (`INTENTFRAME_EXECUTOR_MODE`) | **Yes** | `down`, set `dry_run` + `INTENTFRAME_DRY_RUN_CONTEXT=root`, `up` |
| Code changes after git push (stale cached `git clone` layer) | **Yes** | See [Clean slate](#clean-slate-remove-everything) |

```bash
cd deploy/dev
docker compose -f docker-compose.dev.yml down

# example: switch to attack executor profile
export EXECUTOR_CONFIG=demo/config/executor_attacks_hashicorp.yaml
export OPENAI_API_KEY=sk-...
docker compose -f docker-compose.dev.yml up --build
```

`down` without `-v` keeps registry/audit volumes; add `-v` only when you want a
fully clean state.

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
# root-demo suites seed workspaces — enable the kit profiles:
export INTENTFRAME_SUPERVISOR_CONFIG=/app/intentframe_native_kit/supervisor_profile.yaml
export INTENTFRAME_EDGE_CONFIG=/app/intentframe_native_kit/edge_profile.yaml
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

### Stay attached to a live tail (recommended)

Start the stack in the **background**, then attach your terminal to a log stream.
**Ctrl+C only disconnects the tail** — the containers keep running.

**Terminal 1 — start stack:**

```bash
cd deploy/dev
export OPENAI_API_KEY=sk-...
docker compose -f docker-compose.dev.yml up -d --build
```

**Terminal 2 — attach to the log you care about** (pick one):

```bash
cd deploy/dev

# Dashboard / pipeline / Guardian (most useful while running demo_dashboard.py)
docker compose -f docker-compose.dev.yml exec intentframe-runtime \
  tail -f /home/intentframe/.intentframe/logs/intentframe-core.log

# Executor startup / pack loading / health-check failures
docker compose -f docker-compose.dev.yml exec intentframe-runtime \
  tail -f /home/intentframe/.intentframe/logs/executor.log

# All supervised services interleaved (core + registries + executor)
docker compose -f docker-compose.dev.yml exec intentframe-runtime \
  tail -f /home/intentframe/.intentframe/logs/*.log

# Bootstrap only (entrypoint, credential-vault, seed, supervisor — not file logs)
docker compose -f docker-compose.dev.yml logs -f intentframe-runtime
```

> **Note:** `docker compose up` (without `-d`) also streams logs, but mixing
> bootstrap + all services in one scrollback is noisy, and it does **not**
> show the per-service files under `~/.intentframe/logs/`. Prefer `up -d` +
> `exec tail -f` above.

Foreground `up` without `-d` attaches stdout for every service; **Ctrl+C stops
the whole stack**:

```bash
docker compose -f docker-compose.dev.yml up --build
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
`/home/intentframe/.intentframe/logs/` (on the `if-data` volume). Run these
from `deploy/dev` while the stack is up (`up -d`).

| Log file | Service | What you'll see |
|---|---|---|
| `intentframe-core.log` | intentframe-core | Pipeline, Guardian, Actor, dry-run or executor bridge |
| `policy-registry.log` | policy-registry | Policy registry HTTP/UDS server |
| `resource-registry.log` | resource-registry | Resource registry HTTP/UDS server *(only when the kit `INTENTFRAME_SUPERVISOR_CONFIG` profile is enabled)* |
| `executor.log` | executor | Executor gateway startup, pack loading, adapter wiring *(only when `INTENTFRAME_EXECUTOR_MODE=real`)* |

**Follow (live tail) — one file each:**

```bash
# Pipeline / Guardian / tests hitting core (most useful during dashboard runs)
docker compose -f docker-compose.dev.yml exec intentframe-runtime \
  tail -f /home/intentframe/.intentframe/logs/intentframe-core.log

# Policy registry
docker compose -f docker-compose.dev.yml exec intentframe-runtime \
  tail -f /home/intentframe/.intentframe/logs/policy-registry.log

# Resource registry (workspace mounts registered by dashboard/tests)
docker compose -f docker-compose.dev.yml exec intentframe-runtime \
  tail -f /home/intentframe/.intentframe/logs/resource-registry.log

# Executor — start here when executor health check fails or pack errors
docker compose -f docker-compose.dev.yml exec intentframe-runtime \
  tail -f /home/intentframe/.intentframe/logs/executor.log
```

**Snapshot (last 100 lines, no follow):**

```bash
docker compose -f docker-compose.dev.yml exec intentframe-runtime \
  tail -n 100 /home/intentframe/.intentframe/logs/intentframe-core.log

docker compose -f docker-compose.dev.yml exec intentframe-runtime \
  tail -n 100 /home/intentframe/.intentframe/logs/policy-registry.log

docker compose -f docker-compose.dev.yml exec intentframe-runtime \
  tail -n 100 /home/intentframe/.intentframe/logs/resource-registry.log

docker compose -f docker-compose.dev.yml exec intentframe-runtime \
  tail -n 100 /home/intentframe/.intentframe/logs/executor.log
```

**Search for errors in executor log** (common after stale Docker cache or pack misconfig):

```bash
docker compose -f docker-compose.dev.yml exec intentframe-runtime \
  grep -iE 'error|exception|configuration|failed|traceback' \
  /home/intentframe/.intentframe/logs/executor.log
```

**Follow all supervised services at once:**

```bash
docker compose -f docker-compose.dev.yml exec intentframe-runtime \
  tail -f /home/intentframe/.intentframe/logs/*.log
```

**List log files and sizes** (confirm `executor.log` exists — it is absent in `dry_run` mode):

```bash
docker compose -f docker-compose.dev.yml exec intentframe-runtime \
  ls -la /home/intentframe/.intentframe/logs/
```

### Bootstrap logs (not in `~/.intentframe/logs/`)

These run **before** the supervisor and only appear in the compose log stream for
`intentframe-runtime` (stdout/stderr), not as separate files:

| Source | What you'll see |
|---|---|
| `entrypoint.dev.sh` | `[entrypoint]` vault wait, seed, supervisor launch |
| `credential-vault` | Uvicorn for `intentframe_credentials.server` (HashiCorp backend) |
| `seed_vault.py` | `[seed] stored openai/api_key ...` |
| `inject_and_exec.py` | `[bootstrap] injected N runtime_env var(s) from vault` |

```bash
# Full runtime bootstrap + supervisor (includes credential-vault + entrypoint)
docker compose -f docker-compose.dev.yml logs -f intentframe-runtime

# Last 200 lines only (after a failed start)
docker compose -f docker-compose.dev.yml logs --tail=200 intentframe-runtime

# HashiCorp Vault container (dev mode, KV v2)
docker compose -f docker-compose.dev.yml logs -f vault

# HTTP edge proxy (:8443 → UDS backends)
docker compose -f docker-compose.dev.yml logs -f intentframe-edge
```

Stop the stack when done:

```bash
docker compose -f docker-compose.dev.yml down
```

## Clean slate (remove everything)

Use this when you hit **stale Docker layers** (build log shows `CACHED` on the
`git clone` step after you pushed new commits), executor health-check failures,
or you want a completely fresh stack with no leftover volumes or images.

All commands assume you are in `deploy/dev`. Compose project name is `dev`
(volumes appear as `dev-if-run`, `dev-if-data`; network as `dev_default`).

### Stop only (keep volumes)

Preserves `if-run` / `if-data` (UDS sockets, registry state, credential metadata):

```bash
docker compose -f docker-compose.dev.yml down
```

### Remove compose stack (containers, network, named volumes)

Deletes everything this compose file created, including persistent state:

```bash
docker compose -f docker-compose.dev.yml down -v --remove-orphans
```

### Remove dev images

```bash
docker rmi intentframe-dev:refactor-substrate 2>/dev/null || true
```

The bundled Vault image is shared with other projects — remove only if you want
to force a re-pull:

```bash
# optional
docker rmi hashicorp/vault:latest 2>/dev/null || true
```

### Clear Docker build cache

**Required** when `up --build` reuses a cached `git clone` with old code. Docker
will not re-clone GitHub until this layer is busted:

```bash
docker builder prune -f
```

Aggressive — clears **all** unused build cache on this machine:

```bash
docker builder prune -af
```

### Full reset + rebuild (recommended after executor/pack changes)

One-shot: tear down, remove images, clear build cache, rebuild without cache,
start fresh:

```bash
cd deploy/dev

docker compose -f docker-compose.dev.yml down -v --remove-orphans
docker rmi intentframe-dev:refactor-substrate 2>/dev/null || true
docker builder prune -f

export OPENAI_API_KEY=sk-...
docker compose -f docker-compose.dev.yml build --no-cache
docker compose -f docker-compose.dev.yml up
```

Confirm the build log shows a **fresh** `git clone` (not `CACHED`), then:

```bash
curl -fsS http://localhost:8443/health
```

### Verify nothing dev-related remains (optional)

```bash
docker compose -f docker-compose.dev.yml ps -a
docker volume ls | grep -E '^local +dev-'
docker network ls | grep dev
docker images | grep intentframe-dev
```

If orphaned `dev-*` resources linger after `down -v`:

```bash
docker volume rm dev-if-run dev-if-data 2>/dev/null || true
docker network rm dev_default 2>/dev/null || true
```

### Nuclear option (whole-machine Docker cleanup)

**Destructive** — removes all stopped containers, unused networks, dangling
images, and unused volumes **across every project**, not just this stack:

```bash
docker system prune -af --volumes
```

Only use when you intentionally want to wipe Docker state machine-wide.

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
| `../../intentframe_native_kit/supervisor_profile.yaml` | kit supervisor profile (adds `resource-registry`) — export as `INTENTFRAME_SUPERVISOR_CONFIG` |
| `../../intentframe_native_kit/edge_profile.yaml` | kit edge profile (adds `/workspaces` route) — export as `INTENTFRAME_EDGE_CONFIG` |

Both HashiCorp configs are Linux/container-safe: they load the portable POSIX pack
(`intentframe_native_kit.intentframe_executor_pack_posix`) plus the neutral console pack
(`intentframe_native_kit.intentframe_executor_pack_console`), and enable `simulated_user_io` for
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
