# Package Consumer Guide

This guide is for people installing IntentFrame **packages** into another Python project.

All **18** lockstep-versioned distributions for **`0.1.1`** are on [PyPI](https://pypi.org/). Use normal `pip` / `uv` resolution — no custom index and no GitHub wheel URLs unless you need URL-pinned installs.

The **full product** (Jarvis, gateway CLI, macOS platform server, demos) is **not** on PyPI. Clone the repo and follow [`quickstart.md`](quickstart.md) for that path.

Release tag (GitHub assets mirror): [`v0.1.1`](https://github.com/intentframe/intentframe/releases/tag/v0.1.1)

## Distribution channels

| Channel | Status | Use when |
|---------|--------|----------|
| **PyPI** | **Primary** — all 18 packages @ `0.1.1` | Normal third-party projects (recommended) |
| GitHub release wheels | Available for `v0.1.1` | Air-gapped URL pins, reproducible wheel hashes, or PyPI unavailable |
| Source clone | Available | Contributing to IntentFrame or running the full product workspace |

## Install from PyPI

**Python 3.14+** is required (`requires-python = ">=3.14"` on every package).

### Quick ad-hoc install

```bash
pip install intentframe-actor==0.1.1 intentframe-bundle-sdk==0.1.1 intentframe-executor-sdk==0.1.1
```

Transitive IntentFrame dependencies resolve from PyPI automatically.

### `uv` project (recommended)

Copy [`../scripts/github-install/example-pyproject-pypi.toml`](../scripts/github-install/example-pyproject-pypi.toml) into your repo as `pyproject.toml`, edit `project.name` / `project.version`, and keep only the IntentFrame packages you import directly:

```toml
[project]
name = "my-intentframe-agent"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = [
  "intentframe-actor==0.1.1",
  "intentframe-bundle-sdk==0.1.1",
  "intentframe-executor-sdk==0.1.1",
]
```

```bash
uv sync
```

No `[tool.uv.sources]` block is needed when installing from PyPI.

## Pick packages

For a normal third-party agent or plugin, start with the author-facing SDKs:

| Package | PyPI | Use it when |
|---------|------|-------------|
| `intentframe-actor` | [pypi](https://pypi.org/project/intentframe-actor/) | Your agent submits intents to an IntentFrame runtime |
| `intentframe-bundle-sdk` | [pypi](https://pypi.org/project/intentframe-bundle-sdk/) | You author action bundles for the policy pipeline |
| `intentframe-executor-sdk` | [pypi](https://pypi.org/project/intentframe-executor-sdk/) | You author executor packs/adapters |
| `intentframe-client` | [pypi](https://pypi.org/project/intentframe-client/) | You call the IntentFrame server API directly |
| `intentframe-core` | [pypi](https://pypi.org/project/intentframe-core/) | You need shared DTOs/contracts |
| `command-shield` | [pypi](https://pypi.org/project/command-shield/) | You need shell command capability analysis |
| `intentframe-credentials` | [pypi](https://pypi.org/project/intentframe-credentials/) | You integrate with the credential vault |
| `intentframe-native-kit` | [pypi](https://pypi.org/project/intentframe-native-kit/) | First-party native bundles, executor packs, profiles |
| `intentframe-runtime` | [pypi](https://pypi.org/project/intentframe-runtime/) | Meta-package: policy-registry + executor + server |
| `intentframe-supervisor` | [pypi](https://pypi.org/project/intentframe-supervisor/) | Boot the runtime stack (`intentframe` CLI) |
| `intentframe-edge` | [pypi](https://pypi.org/project/intentframe-edge/) | HTTP/TLS ingress to the runtime |
| `intentframe-proxy` | [pypi](https://pypi.org/project/intentframe-proxy/) | UDS proxy helper (edge/gateway) |
| `intentframe-server` | [pypi](https://pypi.org/project/intentframe-server/) | Policy pipeline service (substrate) |
| `intentframe-executor` | [pypi](https://pypi.org/project/intentframe-executor/) | Executor host (substrate) |
| `intentframe-components` | [pypi](https://pypi.org/project/intentframe-components/) | AE / Guardian / onboarding (substrate) |
| `intentframe-policy-registry` | [pypi](https://pypi.org/project/intentframe-policy-registry/) | Policy service |
| `intentframe-prompt-library` | [pypi](https://pypi.org/project/intentframe-prompt-library/) | Default AE/Guardian prompts |
| `intentframe-executor-client` | [pypi](https://pypi.org/project/intentframe-executor-client/) | Core → executor client |

See [`licensing.md`](licensing.md) before embedding runtime packages. SDKs and neutral libraries are **Apache-2.0**; the running substrate stack is **AGPL-3.0**.

## Fallback: GitHub release wheels

If you must pin exact wheel URLs (or PyPI is unreachable), use [`../scripts/github-install/example-pyproject.toml`](../scripts/github-install/example-pyproject.toml) with all 18 `[tool.uv.sources]` entries. See [`../scripts/github-install/README.md`](../scripts/github-install/README.md).

Verify a release tag installs cleanly:

```bash
./scripts/github-install/verify_release_install.sh --tag v0.1.1
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `No matching distribution found` for an IntentFrame package | Typo in name, wrong version, or Python &lt; 3.14 | Use `==0.1.1` and Python 3.14+ |
| Transitive IntentFrame dep missing (GitHub wheel path only) | Incomplete `[tool.uv.sources]` | Use [`example-pyproject.toml`](../scripts/github-install/example-pyproject.toml) with all 18 sources, or switch to PyPI |
| Wheel URL returns 404 | Tag/version mismatch | Match filenames on the [GitHub release](https://github.com/intentframe/intentframe/releases/tag/v0.1.1) |
| License obligations unclear | Mixing Apache SDKs with AGPL runtime | Read [`licensing.md`](licensing.md); depend only on what you need |
| Expected Jarvis / gateway on PyPI | Product code is not published | Clone repo → [`quickstart.md`](quickstart.md) |

## Related docs

- [`actor-sdk.md`](actor-sdk.md) — integrate an external agent through `actor.submit(...)`
- [`plugin-profiles.md`](plugin-profiles.md) — bundles, executor packs, and profile loading
- [`licensing.md`](licensing.md) — package-by-package licenses
- [`../scripts/release/README.md`](../scripts/release/README.md) — maintainer publishing
- [`../scripts/github-install/README.md`](../scripts/github-install/README.md) — GitHub wheel fallback and verifier
