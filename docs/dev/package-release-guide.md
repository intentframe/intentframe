# Package Release Guide

This guide is for IntentFrame maintainers changing, validating, or publishing the package set under `packages/`.

Use this as the developer-facing overview. The scripts still own the exact commands and edge cases:

- [`../../scripts/release/README.md`](../../scripts/release/README.md) — PyPI/TestPyPI release process
- [`../../scripts/github-release/README.md`](../../scripts/github-release/README.md) — GitHub release wheel publishing
- [`../../scripts/github-install/README.md`](../../scripts/github-install/README.md) — release install verification
- [`../licensing.md`](../licensing.md) — package-by-package license table

## Release Shape

IntentFrame `v0.1.0` publishes 18 Python distributions from `packages/`. They are lockstep-versioned: one release tag, one package version, one dependency pin version.

```text
Git tag:          v0.1.0
Package version:  0.1.0
Wheel version:    intentframe_core-0.1.0-py3-none-any.whl
```

Do not create a release tag whose version differs from the package versions unless the install and verification scripts are updated to support separate tag/package versions.

## Package Groups

| Group | Packages | License family |
|-------|----------|----------------|
| Core / SDK / policy | `intentframe-core`, `intentframe-policy-registry`, `command-shield`, `intentframe-prompt-library`, `intentframe-bundle-sdk`, `intentframe-executor-sdk` | Apache-2.0 |
| Client / actor / components / executor | `intentframe-executor-client`, `intentframe-credentials`, `intentframe-client`, `intentframe-actor`, `intentframe-components`, `intentframe-executor` | Mixed |
| Runtime / kit / ingress | `intentframe-server`, `intentframe-runtime`, `intentframe-supervisor`, `intentframe-native-kit`, `intentframe-proxy`, `intentframe-edge` | Mixed |

The publish groups are duplicated in:

- [`.github/workflows/release.yml`](../../.github/workflows/release.yml)
- [`../../scripts/release/publish.py`](../../scripts/release/publish.py)

If a package is added, removed, or renamed, update both places and the consumer template.

## License Boundaries

The repository root product code remains AGPL-3.0-only. Publishable packages use package-level licenses:

- AGPL-3.0 runtime stack: executor, server, components, runtime, supervisor
- Apache-2.0 SDKs, neutral DTOs, policy models, clients, ingress helpers, credential package, native kit, prompt library, and command analysis library

Before moving code between packages, check the dependency direction:

- AGPL packages may depend on Apache packages.
- Apache packages should not import AGPL packages.
- Shared contracts needed by both sides should live in Apache packages such as `intentframe-core`, `intentframe-bundle-sdk`, or `intentframe-executor-sdk`.

Update [`../licensing.md`](../licensing.md) and package `pyproject.toml` metadata whenever a package boundary or license changes.

## Before Publishing

1. Confirm the package set and dependency graph are intentional.
2. Set the lockstep version:

   ```bash
   python scripts/release/set_version.py 0.1.0
   python scripts/release/set_version.py 0.1.0 --check
   ```

3. Review the diff, especially:

   - package versions
   - intra-IntentFrame dependency pins
   - `LICENSE` files
   - `license` and `license-files` metadata

4. Build and validate:

   ```bash
   ./scripts/release/validate_publish.sh
   ```

Validation should produce wheels and sdists in `dist/publish/`.

## GitHub Release Wheels

Optional mirror of the same wheels published on PyPI — upload after creating the GitHub release tag:

```bash
gh release upload v0.1.0 dist/publish/*.whl
./scripts/github-install/verify_release_install.sh --tag v0.1.0
```

Optional runtime boot smoke test:

```bash
export OPENAI_API_KEY=sk-...
bash scripts/kits-two-venv/gh-release-venv/start_runtime_from_release.sh --tag v0.1.0
bash scripts/kits-two-venv/stop_runtime.sh
```

Use wheels for GitHub URL installs. Sdists are optional on the release page; both ship on PyPI.

## PyPI Publishing

All **18** project names exist on production PyPI for **`0.1.0`**. For **subsequent** lockstep versions, `--all` / `group=all` is usually fine (new **versions**, not new projects).

First-time registration (historical): use groups `1` → `2` → `3` or one-package local uploads if you see `429 Too many new projects created`.

## Consumer Docs Checklist

When publishing a new lockstep version:

- Update [`../../scripts/github-install/example-pyproject-pypi.toml`](../../scripts/github-install/example-pyproject-pypi.toml) and [`example-pyproject.toml`](../../scripts/github-install/example-pyproject.toml) for new versions.
- Update [`../package-consumers.md`](../package-consumers.md) if package recommendations or release mechanics changed.
- Update [`../licensing.md`](../licensing.md) if package boundaries or licenses changed.
- Update [`../../CHANGELOG.md`](../../CHANGELOG.md) with the public release summary.
- Confirm [`../README.md`](../README.md) points consumers to the right guide.

## Package Change Checklist

When adding, removing, or renaming a distribution:

1. Update the package metadata and lockstep dependency pins.
2. Update publish groups in `.github/workflows/release.yml` and `scripts/release/publish.py`.
3. Update `scripts/github-install/verify_release_install.sh`.
4. Update `scripts/kits-two-venv/gh-release-venv/start_runtime_from_release.sh`.
5. Update `scripts/github-install/example-pyproject.toml` and `example-pyproject-pypi.toml`.
6. Update `docs/package-consumers.md` and `docs/licensing.md`.
7. Run `validate_publish.sh` and the release install verifier.

## Common Mistakes

| Mistake | Result | Fix |
|---------|--------|-----|
| Tag version differs from wheel version | Consumer URLs 404 | Keep tag, package, and wheel versions aligned |
| Apache package imports AGPL package | Permissive dependency chain is broken | Move shared contracts into an Apache package |
| New package missing from GitHub wheel template | URL install fails for transitive dep | Update both `example-pyproject*.toml` and `docs/package-consumers.md` |
| Replacing release assets after announcement | Users lose reproducibility | Publish a new tag/version instead |
| Publishing many **new** PyPI project names at once | PyPI 429 rate limit | Use groups or one-package local uploads (first-time only) |

## Source Of Truth

For exact commands and operational detail, prefer the script runbooks. This guide explains the maintainer model and the checklist that keeps code, package metadata, release assets, docs, and licenses aligned.
