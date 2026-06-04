# Package Consumer Guide

This guide is for people installing IntentFrame packages into another Python project.

IntentFrame `v0.1.0` ships 18 lockstep-versioned wheels as GitHub release assets while PyPI publishing is staged. You do not need a custom package index. A consumer project can point `uv` at the release wheel URLs until the same packages are available on PyPI.

## Current Distribution Path

| Channel | Status | Use when |
|---------|--------|----------|
| GitHub release wheels | Available for `v0.1.0` | You need packages before PyPI publishing is complete |
| PyPI | Staged | Use once all required IntentFrame package names exist on PyPI |
| Source clone | Available | You are contributing to IntentFrame itself or running the full product workspace |

Release: [`v0.1.0`](https://github.com/intentframe/intentframe/releases/tag/v0.1.0)

## Pick Packages

For a normal third-party agent or plugin, start with the author-facing SDKs:

```toml
dependencies = [
  "intentframe-actor==0.1.0",
  "intentframe-bundle-sdk==0.1.0",
  "intentframe-executor-sdk==0.1.0",
]
```

Add other packages only if your project imports them directly:

| Package | Use it when |
|---------|-------------|
| `intentframe-actor` | Your agent submits intents to an IntentFrame runtime |
| `intentframe-bundle-sdk` | You author action bundles for the policy pipeline |
| `intentframe-executor-sdk` | You author executor packs/adapters |
| `intentframe-client` | You call the IntentFrame server API directly |
| `intentframe-core` | You need shared DTOs/contracts |
| `command-shield` | You need shell command capability analysis |
| `intentframe-credentials` | You integrate with the credential vault client/backends |
| `intentframe-native-kit` | You want the first-party native bundles, executor packs, and profiles |
| `intentframe-runtime`, `intentframe-supervisor`, `intentframe-edge` | You are booting a runtime stack from packages |

See [`licensing.md`](licensing.md) before embedding runtime packages. Some packages are Apache-2.0; runtime stack packages are AGPL-3.0.

## Install With `uv`

Copy [`../scripts/github-install/example-pyproject.toml`](../scripts/github-install/example-pyproject.toml) into your project and edit:

- `project.name`
- `project.version`
- `[project].dependencies`, keeping only the IntentFrame packages your project imports directly

Keep all IntentFrame entries in `[tool.uv.sources]` while installing from GitHub release assets. `uv` applies those sources to the whole dependency resolution, including transitive IntentFrame dependencies.

Then run:

```bash
uv sync
```

## Why All Sources Are Listed

IntentFrame packages depend on each other. If your project depends on `intentframe-actor`, `uv` may still need `intentframe-core`, `intentframe-client`, or other IntentFrame packages through transitive dependencies.

Until PyPI has every required package, `[tool.uv.sources]` tells `uv` where to find each IntentFrame distribution. Your direct dependency list should stay small; the source map can include all 18 packages.

## Ad-Hoc Install

For quick experiments, you can install wheel URLs directly, but you must include every IntentFrame package in the dependency closure. While PyPI is staged, the simplest ad-hoc rule is: install all 18 IntentFrame wheel URLs, not only the packages you import directly.

```bash
uv pip install \
  https://github.com/intentframe/intentframe/releases/download/v0.1.0/command_shield-0.1.0-py3-none-any.whl \
  https://github.com/intentframe/intentframe/releases/download/v0.1.0/intentframe_actor-0.1.0-py3-none-any.whl \
  https://github.com/intentframe/intentframe/releases/download/v0.1.0/intentframe_bundle_sdk-0.1.0-py3-none-any.whl \
  https://github.com/intentframe/intentframe/releases/download/v0.1.0/intentframe_client-0.1.0-py3-none-any.whl \
  https://github.com/intentframe/intentframe/releases/download/v0.1.0/intentframe_components-0.1.0-py3-none-any.whl \
  https://github.com/intentframe/intentframe/releases/download/v0.1.0/intentframe_core-0.1.0-py3-none-any.whl \
  https://github.com/intentframe/intentframe/releases/download/v0.1.0/intentframe_credentials-0.1.0-py3-none-any.whl \
  https://github.com/intentframe/intentframe/releases/download/v0.1.0/intentframe_edge-0.1.0-py3-none-any.whl \
  https://github.com/intentframe/intentframe/releases/download/v0.1.0/intentframe_executor-0.1.0-py3-none-any.whl \
  https://github.com/intentframe/intentframe/releases/download/v0.1.0/intentframe_executor_client-0.1.0-py3-none-any.whl \
  https://github.com/intentframe/intentframe/releases/download/v0.1.0/intentframe_executor_sdk-0.1.0-py3-none-any.whl \
  https://github.com/intentframe/intentframe/releases/download/v0.1.0/intentframe_native_kit-0.1.0-py3-none-any.whl \
  https://github.com/intentframe/intentframe/releases/download/v0.1.0/intentframe_policy_registry-0.1.0-py3-none-any.whl \
  https://github.com/intentframe/intentframe/releases/download/v0.1.0/intentframe_prompt_library-0.1.0-py3-none-any.whl \
  https://github.com/intentframe/intentframe/releases/download/v0.1.0/intentframe_proxy-0.1.0-py3-none-any.whl \
  https://github.com/intentframe/intentframe/releases/download/v0.1.0/intentframe_runtime-0.1.0-py3-none-any.whl \
  https://github.com/intentframe/intentframe/releases/download/v0.1.0/intentframe_server-0.1.0-py3-none-any.whl \
  https://github.com/intentframe/intentframe/releases/download/v0.1.0/intentframe_supervisor-0.1.0-py3-none-any.whl
```

For real projects, prefer `pyproject.toml` so installs are reproducible.

## Python Version

The `v0.1.0` package set declares Python 3.14+.

```toml
requires-python = ">=3.14"
```

If your project targets an older Python version, do not depend on this package set yet.

## Moving to PyPI

Once all required IntentFrame packages are published to PyPI:

1. Remove the `[tool.uv.sources]` block.
2. Keep normal `[project.dependencies]` pins, such as `intentframe-actor==0.1.0`.
3. Run `uv sync` again.

No import changes should be required.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `uv` tries PyPI and cannot find an IntentFrame package | Missing `[tool.uv.sources]` entry for a transitive package | Start from [`example-pyproject.toml`](../scripts/github-install/example-pyproject.toml) and keep all 18 source entries |
| Wheel URL returns 404 | Tag/version mismatch or filename typo | Use the exact filenames from the GitHub release assets |
| Python version resolution fails | Project uses Python below 3.14 | Use Python 3.14+ |
| License obligations are unclear | Mixing Apache SDKs with AGPL runtime packages | Read [`licensing.md`](licensing.md) and use only the packages your project actually needs |

## Related Docs

- [`actor-sdk.md`](actor-sdk.md) — integrate an external agent through `actor.submit(...)`
- [`plugin-profiles.md`](plugin-profiles.md) — bundles, executor packs, and profile loading
- [`licensing.md`](licensing.md) — package-by-package licenses
- [`../scripts/github-install/README.md`](../scripts/github-install/README.md) — install verification and template details
- [`../scripts/github-release/README.md`](../scripts/github-release/README.md) — release asset publishing runbook
