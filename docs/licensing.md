# Licensing

IntentFrame uses a split license model across publishable workspace packages (`packages/`). Publishing to PyPI (groups, rate limits, CI vs local): [`scripts/release/README.md`](../scripts/release/README.md).

## AGPL-3.0 (runtime stack)

These packages implement or orchestrate the running substrate: pipeline services, pipeline components, the runtime meta-package, and the supervisor that spawns them.

| Distribution | Path | Role |
|--------------|------|------|
| `intentframe-executor` | `packages/executor` | Executor host |
| `intentframe-server` | `packages/intentframe-server` | Policy pipeline service |
| `intentframe-components` | `packages/intentframe-components` | AE / Guardian / onboarding |
| `intentframe-runtime` | `packages/intentframe-runtime` | Meta-package: policy-registry + executor + server |
| `intentframe-supervisor` | `packages/intentframe-supervisor` | Process manager; depends on `intentframe-runtime` |

Each includes a `LICENSE` file (copy of the repository root GNU AGPL v3 text) and `license-files = ["LICENSE"]` in `pyproject.toml`.

## Apache-2.0 (SDKs, policy models, ingress, kit, vault)

Permissive packages: author surfaces, shared libraries, ingress, first-party kit, and the policy-registry service (pulled in by `intentframe-bundle-sdk` so plugin authors stay on a permissive dependency chain).

| Distribution | Path | Notes |
|--------------|------|-------|
| `intentframe-policy-registry` | `packages/policy-registry` | Policy service; Apache so `intentframe-bundle-sdk` does not pull AGPL |
| `intentframe-core` | `packages/intentframe-core` | Neutral DTOs |
| `intentframe-bundle-sdk` | `packages/intentframe-bundle-sdk` | Bundle author SDK |
| `intentframe-executor-sdk` | `packages/intentframe-executor-sdk` | Pack author SDK |
| `intentframe-client` | `packages/intentframe-client` | Server client |
| `intentframe-actor` | `packages/intentframe-actor` | Agent SDK |
| `intentframe-executor-client` | `packages/executor-client` | Core → executor client |
| `command-shield` | `packages/command-shield` | Command analysis library |
| `intentframe-credentials` | `packages/intentframe-credentials` | Credential vault |
| `intentframe-native-kit` | `packages/intentframe-native-kit` | Reference bundles / packs |
| `intentframe-prompt-library` | `packages/intentframe-prompt-library` | Default prompts (used by AGPL `intentframe-components`) |
| `intentframe-edge` | `packages/intentframe-edge` | Network ingress |
| `intentframe-proxy` | `packages/intentframe-proxy` | UDS proxy helper |

Each Apache package includes the official Apache-2.0 `LICENSE` text and `license-files = ["LICENSE"]`.

## Product-facing code (not in `packages/`)

The root `intentframe` distribution, gateway, Jarvis, email sync (`external_data_ingestion`), demos, and related product modules remain AGPL and are not part of the permissive PyPI surface.

## Email and native kit

`intentframe-native-kit` is Apache-2.0. Email actions use the product-side EDI `EmailClient` via lazy imports; `email-sync-service` is not published to PyPI and is not declared as a package dependency.

## Dependency direction

- AGPL runtime packages may depend on Apache packages (e.g. server → core, bundle-sdk, policy-registry).
- Apache SDKs should not depend on AGPL packages except where unavoidable; `intentframe-bundle-sdk` → `intentframe-policy-registry` is intentionally Apache → Apache.
- `intentframe-supervisor` (AGPL) → `intentframe-runtime` (AGPL) keeps orchestration aligned with the running stack.
