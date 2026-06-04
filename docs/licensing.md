# Licensing

IntentFrame uses a split license model across publishable workspace packages.

## AGPL-3.0 (substrate core)

These packages implement the running policy pipeline and three-process substrate:

| Distribution | Path |
|--------------|------|
| `intentframe-policy-registry` | `packages/policy-registry` |
| `intentframe-executor` | `packages/executor` |
| `intentframe-server` | `packages/intentframe-server` |
| `intentframe-components` | `packages/intentframe-components` |
| `intentframe-runtime` | `packages/intentframe-runtime` |

Each includes a `LICENSE` file (copy of the repository root GNU AGPL v3 text) and declares `license-files = ["LICENSE"]` in `pyproject.toml` so wheels and sdists ship the full license.

## Apache-2.0 (SDKs, ingress, kit, vault)

All other packages under `packages/` are distributed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0). Each includes a `LICENSE` file copied from the official Apache text.

Examples: `intentframe-core`, `intentframe-bundle-sdk`, `intentframe-executor-sdk`, `intentframe-client`, `intentframe-actor`, `intentframe-supervisor`, `intentframe-native-kit`, `intentframe-credentials`, `intentframe-edge`, `intentframe-proxy`, `command-shield`, and related client/helper packages.

## Product-facing code (not in `packages/`)

The root `intentframe` distribution, gateway, Jarvis, email sync (`external_data_ingestion`), demos, and related product modules remain AGPL and are not part of the permissive PyPI surface.

## Email and native kit

`intentframe-native-kit` is Apache-2.0. Email actions use the product-side EDI `EmailClient` via lazy imports; `email-sync-service` is not published to PyPI and is not declared as a package dependency.
