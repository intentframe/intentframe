# Kits two-venv harness (local)

Prove the **substrate + `INTENTFRAME_KITS_DIR` wheelhouse** model on your Mac before changing Docker:

| Venv | Role | Contains |
|------|------|----------|
| `.venv-runtime` | Runtime host | `intentframe-supervisor` (no `[native]`), executor, server, policy-registry — **no** kit |
| `.venv` (default `uv sync`) | Test client | Full repo + demo harness (imports kit for policy fixtures only) |

The native kit is built as wheels (kit + workspace deps), copied to `INTENTFRAME_KITS_DIR`, and installed with **`uv pip install` + full dependency resolution** under **runtime constraints** so kits cannot override substrate packages.

The runtime internals stay on their product defaults: supervisor children use
`~/.intentframe/run/*.sock` and talk to each other over UDS. The **edge stays in
the loop only for external clients/tests**, so demo tests use the same HTTP
`INTENTFRAME_*_URL` wiring as Docker/prod (`http://127.0.0.1:8443`).

## Quick start

```bash
cd /path/to/intentframe

# 1) Bare substrate runtime venv + freeze constraints (once, or after substrate changes)
bash scripts/kits-two-venv/setup_runtime_venv.sh

# 2) Client venv for demo tests (once)
uv sync

# 3) Build kit + wheelhouse deps into .intentframe/kits/
bash scripts/kits-two-venv/publish_kit_wheel.sh

# 4) Start runtime (bootstrap kits + supervisor + edge)
export OPENAI_API_KEY=sk-...
bash scripts/kits-two-venv/start_runtime.sh

# 5) Run tests from the client venv over HTTP
bash scripts/kits-two-venv/run_demo_tests.sh demo/tests/test_attacks.py 1 2 3

bash scripts/kits-two-venv/stop_runtime.sh
# or: bash scripts/stop_runtime.sh
```

### Reset / full redo

```bash
# Stop processes and clear harness pid/logs (keeps venvs and wheels)
bash scripts/kits-two-venv/cleanup.sh

# Remove wheelhouse, constraints, and runtime venv (full harness reset)
bash scripts/kits-two-venv/cleanup.sh --full

# Also drop product logs under ~/.intentframe/logs
bash scripts/kits-two-venv/cleanup.sh --full --logs

# or: bash scripts/cleanup_runtime.sh --full
```

After `--full`, rerun the Quick start from step 1 (`setup_runtime_venv.sh` through `start_runtime.sh`).

## Kit install policy (constraints + uv)

After `setup_runtime_venv.sh`, the harness writes:

```text
.intentframe/runtime-constraints.txt   # name==version pins of the bare runtime (see Script internals)
```

`bootstrap_kits.sh` installs **only the primary kit wheel** (default: `intentframe_native_kit-*.whl`) with:

```bash
uv pip install \
  --constraints .intentframe/runtime-constraints.txt \
  --find-links .intentframe/kits \
  --strict \
  .intentframe/kits/intentframe_native_kit-*.whl
```

| Behavior | Meaning |
|----------|---------|
| **Full deps** | Kit `Requires-Dist` (e.g. `command-shield`, `boto3`, …) are resolved and installed |
| **Constraints** | Cannot upgrade/downgrade packages already pinned in the runtime freeze (`pydantic`, `intentframe-server`, …) |
| **`--find-links`** | Workspace-only deps ship as extra wheels in `INTENTFRAME_KITS_DIR` (not on PyPI) |
| **`--strict`** | Fails if the environment has missing or inconsistent dependencies after install |

### When failures show up

| Stage | What fails | Example |
|-------|------------|---------|
| **`uv pip install` (bootstrap)** | Declared dependency conflict or missing wheel | Kit requires `pydantic>=3` but runtime pins `pydantic==2.x` |
| **`uv pip freeze --strict` (bootstrap)** | Broken env after install | Missing transitive dep |
| **Supervisor / service logs** | Import or config at process start | Kit forgot to declare a dependency in `pyproject.toml` |
| **Demo tests** | Runtime behavior | Policy/executor mismatch, not packaging |

