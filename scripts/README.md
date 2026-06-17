# scripts/

Utility scripts for local development setup.

## PyPI release (`packages/` only)

See [`release/README.md`](release/README.md) — lockstep versioning (`set_version.py`), validation (`validate_publish.sh`), grouped GitHub workflow ([`release.yml`](../.github/workflows/release.yml)), terminal uploads (`publish.py`), CI staging (`dist/publish` → `dist/upload`), and PyPI **new-project** rate limits (`429`). All **18** packages for **`0.1.0`** are on [PyPI](https://pypi.org/); consumers: [`../docs/package-consumers.md`](../docs/package-consumers.md).

## GitHub release wheels (optional mirror)

| Directory | Role |
|-----------|------|
| [`github-release/`](github-release/README.md) | Publish runbook: version pins, build, upload wheels to a GitHub release |
| [`github-install/`](github-install/README.md) | Install verify (`verify_release_install.sh`); [`example-pyproject-pypi.toml`](github-install/example-pyproject-pypi.toml) (PyPI) and [`example-pyproject.toml`](github-install/example-pyproject.toml) (URL fallback) |
| [`kits-two-venv/gh-release-venv/`](kits-two-venv/gh-release-venv/README.md) | Boot supervisor + edge from release wheels (`.venv-release`) |

Suggested verification after uploading wheels to a release:

```bash
./scripts/github-install/verify_release_install.sh --tag v0.1.0
export OPENAI_API_KEY=sk-...
bash scripts/kits-two-venv/gh-release-venv/start_runtime_from_release.sh --tag v0.1.0
bash scripts/kits-two-venv/run_demo_tests.sh demo/tests/test_attacks.py 1 2 3
bash scripts/kits-two-venv/stop_runtime.sh
```

## Kits two-venv harness (substrate + wheel, edge for tests)

See [`kits-two-venv/README.md`](kits-two-venv/README.md) — bare `.venv-runtime`, constrained `uv pip install` of kit wheels from `.intentframe/kits/`, start supervisor + edge, run demo tests from `.venv` over HTTP. Per-script behavior: [Script internals](kits-two-venv/README.md#script-internals).

```bash
bash scripts/kits-two-venv/start_runtime.sh              # workspace runtime + kit wheelhouse
bash scripts/kits-two-venv/gh-release-venv/start_runtime_from_release.sh --tag v0.1.0  # release wheels
bash scripts/stop_runtime.sh                             # stops either start path (+ product UDS)
bash scripts/cleanup_runtime.sh --full                     # stop + reset harness (see kits-two-venv README)
```

## Admin (reference)

See [`admin/README.md`](admin/README.md) and [`docs/dev/policy-seeding.md`](../docs/dev/policy-seeding.md) for `seed_policy.py` — orchestrator pattern (load → validate bundles → POST), UDS or `INTENTFRAME_POLICY_URL`.

## Git Hooks

The `git-hooks/` directory contains shared git hooks that are tracked in the repository. These enforce code hygiene rules locally, before anything reaches CI.

### Setup (run once per clone)

```bash
bash scripts/install-hooks.sh
```

This runs `git config core.hooksPath scripts/git-hooks`, pointing git at the shared hooks directory instead of the default `.git/hooks/`.

### What the hooks do

| Hook | What it blocks |
|---|---|
| `pre-commit` | Commits containing `.vscode/`, `.idea/`, `.env`, `.aienv` |

The same checks are enforced server-side by the `Repo Hygiene` CI workflow (`.github/workflows/repo-hygiene.yml`), which acts as a backstop if local hooks are bypassed.
