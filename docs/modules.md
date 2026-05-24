# Workspace Modules — A Map

> Every tracked module in the IntentFrame repository, what it is, why it exists, and where to read more about it.

This is the answer to "does the docs folder cover everything?". Use it as a directory: each row links to the module's source, its own README (if any), and the public docs that explain it.

If you're new, read [README.md](README.md) and [architecture.md](architecture.md) first — this page is for finding things, not for understanding the system from scratch.

---

## Quick orientation

The repo is divided into roughly six layers of concern:

| Layer | Purpose | Modules |
|---|---|---|
| **Shared types** | Data model used by everyone | `intentframe_core`, `action_registry` |
| **Configuration plane** | What the user has authorized | `policy_registry`, `resource_registry` |
| **Pipeline (decision)** | Validates intents | `intentframe_components` (analysis, guardian, onboarding), `intentframe_server` |
| **Execution (action)** | Touches the world | `executor`, `executor_client`, `command_shield` |
| **Platform services** | OS / data-source bridges | `intentframe_credentials`, `external_data_ingestion`, `macos-appkit-server` |
| **Frontends and orchestration** | The user-facing layer | `intentframe_gateway`, `supervisor`, `intentframe_cli`, `intentframe_dashboard`, `intentframe_actor`, `jarvis_pa`, `jarvis_telegram`, `external_agents` |

The rest of this doc walks each module in turn.

---

## Shared types

### `intentframe_core/`

| | |
|---|---|
| **What** | Shared types and enums (`ActionType`, `Decision`, `RiskLevel`, `IntentFrame`, `RuntimeContext`, …). Zero dependencies on the rest of IntentFrame. |
| **Why** | Both the server and the Actor SDK import from here. Without a shared types package, the server-side and agent-side would drift apart, and a common dataclass change would require edits in two unrelated trees. |
| **Where** | `intentframe_core/` |
| **Process** | None — it's an importable Python package, not a service. |
| **Public docs** | [architecture.md](architecture.md) (uses these types throughout) |
| **Module README** | None — purpose is clear from the `__init__.py` docstring. |

### `action_registry/`