Preview a kit install without mutating the venv:

```bash
KITS_INSTALL_DRY_RUN=1 source scripts/kits-two-venv/bootstrap_kits.sh
```

### Third-party kits

1. Build your kit wheel (and any private dependency wheels) into `INTENTFRAME_KITS_DIR`.
2. Point install at your wheel:

   ```bash
   export KIT_WHEELS="/path/to/acme_intentframe_kit-1.0.0-py3-none-any.whl"
   source scripts/kits-two-venv/bootstrap_kits.sh
   ```

3. Re-run `setup_runtime_venv.sh` if you change the substrate so constraints stay current.

4. To refresh kit code after rebuilding the wheel:

   ```bash
   export KIT_REINSTALL_PACKAGES="acme-intentframe-kit"
   ```

Arbitrary **new** libraries in the kit are fine. Overriding **runtime-owned** versions is not — resolution fails at install time.

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `INTENTFRAME_KITS_DIR` | `.intentframe/kits` | Wheelhouse (`--find-links`) + primary kit wheel |
| `RUNTIME_CONSTRAINTS` | `.intentframe/runtime-constraints.txt` | Frozen substrate; kit install must respect this |
| `RUNTIME_VENV` | `.venv-runtime` | Substrate-only Python environment |
| `CLIENT_VENV` | `.venv` | Demo test runner environment |
| `KIT_WHEELS` | (auto: `intentframe_native_kit-*.whl`) | Primary kit wheel(s) to install |
| `KIT_REINSTALL_PACKAGES` | (unset) | Optional `uv --reinstall-package` names when refreshing a kit |
| `KITS_INSTALL_DRY_RUN` | `0` | Set to `1` to resolve without installing |
| `EXECUTOR_CONFIG` | `demo/config/executor_hashicorp.yaml` | Operator-owned executor profile |
| `INTENTFRAME_EDGE_PORT` | `8443` | Edge HTTP port for external test `*_URL` env vars |

After bootstrap, profiles come from the **installed kit wheel**:

- `INTENTFRAME_CORE_CONFIG` → `…/intentframe_native_kit/core.yaml`
- `INTENTFRAME_SUPERVISOR_CONFIG` → `…/supervisor_profile.yaml`
- `INTENTFRAME_EDGE_CONFIG` → `…/edge_profile.yaml`

## Scripts (quick reference)

| Script | Action |
|--------|--------|
| `setup_runtime_venv.sh` | Substrate venv + `runtime-constraints.txt` |
| `publish_kit_wheel.sh` | Build kit + wheelhouse dep wheels → `INTENTFRAME_KITS_DIR` |
| `bootstrap_kits.sh` | Constrained `uv pip install` + export profile env (**source**, do not execute) |
| `start_runtime.sh` | bootstrap + supervisor + edge (background) |
| `start_runtime_attacks.sh` | Same as `start_runtime.sh` with attack executor profile |
| `stop_runtime.sh` | Stop edge and supervisor |
| `cleanup.sh` | Stop + remove harness artifacts (`--artifacts`, `--full`, `--logs`) |
| `status_runtime.sh` | UDS + edge health |
| `run_demo_tests.sh` | Client venv tests via edge HTTP |

Wrappers at repo root: `scripts/stop_runtime.sh`, `scripts/cleanup_runtime.sh` (exec the scripts above).

