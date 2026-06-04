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

GitHub release wheels are the interim distribution path while PyPI first-project creation is staged.

After creating the GitHub release with the matching tag:

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

Use wheels for consumer installs. Sdists are optional on the GitHub release page.

## PyPI Publishing

For a first production PyPI release, do not publish all 18 new project names in one production batch. Use the documented groups:

```bash
python scripts/release/publish.py --group 1 --target pypi
python scripts/release/publish.py --group 2 --target pypi
python scripts/release/publish.py --group 3 --target pypi
```

If PyPI returns `429 Too many new projects created`, stop retrying the same batch. Wait, then resume with smaller local uploads using `--no-build` and one package selector at a time.

TestPyPI can usually use `--all`, but production PyPI should use groups until all project names exist.

## Consumer Docs Checklist

When publishing a new lockstep version:

- Update [`../../scripts/github-install/example-pyproject.toml`](../../scripts/github-install/example-pyproject.toml) if the public template should point to the newest release.
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
5. Update `scripts/github-install/example-pyproject.toml`.
6. Update `docs/package-consumers.md` and `docs/licensing.md`.
7. Run `validate_publish.sh` and the release install verifier.

## Common Mistakes

| Mistake | Result | Fix |
|---------|--------|-----|
| Tag version differs from wheel version | Consumer URLs 404 | Keep tag, package, and wheel versions aligned |
| Apache package imports AGPL package | Permissive dependency chain is broken | Move shared contracts into an Apache package |
| New package missing from consumer sources | `uv` falls back to PyPI and fails while staging | Update `example-pyproject.toml` and `docs/package-consumers.md` |
| Replacing release assets after announcement | Users lose reproducibility | Publish a new tag/version instead |
| Publishing all new names to production PyPI at once | PyPI 429 rate limit | Use groups or one-package local uploads |

## Source Of Truth

For exact commands and operational detail, prefer the script runbooks. This guide explains the maintainer model and the checklist that keeps code, package metadata, release assets, docs, and licenses aligned.
