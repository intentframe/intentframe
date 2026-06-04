# Release tooling (`packages/` → PyPI)

Only distributions under `packages/` are published. Product-facing code (root `intentframe`, gateway, Jarvis, EDI) stays out of scope. See [docs/licensing.md](../../docs/licensing.md) for AGPL vs Apache split.

**Interim install from GitHub release wheels** (while PyPI new-project limits apply): build → upload `.whl` assets → verify. Full manual runbook: [`../github-release/README.md`](../github-release/README.md).

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

Output lands in **`dist/publish/`** (wheel + sdist per package). Local `publish.py` and the CI build job both use this directory.

## PyPI new-project rate limits

PyPI creates a **project** the first time a distribution name is uploaded. That step is rate-limited separately from uploading new **versions** to an existing project.

| What triggers the limit | What does not |
|-------------------------|---------------|
| First upload of a new PyPI project name | New release of a project that already exists on the index |
| | Re-uploading the same file (`skip-existing` skips it) |

Warehouse applies two limiters (see [pypi/warehouse `config.py`](https://github.com/pypi/warehouse/blob/main/warehouse/config.py)): **per user** (default `20 per hour`) and **per IP** (default `40 per hour`). Either can return:

```text
HTTP 429 Too many new projects created
```

Practical notes:

- **API tokens do not bypass the limit.** Tokens only identify the user; the quota is keyed on user id and client IP.
- **New accounts** (verified email + 2FA still required) often hit limits sooner than the public defaults suggest; spacing uploads over **hours or days** is common for a first monorepo release.
- **GitHub Actions** uses shared egress IPs. A workflow that uploads many new names in one job can exhaust the **IP** bucket even when your user bucket has headroom. Prefer **local, one-package uploads** from a stable home IP when rate-limited.
- **Browser upload is not available.** PyPI deprecated manual file upload in the web UI; publishing uses `twine` / the upload API ([PyPI help](https://pypi.org/help/#manual-upload)).
- **Empty projects cannot be pre-created** on a personal account via the website. Organization accounts can create empty projects in the org UI ([docs](https://docs.pypi.org/organization-accounts/actions/project-actions/)), but that path only helps after org approval.
- If limits persist after waiting, open [pypi/support](https://github.com/pypi/support/issues/new/choose) (same class of issue as [pypi/support#10572](https://github.com/pypi/support/issues/10572)).

### First-time production PyPI playbook

1. Run full validation and publish **all 18** to **TestPyPI** first (`group=all` is fine there).
2. On **production PyPI**, use groups **`1` → `2` → `3`** (six packages each), not `all`, until every project name exists.
3. Wait **at least an hour** between groups if you see `429`; for a day-old account, **24 hours** between attempts is often necessary.
4. After `intentframe-core` and `intentframe-policy-registry` exist, packages that depend on them become installable from PyPI.
5. Prefer **one package per `publish.py` invocation** when self-healing from `429` (a failed `twine` call aborts the rest of that batch).

Priority order when trickling manually: `core` → `policy-registry` → remaining group 1 → group 2 → group 3.

## Publish groups

Use three groups of six (leaf-first) so CI and local uploads do not register 18 new names in a single `twine` session:

| Group | Packages |
|-------|----------|
| **1** | `intentframe-core`, `intentframe-policy-registry`, `command-shield`, `intentframe-prompt-library`, `intentframe-bundle-sdk`, `intentframe-executor-sdk` |
| **2** | `intentframe-executor-client`, `intentframe-credentials`, `intentframe-client`, `intentframe-actor`, `intentframe-components`, `intentframe-executor` |
| **3** | `intentframe-server`, `intentframe-runtime`, `intentframe-supervisor`, `intentframe-native-kit`, `intentframe-proxy`, `intentframe-edge` |

The groups are defined **independently** in two places:

- [`.github/workflows/release.yml`](../../.github/workflows/release.yml) — inline bash in the **Stage upload group** step
- [`publish.py`](publish.py) — `GROUPS` dict

Keep both in sync if the buckets change. Terminal publish and CI are intentionally decoupled (no shared Python module in the workflow).

## GitHub Actions (manual)

Workflow: [`.github/workflows/release.yml`](../../.github/workflows/release.yml)

### Jobs and directories

| Job / step | Directory | Contents |
|------------|-----------|----------|
| **Build & validate** | `dist/publish/` | All 18 packages after `validate_publish.sh` (artifact `dist-publish`) |
| **Stage upload group** | `dist/upload/` | Only wheels/sdists for the selected `group` input (copied from `dist/publish/`) |
| **Publish to (Test)PyPI** | `dist/upload/` | `pypa/gh-action-pypi-publish` `packages-dir` — uploads the staged subset only |

`packages-dir` was changed from `dist/publish` to **`dist/upload`** so the publish job respects the `group` input. Without staging, every workflow run would upload all 36 artifacts regardless of `group`.

### Running the workflow

1. Repo secrets: `TEST_PYPI_API_TOKEN`, `PYPI_API_TOKEN` (environment-scoped in GitHub **Environments** `testpypi` / `pypi` if you use approval gates).
2. Actions → **Release (packages/ → PyPI)** → Run workflow.
3. Inputs:
   - `target` — `testpypi` or `pypi`
   - `group` — `1`, `2`, `3`, or `all` (use `1`/`2`/`3` for first production release)
   - `version` — must match lockstep pins (e.g. `0.1.0`)
   - `confirm` — must be exactly `publish`

The build job always validates all 18 packages. The publish job uploads only the staged group. Uploads use **`skip-existing`** so partial runs are safe to retry (already-uploaded files are skipped; `429` still aborts the rest of that run).

```bash
# Example: production group 2
gh workflow run release.yml --ref main \
  -f target=pypi -f group=2 -f version=0.1.0 -f confirm=publish
```

Avoid re-running `group=all` on production PyPI while new names are still being registered; it maximizes new-project creations per job and worsens `429` behavior on shared CI IPs.

## Terminal publish (`publish.py`)

Build and upload without GitHub Actions. Reads/writes **`dist/publish/`** only (no `dist/upload/` — that path is CI-specific).

```bash
export PYPI_API_TOKEN='pypi-...'   # or TEST_PYPI_API_TOKEN

# one package (distribution name, packages/ dir name, or short alias)
python scripts/release/publish.py core --target pypi

# predefined group (six packages, one twine invocation)
python scripts/release/publish.py --group 1 --target pypi

# everything (18 packages — OK on TestPyPI; risky for first prod release)
python scripts/release/publish.py --all --target pypi

# build + twine check only
python scripts/release/publish.py --all --target testpypi --dry-run

# upload artifacts already in dist/publish/ (skip build)
python scripts/release/publish.py core --target pypi --no-build
python scripts/release/publish.py --group 3 --target pypi --no-build
```

Auth: `TEST_PYPI_API_TOKEN` / `PYPI_API_TOKEN`, else `TWINE_PASSWORD`, else `~/.pypirc`.

When rate-limited on production, use **`--no-build`** and **one selector per command** so a `429` on the second package does not roll back the first.

## GitHub release wheels (interim)

Before or in parallel with PyPI, you can ship the same `dist/publish/*.whl` files as **GitHub release assets** so other repos install by URL (`uv` `[tool.uv.sources]`). Full release steps: [`../github-release/README.md`](../github-release/README.md). Consumer `pyproject.toml` and verifier: [`../github-install/README.md`](../github-install/README.md).

```bash
./scripts/release/validate_publish.sh
gh release upload v0.1.0 dist/publish/*.whl    # after creating the release tag
./scripts/github-install/verify_release_install.sh --tag v0.1.0
```

Use **wheels only** for this path; sdists on the release are optional. Tag version must match wheel versions (`v0.1.0` → `*-0.1.0-*.whl`).

## Suggested release order

1. `set_version.py <version>` → `uv sync` → run tests
2. `./scripts/release/validate_publish.sh`
3. **GitHub release (optional, interim):** create tag → `gh release upload v<version> dist/publish/*.whl` → `verify_release_install.sh --tag v<version>`
4. **TestPyPI:** workflow `group=all` or `publish.py --all --target testpypi`; verify `pip install` from TestPyPI
5. **PyPI (first time):** groups `1` → `2` → `3` via workflow or local `publish.py`, spaced if rate-limited; then `all` only when every name already exists
6. `git tag v<version> && git push --tags` (if not already tagged for the GitHub release)

## Troubleshooting

| Symptom | Likely cause | What to do |
|---------|--------------|------------|
| `429 Too many new projects created` | New-project quota (user and/or IP) | Stop retrying for 24h; upload one name locally with `--no-build`; file [pypi/support](https://github.com/pypi/support/issues/new/choose) if still blocked |
| `pip install` missing `intentframe-core` | Dependency not on PyPI yet | Publish `core` and `policy-registry` first |
| Workflow uploaded wrong subset | Wrong `group` or staging skipped | Confirm **Stage upload group** ran and `packages-dir` is `dist/upload` |
| `confirm` set but no publish job | `confirm` ≠ `publish` | Re-run with `confirm=publish` |
| Partial CI success | `twine` fail-fast after first hard error | Re-run same `group`; `skip-existing` skips completed files |
