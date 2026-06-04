# scripts/

Utility scripts for local development setup.

## PyPI release (`packages/` only)

See [`release/README.md`](release/README.md) — lockstep versioning (`set_version.py`), validation (`validate_publish.sh`), grouped GitHub workflow ([`release.yml`](../.github/workflows/release.yml)), and terminal uploads (`publish.py`).

## Kits two-venv harness (substrate + wheel, edge for tests)

See [`kits-two-venv/README.md`](kits-two-venv/README.md) — bare `.venv-runtime`, constrained `uv pip install` of kit wheels from `.intentframe/kits/`, start supervisor + edge, run demo tests from `.venv` over HTTP. Per-script behavior: [Script internals](kits-two-venv/README.md#script-internals).

```bash
bash scripts/kits-two-venv/start_runtime.sh   # or: start via kits-two-venv README
bash scripts/stop_runtime.sh                  # stop supervisor + edge
bash scripts/cleanup_runtime.sh --full        # stop + reset harness (see kits-two-venv README)
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
