# GitHub release runtime (local smoke test)

Boot the full IntentFrame runtime from **published GitHub release wheels** (not the workspace or kit wheelhouse). Uses `.venv-release` and the same env defaults as the kits-two-venv harness (`~/.intentframe/run`, `~/.intentframe/logs` — no `INTENTFRAME_RUN_DIR` override).

Part of the release verification stack documented in [`../../github-release/README.md`](../../github-release/README.md).

## When to use

| Goal | Use |
|------|-----|
| Wheels install + imports only | [`../../github-install/verify_release_install.sh`](../../github-install/verify_release_install.sh) |
| Wheels boot supervisor + edge | This script |
| Demo behavior over HTTP | [`../run_demo_tests.sh`](../run_demo_tests.sh) after start |

## Start

```bash
export OPENAI_API_KEY=sk-...
bash scripts/kits-two-venv/gh-release-venv/start_runtime_from_release.sh --tag v0.1.1
```

Options: `--tag`, `--repo` (default `intentframe/intentframe`). Override `RELEASE_VENV`, `EXECUTOR_CONFIG`, `INTENTFRAME_EDGE_PORT` via env (see [`../common.sh`](../common.sh)).

Refuses to start if edge or core UDS is already healthy — run stop first.

## Stop / test (shared harness)

```bash
bash scripts/kits-two-venv/stop_runtime.sh
bash scripts/kits-two-venv/run_demo_tests.sh demo/tests/test_attacks.py 1 2 3
```

`stop_runtime.sh` clears harness pids under `.intentframe/kits-two-venv/`, `.intentframe/gh-release-venv/`, and legacy `.intentframe/github-release/`, plus the product supervisor in `~/.intentframe/run`.

## Paths

| Path | Purpose |
|------|---------|
| `.venv-release/` | Python env with all 18 release wheels |
| `.intentframe/gh-release-venv/` | Harness `supervisor.log`, `edge.log`, pid files |
| `~/.intentframe/run/` | Product UDS sockets (shared with workspace harness) |
| `~/.intentframe/logs/` | Service logs from spawned processes |

## Consumer install (separate repo)

**PyPI (recommended):** [`../../github-install/example-pyproject-pypi.toml`](../../github-install/example-pyproject-pypi.toml) — see [`../../docs/package-consumers.md`](../../docs/package-consumers.md).

**GitHub URL fallback:** [`../../github-install/example-pyproject.toml`](../../github-install/example-pyproject.toml) — all 18 `[tool.uv.sources]` entries.