Step-by-step behavior: [Script internals](#script-internals) below.

## Architecture

```text
  .venv (client)                    .venv-runtime (host)
  uv sync full repo                 setup_runtime_venv: substrate only
        |                                    |
        |  INTENTFRAME_*_URL ──HTTP──►  edge (:8443, repo PYTHONPATH)
        |                                    │ UDS proxy
        |                                    ▼
        |                             ~/.intentframe/run/*.sock
        |                             supervisor → policy / executor / core / (kit) resource-registry
        |
  run_demo_tests.sh ─────────────────►  same path as Docker/prod tests
```

| Path | Written by | Purpose |
|------|------------|---------|
| `.venv-runtime/` | `setup_runtime_venv.sh` | Substrate Python env |
| `.intentframe/runtime-constraints.txt` | `setup_runtime_venv.sh` | `name==version` freeze for kit `--constraints` |
| `.intentframe/kits-build/` | `publish_kit_wheel.sh` | Staging for `uv build` output |
| `.intentframe/kits/` | `publish_kit_wheel.sh` | Wheelhouse (`--find-links`) |
| `.intentframe/kits-two-venv/` | `start_runtime.sh` | Harness pid files + `supervisor.log` / `edge.log` |
| `~/.intentframe/run/` | supervisor (product default) | UDS sockets + `supervisor.pid` |
| `~/.intentframe/logs/` | runtime services | Service logs (not removed unless `cleanup.sh --logs`) |

**Edge note:** `intentframe_edge` and `intentframe_proxy` are not installed wheels yet. `start_runtime.sh` runs them from the repo via `PYTHONPATH=${REPO_ROOT}`. Only FastAPI, uvicorn, httpx, and related libs are in the runtime venv and listed in `runtime-constraints.txt`.

## Script internals

### `common.sh` (library — source only, do not execute)

Sets paths and helpers used by every script.

| Symbol | Role |
|--------|------|
| `REPO_ROOT`, `RUNTIME_VENV`, `CLIENT_VENV`, `INTENTFRAME_KITS_DIR` | Overridable via env |
| `RUNTIME_CONSTRAINTS` | Constraint file path for kit install |
| `RUN_DIR` | Fixed `~/.intentframe/run` (product UDS layout; harness does not override) |
| `PID_DIR`, `SUPERVISOR_PID_FILE`, `EDGE_PID_FILE` | Harness process tracking under `.intentframe/kits-two-venv/` |
| `_kits_require_*` | Fail fast if repo, venv, or constraints are missing |
| `_kits_freeze_runtime_constraints` | Writes constraints via `importlib.metadata` (not raw `uv pip freeze`, which can emit invalid `-e file://` lines) |
| `_kits_primary_wheels` | Resolves `KIT_WHEELS` or `intentframe_native_kit-*.whl` in the wheelhouse |
| `_kits_kit_parent` | Installed kit package directory (profile YAML paths after bootstrap) |

### `setup_runtime_venv.sh`

1. Create `.venv-runtime` (Python 3.14) if missing.
2. `uv pip install packages/intentframe-supervisor` — pulls `intentframe-runtime` → policy-registry, executor, server (+ transitive SDKs). No `[native]` extra, no kit.
3. Install edge **third-party** deps only (FastAPI, uvicorn, httpx, pydantic, PyYAML); not `intentframe_edge` as a wheel.
4. Uninstall any leftover `intentframe-native-kit` / `command-shield` so the freeze describes substrate only.
5. Write `runtime-constraints.txt`, run `uv pip freeze --strict`, verify substrate imports; warn if the kit is already importable.

Re-run after substrate package changes or before a clean kit reinstall.

### `publish_kit_wheel.sh`

1. `uv build --package` for each entry in `WHEELHOUSE_PACKAGES` (default: `intentframe-native-kit`, `command-shield`) into `.intentframe/kits-build/`.
2. Copy all `*.whl` into `INTENTFRAME_KITS_DIR`.
3. Exit with error if no `intentframe_native_kit-*.whl` (primary kit).

Other wheels in the directory are not installed directly; `bootstrap_kits.sh` uses them as `--find-links` for kit `Requires-Dist`. Extend `WHEELHOUSE_PACKAGES` in the script for additional workspace-only deps.

### `bootstrap_kits.sh` (must be **sourced**)

Use `source bootstrap_kits.sh` so exported `INTENTFRAME_*_CONFIG` persist in your shell. `start_runtime.sh` sources it in-process.

1. Require runtime venv and constraints file.
2. Resolve primary wheel(s) via `_kits_primary_wheels`.
3. `uv pip install` with `--constraints`, `--find-links`, `--strict` (optional `--reinstall-package` from `KIT_REINSTALL_PACKAGES`).
4. `uv pip freeze --strict` post-check.
5. Export profile paths from the **installed** kit: `core.yaml`, `supervisor_profile.yaml`, `edge_profile.yaml`; keep `EXECUTOR_CONFIG` from caller / `common.sh`.
6. Print entry points `intentframe.bundles` and `intentframe.executor_packs`.

`KITS_INSTALL_DRY_RUN=1` runs resolve-only `--dry-run`.

### `start_runtime.sh`

1. Default `KIT_REINSTALL_PACKAGES=intentframe-native-kit` (refresh kit after wheel rebuild).
2. Source `bootstrap_kits.sh`.
3. Start `python -m supervisor.main start` in the background with only: `OPENAI_API_KEY`, core/supervisor configs, `EXECUTOR_CONFIG`, `INTENTFRAME_EXECUTOR_MODE`. No `INTENTFRAME_*_URL` — children use default UDS under `RUN_DIR`.
4. Wait up to 90s for core health via `curl --unix-socket …/intentframe.sock`.
5. Start edge with `PYTHONPATH=${REPO_ROOT}`, `python -m intentframe_edge`, kit `INTENTFRAME_EDGE_CONFIG`; log to `edge.log`.
6. Wait up to 60s for `http://127.0.0.1:8443/health`.

Exits early if the harness supervisor pid file already refers to a live process.

### `start_runtime_attacks.sh`

Sets `EXECUTOR_CONFIG` to `demo/config/executor_attacks_hashicorp.yaml`, then `exec start_runtime.sh`. Required for attack / redteam demo paths (VFS mount layout).

### `stop_runtime.sh`

Shutdown order (best-effort):

1. Harness edge pid (`.intentframe/kits-two-venv/edge.pid`) — TERM, then KILL.
2. Product supervisor pid (`~/.intentframe/run/supervisor.pid`) — TERM the process **group**.
3. Harness supervisor pid file.
4. `lsof` holders of UDS sockets in `RUN_DIR`, then listeners on `EDGE_PORT`.
5. Remove stale socket files; verify edge HTTP is down.

### `status_runtime.sh`

Read-only checks: four UDS sockets, core UDS health, edge HTTP health JSON, harness and run_dir supervisor pids. Always exits 0 (informational, even when services are down).

### `run_demo_tests.sh`

1. Require client `.venv`.
2. Set `INTENTFRAME_CORE_URL`, `INTENTFRAME_POLICY_URL`, `INTENTFRAME_RESOURCE_URL` to `EDGE_BASE_URL` (external client path, same as Docker).
3. Fail fast if edge health check fails.
4. Warn if attack test paths are selected but runtime was not started with `executor_attacks` config.
5. `exec` client Python with arguments (default: `demo/tests/test_attacks.py 1 2 3` — pytest node ids, not shell flags).

`OPENAI_API_KEY` is required on the **runtime** process for Guardian; the test shell does not need it for HTTP-only demo tests.

### `cleanup.sh`

1. Invoke `stop_runtime.sh` first (unless `--dry-run`).
2. Default: remove `.intentframe/kits-two-venv/` (harness logs and pids).
3. `--artifacts`: wheelhouse, `kits-build`, constraints file.
4. `--runtime-venv`: `.venv-runtime`.
5. `--full`: artifacts + runtime venv.
6. `--logs` / `--client`: optional product logs or client venv.

## Common issues

- **No wheels in KITS_DIR** — run `publish_kit_wheel.sh`.
- **Constraint conflict on install** — kit wants a different version of a substrate package; fix kit deps or bump substrate + re-freeze constraints.
- **`command-shield` not found** — add its wheel to the wheelhouse (`publish_kit_wheel.sh` builds it) or publish all private deps into `INTENTFRAME_KITS_DIR`.
- **Attack suite mismatch** — use `bash scripts/kits-two-venv/start_runtime_attacks.sh` or set `EXECUTOR_CONFIG=demo/config/executor_attacks_hashicorp.yaml` before `start_runtime.sh`.
- **Handshake 500 over edge** — check `~/.intentframe/logs/intentframe-server.log`; runtime-internal registry/executor calls should be UDS under `~/.intentframe/run`, not HTTP through the edge.
