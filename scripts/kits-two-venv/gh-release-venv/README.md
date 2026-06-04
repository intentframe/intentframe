# GitHub release runtime (local smoke test)

Boot the full IntentFrame runtime from **published GitHub release wheels** (not the workspace or kit wheelhouse). Uses `.venv-release` and the same env defaults as the kits-two-venv harness.

## Start

```bash
export OPENAI_API_KEY=sk-...
bash scripts/kits-two-venv/gh-release-venv/start_runtime_from_release.sh --tag v0.1.0
```

## Stop / test (shared harness)

```bash
bash scripts/kits-two-venv/stop_runtime.sh
bash scripts/kits-two-venv/run_demo_tests.sh demo/tests/test_attacks.py 1 2 3
```

`stop_runtime.sh` stops edge/supervisor whether you started via `start_runtime.sh` or this script (all harness pid dirs + product `~/.intentframe/run`).

Publishing and consumer `pyproject.toml`: [`../../github-release/README.md`](../../github-release/README.md), [`../../github-install/example-pyproject.toml`](../../github-install/example-pyproject.toml).
