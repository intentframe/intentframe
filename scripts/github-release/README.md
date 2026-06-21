# GitHub release wheel publishing

Optional mirror of the same wheels published on [PyPI](https://pypi.org/) for **`0.1.1`**. Use when you need URL-pinned installs, offline verification, or release-asset boot tests — not as the primary consumer path.

**Primary install:** [`../../docs/package-consumers.md`](../../docs/package-consumers.md) and [`../github-install/example-pyproject-pypi.toml`](../github-install/example-pyproject-pypi.toml).

This does **not** create a PyPI index. GitHub consumers install direct wheel URLs with `uv` or `pip`.

Related docs:

- Build, validation, and PyPI publishing: [`../release/README.md`](../release/README.md)
- Install verification and consumer TOML templates: [`../github-install/README.md`](../github-install/README.md)
- Package licensing split: [`../../docs/licensing.md`](../../docs/licensing.md)

## Scripts (by directory)

| Location | Script | Purpose |
|----------|--------|---------|
| [`../github-install/`](../github-install/README.md) | `verify_release_install.sh` | Disposable venv: install all 18 wheels + import smoke test |
| [`../kits-two-venv/gh-release-venv/`](../kits-two-venv/gh-release-venv/README.md) | `start_runtime_from_release.sh` | `.venv-release` + boot supervisor + edge (full stack test) |
| [`../kits-two-venv/`](../kits-two-venv/README.md) | `stop_runtime.sh`, `run_demo_tests.sh` | Shared stop and demo tests over edge HTTP |

## Verification layers

After uploading wheels to a release, run in order:

1. **Install** — `verify_release_install.sh` (no long-running processes).
2. **Boot** — `gh-release-venv/start_runtime_from_release.sh` (supervisor + edge from release wheels).
3. **Behavior** (optional) — `run_demo_tests.sh` from client `.venv`, then `stop_runtime.sh`.

## What We Publish

Publish the **wheel** files from `dist/publish/` as GitHub release assets.

For `v0.1.1`, the install URLs look like:

```text
https://github.com/intentframe/intentframe/releases/download/v0.1.1/intentframe_core-0.1.1-py3-none-any.whl
```

Important:

- `.whl` files are the important artifacts for consumer installs.
- `.tar.gz` source distributions are optional on GitHub releases.
- GitHub Actions artifacts are **not** suitable for consumers; they expire and may require auth.
- GitHub release assets are stable public URLs while the repository is public.

## Release Invariant

For this workflow to stay simple:

```text
Git tag version == package version == wheel filename version
```

Example:

```text
tag:         v0.2.0
package:     version = "0.2.0"
wheel:       intentframe_core-0.2.0-py3-none-any.whl
```

Do not create a tag like `v0.2.0-alpha.1` if the wheels are named
`*-0.2.0-*.whl`, unless you also update the install/verify scripts to accept a
separate package version.

## One-Time Assumptions

The current scripts assume:

- 18 IntentFrame distributions.
- All distributions are lockstep-versioned.
- All wheel filenames are `py3-none-any`.
- Python floor is **3.14**.
- Release assets are public.
- Consumers use `uv` `[tool.uv.sources]` or direct `pip`/`uv pip` URL installs.

If any of those change, update:

- [`../github-install/verify_release_install.sh`](../github-install/verify_release_install.sh)
- [`../kits-two-venv/gh-release-venv/start_runtime_from_release.sh`](../kits-two-venv/gh-release-venv/start_runtime_from_release.sh)
- [`../github-install/example-pyproject.toml`](../github-install/example-pyproject.toml)
- This README

## Release Checklist

### 1. Set the Package Version

All packages must share the same version.

```bash
python scripts/release/set_version.py 0.2.0
python scripts/release/set_version.py 0.2.0 --check
```

Review and commit the version change before publishing.

### 2. Build and Validate

Build every package and run the release validation.

```bash
./scripts/release/validate_publish.sh
```

Expected output directory:

```text
dist/publish/
```

Expected artifact shape:

```text
18 wheels:  *.whl
18 sdists:  *.tar.gz
```

Quick local checks:

```bash
ls dist/publish/*.whl | wc -l
ls dist/publish/*.tar.gz | wc -l
```

For the GitHub release install path, only the wheels are required.

### 3. Create the GitHub Release

Create a normal GitHub release with a tag matching the package version.

For example:

```text
tag:   v0.2.0
title: IntentFrame v0.2.0 — <short release theme>
```

Use the GitHub UI or `gh`.

```bash
gh release create v0.2.0 \
  --title "IntentFrame v0.2.0 — <short release theme>" \
  --notes-file /path/to/release-notes.md
```

If you create the release in the UI first, upload assets later with the next
step.

### 4. Upload Wheels

Upload wheels from the validated build output.

```bash
gh release upload v0.2.0 dist/publish/*.whl
```

If the release already has assets with the same filenames and you are replacing
them before announcing the release:

```bash
gh release upload v0.2.0 dist/publish/*.whl --clobber
```

Do **not** silently replace release assets after users may have installed them.
Prefer a new version/tag. Replacing a wheel under the same filename makes
reproducibility worse.

### 5. Verify Uploaded Assets

Confirm GitHub sees all wheels:

```bash
gh release view v0.2.0 \
  --repo intentframe/intentframe \
  --json assets \
  --jq '.assets[].name' | sort
```

Then run install + boot smoke tests:

```bash
./scripts/github-install/verify_release_install.sh --tag v0.2.0
export OPENAI_API_KEY=sk-...
bash scripts/kits-two-venv/gh-release-venv/start_runtime_from_release.sh --tag v0.2.0
bash scripts/kits-two-venv/stop_runtime.sh
```

The verifier creates a temp venv, installs all 18 wheels from the release, checks
distribution versions, and imports the installable modules. Success ends with:

```text
SUCCESS: all IntentFrame release wheels installed and importable
```

### 6. Update Consumer Template

For each new public release, update both consumer templates if the docs should point at the newest version:

```text
scripts/github-install/example-pyproject-pypi.toml   # PyPI (primary)
scripts/github-install/example-pyproject.toml        # GitHub URL fallback
```

Replace both:

```text
v0.1.1  -> v0.2.0
0.1.1   -> 0.2.0
```

Then validate syntax:

```bash
python3 - <<'PY'
import tomllib
from pathlib import Path
tomllib.loads(Path("scripts/github-install/example-pyproject.toml").read_text())
print("TOML OK")
PY
```

## Consumer Install Pattern

In a third-party workspace, consumers copy:

```text
scripts/github-install/example-pyproject.toml
```

They should edit:

- `project.name`
- `project.version`
- `[project].dependencies` to include only the IntentFrame packages they import directly

They must keep all **18** IntentFrame entries in `[tool.uv.sources]` on this path, because transitive IntentFrame dependencies also need release URLs. For normal projects, prefer PyPI via [`example-pyproject-pypi.toml`](../github-install/example-pyproject-pypi.toml) instead.

Then:

```bash
uv sync
```

Ad-hoc install also works:

```bash
uv pip install https://github.com/intentframe/intentframe/releases/download/v0.2.0/intentframe_actor-0.2.0-py3-none-any.whl
```

For real third-party projects, prefer the `pyproject.toml` source block over
ad-hoc commands so installs are reproducible.

## Wheels vs Sdists

| Artifact | Publish to GitHub? | Why |
|----------|--------------------|-----|
| `.whl` | Yes | Required for fast direct URL installs. uv/pip can install immediately. |
| `.tar.gz` | Optional | Useful source archive, but uv must build it before install. Not needed for the release-URL path. |

If disk/UI clutter matters, upload only wheels. If you want source provenance on
the release page too, upload both, but consumers should still point at wheels.

## Updating Future Releases

For a normal future release:

1. Choose the next lockstep package version (`0.2.0`, `0.2.1`, etc.).
2. Run `set_version.py`.
3. Commit version and dependency pin changes.
4. Run `validate_publish.sh`.
5. Create GitHub release tag `v<version>`.
6. Upload `dist/publish/*.whl`.
7. Run `verify_release_install.sh --tag v<version>`, then `gh-release-venv/start_runtime_from_release.sh` (and `stop_runtime.sh`).
8. Update `example-pyproject.toml` and `example-pyproject-pypi.toml` if the docs should point at the newest release.
9. Publish new versions to PyPI/TestPyPI via [`../release/README.md`](../release/README.md) (primary consumer path).

If adding, removing, or renaming a package:

1. Update package metadata and lockstep dependencies.
2. Update publish groups in both:
   - [`.github/workflows/release.yml`](../../.github/workflows/release.yml)
   - [`../release/publish.py`](../release/publish.py)
3. Update [`../github-install/verify_release_install.sh`](../github-install/verify_release_install.sh).
4. Update [`../kits-two-venv/gh-release-venv/start_runtime_from_release.sh`](../kits-two-venv/gh-release-venv/start_runtime_from_release.sh).
5. Update [`../github-install/example-pyproject.toml`](../github-install/example-pyproject.toml).
6. Update docs listing the 18-package assumption.

If a wheel stops being `py3-none-any`:

- Confirm the platform tag that `uv build` produces.
- Update the GitHub install URLs and verify script.
- Consider whether consumers on other OS/Python combinations can still install.

## Common Mistakes

| Mistake | Result | Fix |
|---------|--------|-----|
| Tag version differs from wheel version | URL 404 in consumer TOML / verifier | Keep tag and package version aligned, or add a separate version flag to the verifier. |
| Upload only sdists | Slower installs, possible build failures | Upload wheels. |
| Forget a transitive package in `[tool.uv.sources]` | uv may resolve a missing IntentFrame dep from PyPI at the wrong version, or fail | Keep all 18 sources in the GitHub template, or use PyPI ([`example-pyproject-pypi.toml`](../github-install/example-pyproject-pypi.toml)). |
| Replace assets after announcement | Reproducibility risk | Publish a new version instead. |
| Use GitHub Actions artifacts as install URLs | Expiry/auth problems | Use GitHub release assets. |
| Private repo release assets | Consumers need auth | Keep repo public or use an authenticated package/index solution. |

## Start the Runtime From a Release (boot smoke test)

Verify the published wheels actually boot the full runtime — supervisor + its
spawned services + edge — not just that they install.

```bash
export OPENAI_API_KEY=sk-...
bash scripts/kits-two-venv/gh-release-venv/start_runtime_from_release.sh --tag v0.1.1
```

What it does:

1. Installs all 18 release wheels into `.venv-release` (separate from `.venv` / `.venv-runtime`).
2. Resolves `INTENTFRAME_CORE_CONFIG` / `INTENTFRAME_SUPERVISOR_CONFIG` / `INTENTFRAME_EDGE_CONFIG` from the installed native-kit wheel.
3. Starts `supervisor.main start` (spawns policy-registry, resource-registry, executor, intentframe-server over UDS) and waits for core health.
4. Starts `intentframe_edge` on `:8443` and waits for HTTP `/health`.

Environment and run/log dirs match `scripts/kits-two-venv/start_runtime.sh`
exactly — `~/.intentframe/run` and `~/.intentframe/logs` are used as-is (no
`INTENTFRAME_RUN_DIR` / `INTENTFRAME_LOG_DIR` override). `EXECUTOR_CONFIG`
defaults to `demo/config/executor_hashicorp.yaml` (override via env), so the repo
checkout still supplies the operator executor profile.

Run demo tests against it from the client venv (same as the harness):

```bash
bash scripts/kits-two-venv/run_demo_tests.sh demo/tests/test_attacks.py 1 2 3
```

Stop with the shared harness stopper (all harness pid dirs, product supervisor
pgid, and edge port `8443`):

```bash
bash scripts/kits-two-venv/stop_runtime.sh
```

Notes:

- This installs the native kit directly into `.venv-release`, so it does **not**
  exercise the `INTENTFRAME_KITS_DIR` wheelhouse + constraints boundary that the
  kits-two-venv harness tests. It validates that the published wheels boot the
  stack, which is what a release consumer experiences.
- Requires `uv`, network access to the release + PyPI, and Python 3.14.

## PyPI consumers

All **18** `packages/` distributions are on PyPI @ **`0.1.1`**. Third-party projects: [`docs/package-consumers.md`](../../docs/package-consumers.md). GitHub release wheels remain an optional URL-pinned fallback.

## Maintainer checklist