| | |
|---|---|
| **What** | Static catalog of every action that *can* exist (`READ_FILE`, `RUN_COMMAND`, `PAY_INVOICE`, …) and its category (FILE, TERMINAL, EMAIL, …). |
| **Why** | The vocabulary the policy registry validates against and the pipeline dispatches on. Splitting it from `policy_registry` and from the pipeline lets both depend on a small, dependency-free taxonomy. |
| **Where** | `action_registry/` |
| **Process** | None — in-process Python module. |
| **Public docs** | [registries.md § Action registry](registries.md#the-action-registry) |
| **Module README** | None — purpose is clear from the `__init__.py` docstring. |

---

## Configuration plane

### `policy_registry/`

| | |
|---|---|
| **What** | The user's rules: which actions are allowed, with what constraints, with what intent limits. Plus a system-level blocked-pattern floor. |
| **Why** | Separates configuration from decision-making. The Guardian reads policies; it doesn't store them. This is also what closes the "compromised agent talks the Guardian into a policy exception" attack — there is no negotiation surface. |
| **Where** | `policy_registry/` |
| **Process** | `policy-registry` (uvicorn) on `~/.intentframe/run/policy-registry.sock`, started by the supervisor. |
| **Public docs** | [registries.md § Policy registry](registries.md#the-policy-registry) |
| **Module README** | None — design is described in `__init__.py` and `registry.py` docstrings. |

### `resource_registry/`

| | |
|---|---|
| **What** | Workspaces and resource mounts. Serves separate read views to the agent (virtual paths only) and the executor (real paths). |
| **Why** | Implements the virtual filesystem. The agent can never name a path outside its mounts; path traversal becomes structurally impossible. |
| **Where** | `resource_registry/` |
| **Process** | `resource-registry` (uvicorn) on `~/.intentframe/run/resource-registry.sock`, started by the supervisor. |
| **Public docs** | [registries.md § Resource registry](registries.md#the-resource-registry); [vfs-vs-host-tools.md](vfs-vs-host-tools.md) |
| **Module README** | None. |

---

## Plugin platform (bundles)

### `intentframe_bundle_sdk/`

| | |
|---|---|
| **What** | Bundle lifecycle contract: `ActionBundle` / `DomainBundle` hooks, `DeterministicRunner` (fixed gate order), registry + domain routes, `ensure_loaded(packages)` loader, opaque `ActionPermission` / `BundleAIContext` types. |
| **Why** | Substrate orchestrates; plugins own action/domain logic. The SDK is action- and domain-agnostic — no family-specific constraint field names or industry vocabulary. |
| **Where** | `intentframe_bundle_sdk/` |
| **Process** | None — imported by `intentframe_components`, `intentframe_native_bundles`, and tests. |
| **Public docs** | [dev/action-family-wiring.md](dev/action-family-wiring.md) |
| **Module README** | Module docstrings in `loader.py`, `action.py`, `runner.py`. |

### `intentframe_native_bundles/`

| | |
|---|---|
| **What** | First-party plugins: `actions/<family>/` (action ids + constraints + enforcement), `domains/<domain>/` (domain overlays), `domain_routes.py` (routing manifest), `register_bundles(registry)` entry point. |
| **Why** | All family-specific logic lives here — not in `intentframe_components` or `policy_registry`. Domain bundles do not import action bundles; routing is separate metadata. |
| **Where** | `intentframe_native_bundles/` |
| **Process** | Loaded at runtime via `ensure_loaded(["intentframe_native_bundles"])`. |
| **Public docs** | [dev/action-family-wiring.md](dev/action-family-wiring.md) |
| **Module README** | None — see `register_bundles` in `__init__.py`. |

---

## Pipeline (decision)

### `intentframe_components/`

| | |
|---|---|
| **What** | The pipeline building blocks: `analysis/` (Analysis Engine), `guardian/` (deterministic + AI Guardian), `onboarding/` (agent handshake), `executor/` (executor base ABC). Action-family path/vocabulary rules live in `intentframe_native_bundles/`. |
| **Why** | Each layer of the pipeline gets its own sub-package with a base class plus a default AI implementation, so you can swap the AI implementation without touching pipeline assembly. |
| **Where** | `intentframe_components/` |
| **Process** | None directly — used by `intentframe_server`. The `intentframe-core` process imports from here. |
| **Public docs** | [architecture.md](architecture.md) (the pipeline section); [why_llm_guarding_llm_deep_dive.md](why_llm_guarding_llm_deep_dive.md) |
| **Module README** | None. |

### `intentframe_server/`

| | |
|---|---|
| **What** | The pipeline runtime — `pipeline.py` (`IntentFrameRuntime`), `server.py` (FastAPI app), `client.py` (HTTP/UDS client used by the Actor SDK and Dashboard), `enrichers/`, `dry_run_executor.py`, `file_intel.py`. |
| **Why** | The pipeline needs a service surface so the Actor SDK can submit intents from a different process. This is that service. |
| **Where** | `intentframe_server/` |
| **Process** | `intentframe-core` (uvicorn) on `~/.intentframe/run/intentframe.sock`, started by the supervisor. This is the process that calls OpenAI for AE + Guardian. |
| **Public docs** | [architecture.md](architecture.md), [processes.md § intentframe-core](processes.md) |
| **Module README** | None. |

---

## Execution (action)

### `executor/`

| | |
|---|---|
| **What** | The only component that touches the real world. Holds adapter credentials. Applies the kernel sandbox for `RUN_COMMAND`. Writes the audit log. |
| **Why** | Concentrating every IO and every credential in one process is what makes credential isolation, audit, and rollback structurally enforceable. The executor is "the engine, not the workbench." |
| **Where** | `executor/` |
| **Process** | `executor` (uvicorn) on `~/.intentframe/run/executor.sock`, started by the supervisor. |
| **Public docs** | [executor.md](executor.md), [executor/architecture.md](executor/architecture.md), [executor/security-model.md](executor/security-model.md), [executor/why-foundation.md](executor/why-foundation.md), [executor/standalone-product.md](executor/standalone-product.md) |
| **Module README** | `executor/README.md` (sub-references: `executor/sandbox.md`, `executor/plan.md`) |

### `executor_client/`

| | |
|---|---|
| **What** | Two implementations of the `Executor` ABC — `ExecutorHTTPClient` (calls the executor service over UDS) and `ExecutorBridge` (in-process, for tests / demo). Plus wire-protocol models. |
| **Why** | The pipeline talks to the executor through the same interface in both production (HTTP) and tests (in-process). Letting tests skip the HTTP layer keeps test runtime fast without diverging from production code paths. |
| **Where** | `executor_client/` |
| **Process** | None directly — imported by the pipeline (`intentframe-core`). |
| **Public docs** | Implicit in [architecture.md](architecture.md) and [executor.md](executor.md). |
| **Module README** | None. |

### `command_shield/`

| | |
|---|---|
| **What** | Deterministic inspection of shell commands and raw code bodies. Returns a structured report: catastrophic flags, deterministic capabilities, language detection, referenced files, static-analysis findings. |
| **Why** | The deterministic gate before `RUN_COMMAND` reaches the AE. It catches the catastrophic shapes that should never need an LLM (`rm -rf /`, fork bombs, …) and tags every command with the capabilities it would exercise (`capability:network_egress:download`, `capability:filesystem_write`, …) so the policy registry can apply allow/deny decisions deterministically. |
| **Where** | `command_shield/` |
| **Process** | None — in-process Python module, called by the pipeline. |
| **Public docs** | [executor/security-model.md](executor/security-model.md), [terminal_use/current_deterministic_gates_mapping.md](terminal_use/current_deterministic_gates_mapping.md), [why-not-injection-shield.md](why-not-injection-shield.md) |
| **Module README** | `command_shield/README.md` |

---

## Platform services

### `intentframe_credentials/`

| | |
|---|---|
| **What** | The credential vault — OS-keyring-backed secret store, exposed via FastAPI over UDS. Plus client libraries (`VaultClient`, `VaultClientSync`), backends (`keyring`, `service`, `env`), and a structlog redaction processor. |
| **Why** | One process holds every secret. Other processes ask for what they need; values never appear in logs, env vars (except where explicitly designed to), or on disk. |
| **Where** | `intentframe_credentials/` |
| **Process** | `credential-vault` (uvicorn) on `~/.intentframe/run/credential-vault.sock`, started by the gateway in Step 1 (before everything else). |
| **Public docs** | [credentials-vault.md](credentials-vault.md) |
| **Module README** | `intentframe_credentials/README.md` |

### `external_data_ingestion/` (EDI)

| | |
|---|---|
| **What** | IMAP IDLE + SMTP daemon with a local SQLite mirror (WAL + FTS5) and a `EmailClient` consumed by the executor's MailAdapter and Jarvis. |
| **Why** | The only place in IntentFrame that talks IMAP/SMTP. Centralizes credential isolation, connection budget, and the local read store; lets the executor and Jarvis share one cache and one connection pool. |
| **Where** | `external_data_ingestion/` |
| **Process** | `email-sync-daemon`, started by the gateway in Step 7. |
| **Public docs** | [email-sync.md](email-sync.md) |
| **Module README** | `external_data_ingestion/README.md` (deep design in `external_data_ingestion/external_data_ingestion/concepts/imap_connection_budget.md`) |

### `macos-appkit-server/`

| | |
|---|---|
| **What** | A native Swift `.app` bundle that exposes Apple frameworks (EventKit, Contacts, UserNotifications, AppleScript bridges to Notes / Mail / Messages, DisplayServices) over a Unix socket. |
| **Why** | The relevant frameworks are Swift / Objective-C only; Python has no usable bindings. macOS TCC permissions are pinned to a stable code-signed binary, so a Swift .app bundle is the right place for them. |
| **Where** | `macos-appkit-server/` |
| **Process** | `macos-appkit-server` (Swift / Vapor) on `~/.intentframe/run/platform.sock`, started by the gateway in Step 5. |
| **Public docs** | [macos-platform-server.md](macos-platform-server.md) |
| **Module README** | `macos-appkit-server/README.md` |

---

## Frontends and orchestration

### `intentframe_gateway/`

| | |
|---|---|
| **What** | The top-level orchestrator. A FastAPI service on a single Unix socket that starts the entire IntentFrame stack, manages its lifecycle, aggregates health, and exposes a unified API to any frontend. |
| **Why** | Frontends shouldn't have to know which sockets exist or how to start each subsystem. They talk to one socket; the gateway hides everything else. |
| **Where** | `intentframe_gateway/` |
| **Process** | `intentframe-gateway-cli` (uvicorn) on `~/.intentframe/run/gateway.sock`. The user-facing entry point — the one process the user actually starts. |
| **Public docs** | [processes.md § Process tree](processes.md), [architecture.md § Runtime model and privacy](architecture.md#runtime-model-and-privacy) |
| **Module README** | `intentframe_gateway/README.md` |

### `supervisor/`

| | |
|---|---|
| **What** | A small process manager that spawns and monitors the four core services (`policy-registry`, `resource-registry`, `executor`, `intentframe-core`) in dependency order, waits for health, and shuts them down gracefully. |
| **Why** | Splitting startup orchestration out of the gateway keeps the gateway focused on the user-facing API. The supervisor also injects `runtime_env` credentials into spawned children, so the children never call the vault themselves. |
| **Where** | `supervisor/` |
| **Process** | `supervisor`, started by the gateway in Step 6. |
| **Public docs** | [processes.md § supervisor](processes.md), [credentials-vault.md § Lifecycle](credentials-vault.md#lifecycle) |
| **Module README** | None. |

### `intentframe_cli/`

| | |
|---|---|
| **What** | Interactive terminal frontend. Talks exclusively to `gateway.sock`. If the gateway isn't running, starts it as a background process. |
| **Why** | The reference frontend. Demonstrates that any frontend (CLI, native, web, Telegram) can be built against just the gateway socket without depending on internal services. |
| **Where** | `intentframe_cli/` |
| **Process** | `intentframe-gateway-cli` (the same binary that runs as the gateway — it self-bootstraps). |
| **Public docs** | [quickstart.md](quickstart.md) |
| **Module README** | `intentframe_cli/README.md` |

### `intentframe_dashboard/`

| | |
|---|---|
| **What** | Programmatic and config-driven control plane. Scans agent packages, registers users, configures workspaces, launches agent programs as subprocesses, retrieves audit trails. |
| **Why** | The user-facing administration surface. Used by the demo runner and by external operators who want to script multi-agent setups. Never imports or executes agent code directly — it spawns subprocesses, isolating the dashboard from the agent. |
| **Where** | `intentframe_dashboard/` |
| **Process** | None as a daemon — invoked programmatically (`with IntentFrameDashboard(...) as d:`) or via `run_config(...)`. The demo (`demo/demo_dashboard.py`) is the canonical caller. |
| **Public docs** | Implicit in [quickstart.md](quickstart.md); usage in `demo/demo_dashboard.py`. |
| **Module README** | None. |

### `intentframe_actor/`

| | |
|---|---|
| **What** | The Actor SDK. The single import an agent developer uses (`from intentframe_actor import Actor`) to handshake with IntentFrame and submit actions. |
| **Why** | The boundary between agent code and the IntentFrame pipeline. By making this the *only* way an agent can do IO, every AI-decided action is structurally forced through the pipeline. Agents that try to do their own IO are ill-formed by construction. |
| **Where** | `intentframe_actor/` |
| **Process** | None directly — runs in the agent's process. |
| **Public docs** | [architecture.md § Agent → Actor](architecture.md), `external_agents/invoice_bot/agent.py` (reference usage) |
| **Module README** | None — purpose is clear from the `__init__.py` docstring; `actor.py` is small and self-contained. |

### `jarvis_pa/`

| | |
|---|---|
| **What** | A standalone macOS personal assistant — terminal REPL, LLM agent, persistent memory, proactive scheduler, sub-agent delegation. Uses the Actor SDK to do IO. |
| **Why** | The reference real-world agent. Demonstrates that a substantial agent app can be built on top of IntentFrame without coupling to its internals — Jarvis is "a normal Python application that depends on the Actor SDK," not "an IntentFrame component." |
| **Where** | `jarvis_pa/` |
| **Process** | `jarvis-pa` and optionally `jarvis-telegram-bot`, started by the gateway in Steps 8–9. |
| **Public docs** | [processes.md § jarvis](processes.md); none yet dedicated. |
| **Module README** | `jarvis_pa/README.md` |

### `jarvis_telegram/`

| | |
|---|---|
| **What** | Telegram bot bridge to Jarvis. Authenticates user IDs, forwards messages to Jarvis, streams replies back. |
| **Why** | A second frontend on top of Jarvis (in addition to the terminal REPL), proving Jarvis's UI is decoupled from its core. Useful for remote access on the go. |
| **Where** | `jarvis_telegram/` |
| **Process** | `jarvis-telegram-bot`, started by the gateway in Step 9. |
| **Public docs** | None yet dedicated. |
| **Module README** | `jarvis_telegram/README.md` and `jarvis_telegram/ARCHITECTURE.md` |

### `external_agents/`

| | |
|---|---|
| **What** | Third-party agents that target IntentFrame via the Actor SDK. Currently contains the reference `invoice_bot/`. |
| **Why** | This is what an external integration looks like: a Python package with a `manifest.yaml` and an `agent.py` that imports `intentframe_actor.Actor`. The dashboard discovers agents from this directory. |
| **Where** | `external_agents/` |
| **Process** | One process per registered agent, spawned by the dashboard. |
| **Public docs** | Implicit in [architecture.md](architecture.md) and [quickstart.md](quickstart.md). |
| **Module README** | None — `external_agents/invoice_bot/manifest.yaml` plus `agent.py` is the canonical example. |

---

## Supporting directories (not modules)

### `demo/`

| | |
|---|---|
| **What** | Runnable end-to-end demos: `demo_dashboard.py` (the headline demo), `demo_evaluation.md`, `demo_run_logs.txt`, plus configuration and test data. |
| **Why** | The primary way new users see what IntentFrame does. Also the integration smoke test for the whole stack. |
| **Where** | `demo/` |
| **Public docs** | [quickstart.md](quickstart.md), [evidence.md](evidence.md), [root_demo/PROOF.md](root_demo/PROOF.md) |

### `tests/`

| | |
|---|---|
| **What** | Top-level integration tests. Per-module unit tests live alongside their modules (e.g. `policy_registry/tests/`). |
| **Why** | Cross-cutting tests that exercise multiple modules — guardian + executor + policy registry together, audit pipeline end-to-end, etc. |
| **Where** | `tests/` |
| **Public docs** | [evidence.md](evidence.md) summarizes what's verified. |

### `scripts/` and `git-hooks/`

| | |
|---|---|
| **What** | Developer-facing scripts: install hooks, run tests in containers, etc. |
| **Why** | Standard repo hygiene — keep scripts in one place, hooks installable. |
| **Public docs** | `scripts/README.md` |

### `roadmap/` and `TODO/`

| | |
|---|---|
| **What** | Planning notes. `roadmap/` for forward direction; `TODO/` for known followups (e.g. `licensing-todo.md`). |
| **Public docs** | None — these are planning artifacts, not reference docs. |

---

## Coverage matrix

A direct answer to "does docs/ cover all tracked workspace modules?":

| Module | Has module README | Has dedicated public doc | Covered in docs |
|---|---|---|---|
| `intentframe_core` | — | — | ✅ via [architecture.md](architecture.md) |
| `action_registry` | — | — | ✅ via [registries.md](registries.md) |
| `policy_registry` | — | — | ✅ via [registries.md](registries.md) |
| `resource_registry` | — | — | ✅ via [registries.md](registries.md), [vfs-vs-host-tools.md](vfs-vs-host-tools.md) |
| `intentframe_components` | — | — | ✅ via [architecture.md](architecture.md) |
| `intentframe_server` | — | — | ✅ via [architecture.md](architecture.md), [processes.md](processes.md) |
| `executor` | ✅ (sub-folder of refs) | ✅ [executor.md](executor.md) | ✅ |
| `executor_client` | — | — | ✅ implicit in [architecture.md](architecture.md) |
| `command_shield` | ✅ | — | ✅ via [executor/security-model.md](executor/security-model.md), [terminal_use/](terminal_use/) |
| `intentframe_credentials` | ✅ | ✅ [credentials-vault.md](credentials-vault.md) | ✅ |
| `external_data_ingestion` | ✅ | ✅ [email-sync.md](email-sync.md) | ✅ |
| `macos-appkit-server` | ✅ | ✅ [macos-platform-server.md](macos-platform-server.md) | ✅ |
| `intentframe_gateway` | ✅ | — | ✅ via [processes.md](processes.md) |
| `supervisor` | — | — | ✅ via [processes.md](processes.md), [credentials-vault.md](credentials-vault.md) |
| `intentframe_cli` | ✅ | — | ✅ via [quickstart.md](quickstart.md) |
| `intentframe_dashboard` | — | — | ✅ via [quickstart.md](quickstart.md) and demo |
| `intentframe_actor` | — | ✅ [actor-sdk.md](actor-sdk.md) | ✅ |
| `jarvis_pa` | ✅ | ✅ [jarvis.md](jarvis.md) | ✅ |
| `jarvis_telegram` | ✅ | ✅ [jarvis-telegram.md](jarvis-telegram.md) | ✅ |
| `external_agents` | — | ✅ via [actor-sdk.md](actor-sdk.md) | ✅ via [architecture.md](architecture.md), `invoice_bot` example |

---

## Gaps and intentional non-coverage

These are deliberate choices, documented so they don't look accidental:

- **No public doc for `intentframe_dashboard`.** The dashboard is the platform's admin API; the demo shows how it's used. A dedicated doc would be appropriate when the dashboard gets a UI beyond the current programmatic / config-file interface.
- **No public doc for `intentframe_server` / `intentframe_components`.** They're the implementation of the pipeline that's already documented at the right level in [architecture.md](architecture.md). Splitting them out would duplicate without adding clarity.
- **No public doc for `executor_client`.** Pure plumbing — the public-facing details are the executor's, not the client's.

---

## Related documents

- [README.md](README.md) — Top-level docs index
- [architecture.md](architecture.md) — Logical pipeline these modules implement
- [processes.md](processes.md) — Physical process tree showing which modules become which OS processes
- [privacy.md](privacy.md) — Data layout for the modules that store data
