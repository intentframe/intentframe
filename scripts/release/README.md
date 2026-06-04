# Release tooling (`packages/` → PyPI)

Only distributions under `packages/` are published. Product-facing code (root `intentframe`, gateway, Jarvis, EDI) stays out of scope.

## Lockstep versioning

All 18 packages share one version. Intra-workspace dependencies are pinned to `==<version>` so wheels resolve correctly off PyPI (workspace sources are dev-only).

```bash
# Apply pins for a release (review git diff, then commit)
python scripts/release/set_version.py 0.1.0

# CI guard: fail if any package drifted
python scripts/release/set_version.py 0.1.0 --check
```

## Pre-publish validation

Builds every package, runs `twine check`, verifies wheels ship `LICENSE` and key data files, then installs from the local `dist/publish/` set (TestPyPI/PyPI index for third-party deps) to prove the dependency graph is closed.

```bash
chmod +x scripts/release/validate_publish.sh
./scripts/release/validate_publish.sh
```

Requires Python **3.14** (project floor) and `uv` on PATH.

## Publish groups (PyPI new-project limit)

PyPI enforces a per-account quota on **first-time project registration**. Uploading all 18 new names in one shot often returns `429 Too many new projects created`. Use three groups of six (leaf-first), spaced hours apart if needed:

| Group | Packages |
|-------|----------|
| **1** | `intentframe-core`, `intentframe-policy-registry`, `command-shield`, `intentframe-prompt-library`, `intentframe-bundle-sdk`, `intentframe-executor-sdk` |
| **2** | `intentframe-executor-client`, `intentframe-credentials`, `intentframe-client`, `intentframe-actor`, `intentframe-components`, `intentframe-executor` |
| **3** | `intentframe-server`, `intentframe-runtime`, `intentframe-supervisor`, `intentframe-native-kit`, `intentframe-proxy`, `intentframe-edge` |

The groups are defined **independently** in two places: inline in [`release.yml`](../../.github/workflows/release.yml) (CI) and in [`publish.py`](publish.py) (terminal). Keep both in sync if the buckets change.

## GitHub Actions (manual)

Workflow: [`.github/workflows/release.yml`](../../.github/workflows/release.yml)

1. Repo secrets: `TEST_PYPI_API_TOKEN`, `PYPI_API_TOKEN`.
2. Actions → **Release (packages/ → PyPI)** → Run workflow.
3. Inputs: `target`, `group` (`1` / `2` / `3` or `all`), `version`, `confirm` = `publish`.

The build job always validates all 18 packages; the publish job uploads only the selected group. Uploads use `skip-existing` so partial runs are safe to retry.

```bash
# Example: production group 2
gh workflow run release.yml --ref main \
  -f target=pypi -f group=2 -f version=0.1.0 -f confirm=publish
```

## Terminal publish (`publish.py`)

Build and upload one or more packages without GitHub Actions:

```bash
export PYPI_API_TOKEN='pypi-...'   # or TEST_PYPI_API_TOKEN

# one package (name, directory, or short alias)
python scripts/release/publish.py core --target pypi

# predefined group
python scripts/release/publish.py --group 1 --target pypi

# everything
python scripts/release/publish.py --all --target pypi

# build + twine check only
python scripts/release/publish.py --all --target testpypi --dry-run

# upload artifacts already in dist/publish/
python scripts/release/publish.py --group 3 --target pypi --no-build
```

## Suggested release order

1. `set_version.py <version>` → `uv sync` → run tests
2. `./scripts/release/validate_publish.sh`
3. TestPyPI: workflow or `publish.py --all --target testpypi`; verify install from TestPyPI
4. PyPI: groups `1` → `2` → `3` (or `all` once names exist), hours apart if rate-limited
5. `git tag v<version> && git push --tags`

See [docs/licensing.md](../../docs/licensing.md) for AGPL vs Apache split.
