# The Registries

> The configuration plane of IntentFrame — what actions can exist, what the user has authorized, and what resources they expose to the agent.

IntentFrame separates **configuration** (what's allowed, what exists) from **decision-making** (whether a specific action should run). Configuration lives in three small registries; decisions happen in the Guardian. This separation is what lets a non-AI rule change the system's behavior — you edit a registry, and the Guardian's next decision reflects that edit, deterministically.

This doc covers all three registries together because they share the same shape (a typed data store with separate read views per consumer) and they're commonly read together at decision time.

---

## The three registries at a glance

| Registry | Source | What it stores | Who writes it | Who reads it |
|---|---|---|---|---|
| **Action registry** | `intentframe_native_kit/action_registry/` | The universal *taxonomy* — every action that *can* exist (`READ_FILE`, `RUN_COMMAND`, `PAY_INVOICE`, …), its category, its metadata | IntentFrame developers (it's a static catalog) | Policy registry (to validate user policies); pipeline (to dispatch to adapters) |
| **Policy registry** | `policy_registry/` | The user's *rules* — which actions are allowed, opaque constraint dicts, intent limits | The user (via dashboard / CLI / SDK at registration time) | Guardian (every validation), Analysis Engine (to adjust depth) |
| **Resource registry** | `intentframe_native_kit/resource_registry/` | The user's *workspaces* and resource mounts — virtual paths, real paths, writability, file filters, plus the registered adapter inventory | The user (when defining workspaces) and platform (when adapters register) | Agent client (sees `ClientView` — virtual paths only); executor (sees `ExecutorView` — full mount table with real paths) |

Capability-tagging (the tag taxonomy used inside `TerminalConstraints`) is owned by `command_shield`, not by a registry of its own.

```
┌──────────────────────────────────────────────────────────────────┐
│                    USER CONFIGURATION                            │
│                                                                  │
│  "I authorize this agent to do X with constraint Y on resource Z"│
└────────┬─────────────────────────┬──────────────────────────┬────┘
         │                         │                          │
         ▼                         ▼                          ▼
┌──────────────────┐   ┌────────────────────┐   ┌────────────────────┐
│ ACTION REGISTRY  │   │  POLICY REGISTRY   │   │ RESOURCE REGISTRY  │
│                  │   │                    │   │                    │
│ Static taxonomy  │   │ User policies +    │   │ Workspaces + VFS   │
│ of every action  │   │ intent limits      │   │ mounts + adapter   │
│ that CAN exist   │   │ (opaque constraint │   │ inventory          │
│                  │   │  dicts per action) │   │                    │
│ "READ_FILE,      │   │ "READ_FILE only    │   │ "/invoices/ →      │
│  RUN_COMMAND,    │   │  in /invoices/,    │   │  /Users/me/inbox/  │
│  PAY_INVOICE,    │   │  PAY_INVOICE max   │   │  (read-only)"      │
│  ..."            │   │  $5000, ..."       │   │                    │
└────────┬─────────┘   └─────────┬──────────┘   └─────────┬──────────┘
         │                       │                        │
         │   (taxonomy            │   (rules)              │   (mounts +
         │    used to validate    │                        │    adapter
         │    user policies)      │                        │    inventory)
         │                       │                        │
         ▼                       ▼                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   THE GUARDIAN + EXECUTOR                            │
│                                                                      │
│  Guardian reads policy_registry to decide ALLOW / BLOCK              │
│  Executor reads resource_registry executor_view to resolve real paths│
│  Pipeline uses intentframe_native_kit.action_registry to dispatch to the right adapter      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Why registries are separate from the Guardian

The "Why isn't this a single big config?" question. Three reasons:

**1. Pipeline components can't act on the world.** The Guardian *reads* policies but doesn't store them. The executor *reads* resource mounts but doesn't define them. This is the No-Self-IO principle: pipeline components are validators, not stores. Storage is its own service. The short version of the argument: policy stores are *internal operational state*, not *external resources the pipeline acts on* — Guardian reading the policy store is the validator consulting its own rulebook, not an agent acting on the user's world.

**2. Different views for different consumers.** The agent and the executor see different things. The agent sees virtual paths; the executor sees real paths. The agent sees its allowed action types; the Guardian sees the full constraint set. The registries enforce that view split structurally — the agent literally cannot ask the registry for the executor's view.

**3. Configuration is its own deployment concern.** In the current macOS deployment, the registries run in-process inside their respective uvicorn services, with a SQLite store. In a future cloud deployment, the same interface could be backed by a hosted policy database with a UI for org-wide policy administration. The Guardian doesn't change.

---

## The action registry

`intentframe_native_kit/action_registry/` defines the universal action vocabulary (import: `intentframe_native_kit.action_registry`). It's a static, in-process catalog — not a service.

### What's in it

```
ActionCategory ─── enum (FILE, HOST_FILE, TERMINAL, EMAIL, CALENDAR, …)
ActionType ─────── str enum (READ_FILE, WRITE_FILE, RUN_COMMAND, PAY_INVOICE, …)
ActionMeta ─────── per-action metadata (category, domain, description)
DomainType ─────── enum (FINANCE, DELETION)
ACTION_DOMAINS ─── map ActionType → DomainType (critical-domain tag)
ActionCatalog ──── lookup: action id string → ActionMeta
domains/ ───────── domain intent schemas (FinancialIntentData, DeletionIntentData, DOMAIN_SCHEMAS)
```

`IntentFrame.action` in core is a plain `str`. `ActionType` members are drop-in strings (`ActionType(str, Enum)`). Platform-only catalog actions (e.g. `RUN_SHORTCUT`, `WATCH_FILESYSTEM`) may exist in `ActionCatalog` without being enum members — they still flow as strings through the pipeline.

Each `ActionType` belongs to exactly one `ActionCategory`. Categories determine which constraint schema applies when a user writes a policy. For example:

- `READ_FILE`, `WRITE_FILE`, `LIST_DIRECTORY` → `ActionCategory.FILE` → `FileConstraints` (allowed paths, file filters)
- `SEND_EMAIL`, `READ_EMAIL` → `ActionCategory.EMAIL` → `EmailConstraints` (in `intentframe_native_kit/intentframe_native_bundles/actions/email/constraints.py`)
- `RUN_COMMAND` → `ActionCategory.TERMINAL` → `TerminalConstraints` (in `intentframe_native_kit/intentframe_native_bundles/actions/terminal/constraints.py`)
- `PAY_INVOICE` → `ActionCategory.API` + `DomainType.FINANCE` → finance hard gate

### Why it's a separate module

So bundles, executor packs, policy YAML, and optional agent-author tooling share one vocabulary without coupling that vocabulary into `intentframe_core`. **`intentframe_native_kit.action_registry` depends on `intentframe_core`** (for `DomainSchema`); core does not import the registry. The deterministic runner routes domains via `domain_routes.py` and the bundle SDK registry — not via `ACTION_DOMAINS` at runtime.

### Where to look

- `intentframe_native_kit/action_registry/types.py` — enums, `ACTION_CATEGORIES`, `ACTION_DOMAINS`
- `intentframe_native_kit/action_registry/catalog.py` — `ActionCatalog` registration
- `intentframe_native_kit/action_registry/domains/` — `DOMAIN_SCHEMAS`, `FinancialIntentData`, `DeletionIntentData`
- `intentframe_native_kit/action_registry/platforms/<os>/actions.py` — platform-only catalog entries

---

## The policy registry

`policy_registry/` is what holds the user's actual rules.

### Process and storage

Runs as a uvicorn FastAPI service on `~/.intentframe/run/policy-registry.sock`. Source: `policy_registry/server.py`. Backed by local SQLite. Started by the supervisor as one of its four core services.

### What it stores

```
UserPolicy
├── user_id
├── allowed_actions: dict[str → ActionPermission]   # keys are action id strings (e.g. "READ_FILE")
│        ActionPermission:
│          • safe: bool                ← critical for fast-path routing
│          • constraints: dict | None  ← opaque JSON; schema owned by action bundles
│          • description
│
├── intent_limits: list[SemanticIntentLimit]
│        SemanticIntentLimit:
│          • limit_id, domain, raw text, optional threshold
│
└── (per-policy metadata)
```

The registry stores constraint dicts **opaquely**. It does not validate shapes, resolve dynamic sources (e.g. `contacts_all` → email addresses), or merge system safety floors. Those responsibilities live in the **action bundles** that own each constraint schema (see `intentframe_native_kit/intentframe_native_bundles/actions/*/constraints.py` and `intentframe_bundle_sdk/runner.py`).

### Two important properties

**Policies are declared at registration time.** The user (or developer) declares the policy when they install or onboard an agent. The agent itself cannot influence what's in the policy registry at runtime. This is what closes the "compromised agent talks the Guardian into a policy exception" attack — there's nothing for the agent to talk *to*. The policy is data, not a conversation.

**Rules are deterministic.** The policy registry stores facts (action allowlists, path constraints, intent limits, deny patterns). The Guardian's deterministic gate (`DeterministicGuardian`) consults these facts and produces ALLOW / BLOCK / UNDECIDED without an LLM. Most safe and most catastrophic intents are decided here.

### What `safe: true` does

`ActionPermission.safe` is a routing decision the user makes at registration time. If an action is marked `safe: true` AND it's in the developer-curated `_PRE_AE_SAFE_READS` set (passive reads like `LIST_DIRECTORY`), the pipeline takes the fast-path and never calls an LLM. Mutating actions (`PAY_INVOICE`, `WRITE_FILE`, `SEND_EMAIL`) are declared `safe: false` so they always reach the AI gates. See [architecture.md § Two ALLOW branches](architecture.md#two-allow-branches).

### System floor

Terminal command safety floors are **not** applied by the policy registry. `TerminalActionBundle.enforce_constraints` merges `SYSTEM_TERMINAL_BLOCKED_PATTERNS` (defined in `intentframe_native_kit/intentframe_native_bundles/actions/terminal/constraints.py`) with the user's `blocked_patterns` at runtime. A user can *add* deny patterns; they cannot remove the system floor. This guarantees a baseline even if the user's terminal policy is empty.

Dynamic recipient/contact sources (`recipient_sources`, `contact_sources` in Jarvis YAML) are also resolved at runtime by the email and message bundles during `enforce_constraints`, via `intentframe_native_kit/intentframe_native_bundles/platform/contacts_client.py`.

### Where to look

- `policy_registry/__init__.py` — public API
- `policy_registry/registry.py` — `PolicyRegistry` class (opaque CRUD + query)
- `policy_registry/models.py` — `UserPolicy`, `ActionPermission`, `SemanticIntentLimit`
- `policy_registry/server.py` — FastAPI service
- `policy_registry/client.py` — async client for callers
- `intentframe_native_kit/intentframe_native_bundles/actions/*/constraints.py` — typed constraint schemas per action family
- `intentframe_native_kit/intentframe_native_bundles/platform/contacts_client.py` — resolves contact-based policy sources at bundle enforcement time

---

## The resource registry

`intentframe_native_kit/resource_registry/` is what holds the user's workspaces and the platform's adapter inventory.

### Process and storage

Runs as a uvicorn FastAPI service on `~/.intentframe/run/resource-registry.sock`. Source: `intentframe_native_kit/resource_registry/server.py`. Backed by local SQLite. Started by the supervisor as one of its four core services.

### What it stores

```
Workspace
├── workspace_id
├── mounts: list[ResourceMount]
│        ResourceMount:
│          • virtual_path  (what the agent sees, e.g. "/invoices/")
│          • real_path     (what the executor uses, e.g. "/Users/me/inbox/")
│          • writable: bool
│          • file_filter   (e.g. "*.md")
│
└── (workspace metadata)

Adapter inventory
└── (each registered adapter's manifest)
```

### Two views

The registry's defining feature is that it serves *different views* to different consumers:

| View | Returned by | Contains |
|---|---|---|
| `ClientView` | `registry.client_view(workspace_id)` | Virtual paths and permissions only. The agent never sees real filesystem paths. |
| `ExecutorView` | `registry.executor_view(workspace_id)` | Full mount table with real paths. The executor uses this to resolve a virtual path the pipeline approved into the real path it will read or write. |

This is what implements the **virtual filesystem** that's referenced throughout the security docs. The agent thinks in terms of `/invoices/january.pdf`; the executor knows that resolves to `/Users/me/Documents/Inbox/january.pdf`. Path traversal attacks fail because the agent literally cannot name a path outside its mounts (`../..` resolves inside the virtual root or fails).

### What it doesn't do

The resource registry doesn't enforce path access — that's the executor's `FilesAdapter` job, using the `ExecutorView` mount table. The registry just stores the mounts and serves the right view to the right caller.

### Where to look

- `intentframe_native_kit/resource_registry/__init__.py` — public API
- `intentframe_native_kit/resource_registry/registry.py` — `ResourceRegistry` class, view derivation
- `intentframe_native_kit/resource_registry/models.py` — `ClientView`, `ExecutorView`, `ResourceMount`, `Workspace`
- `intentframe_native_kit/resource_registry/server.py` — FastAPI service
- `intentframe_native_kit/resource_registry/client.py` — async client
- `intentframe_native_kit/resource_registry/floor.py` — defaults / floor mounts

---

## How they get used together at decision time

When an `IntentFrame` arrives at the pipeline:

```
1. Pipeline looks up the action in intentframe_native_kit.action_registry
   → finds the ActionCategory and dispatching adapter
   → "READ_FILE belongs to FILE category, served by FilesAdapter"

2. Pipeline calls policy_registry.get_user_policy(user_id, agent_id)
   → returns UserPolicy with allowed_actions and intent_limits
   → "user has READ_FILE allowed with constraints={'allowed_paths': ['/invoices/']}"

3. DeterministicRunner + action bundles check:
   - is the action in allowed_actions?              (permission check)
   - does target satisfy bundle constraints?         (enforce_constraints hook)
   - any deny capability tags hit?                   (terminal bundle + command_shield)
   - any domain hard gate fire?                      (domain bundle check)
   - any fast-path ALLOW?                            (passive-read or allow_gates)

4. If executor reached:
   executor calls intentframe_native_kit.resource_registry.executor_view(workspace_id)
   → resolves virtual path to real path
   → FilesAdapter reads/writes that real path
```

Source of truth for the deterministic decision logic: `intentframe_components/guardian/deterministic.py`.

---

## Why three registries instead of one

The split is intentional and corresponds to "who owns this data":

| Registry | Owner | Lifecycle |
|---|---|---|
| Action registry | IntentFrame developers | Static. Changes only when IntentFrame ships a new action type. |
| Policy registry | The user | Mutable. Edited via dashboard / CLI / SDK whenever the user changes their mind. |
| Resource registry | The user (workspaces) + the platform (adapter inventory) | Workspaces are user-edited; adapter inventory is set at startup. |

Combining them would mix three different change cadences and three different trust levels into one store. The split keeps each registry small and each consumer's read surface narrow.

---

## Where capability tags live

The capability tags that `TerminalConstraints` uses (`capability:read_only:*`, `capability:network_probe:*`, `capability:filesystem_write`, …) live in `command_shield/`, not in a registry of their own. See [`../command_shield/README.md`](../command_shield/README.md) for the tag taxonomy and how Command Shield classifies a command into them.

---

## Limitations and gaps

- **Single-user.** The current registries are designed for one user's device. Multi-tenant policy administration (org-wide policies, per-team overrides) is not shipped.
- **No version history.** A policy edit overwrites the previous policy. There's no audit log of *who changed what when* on the configuration plane (the executor's audit log is for *executions*, not *configuration changes*).
- **Static action registry.** `intentframe_native_kit.action_registry` is in-process Python. New action types require a code change. (Adapters are pluggable; the action vocabulary is not, intentionally — it's the shared language between policy and pipeline.)
- **In-memory by default in dev mode.** The demo setup uses in-memory stores. Production runs the registries as supervised services with SQLite.

---

## Related documents

- [architecture.md](architecture.md) — How the Guardian uses policies in the deterministic gate and AI gate
- [processes.md](processes.md) — Where the policy and resource registries sit in the process tree
- [executor.md](executor.md) — How the executor uses the resource registry's `ExecutorView`
- [vfs-vs-host-tools.md](vfs-vs-host-tools.md) — Virtual filesystem vs host filesystem tools, both backed by resource_registry
- [executor/security-model.md](executor/security-model.md) — How `TerminalConstraints` and the terminal bundle system floor interact with `command_shield` capability tags
- [`../command_shield/README.md`](../command_shield/README.md) — Capability tag taxonomy
