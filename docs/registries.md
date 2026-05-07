# The Registries

> The configuration plane of IntentFrame — what actions can exist, what the user has authorized, and what resources they expose to the agent.

IntentFrame separates **configuration** (what's allowed, what exists) from **decision-making** (whether a specific action should run). Configuration lives in three small registries; decisions happen in the Guardian. This separation is what lets a non-AI rule change the system's behavior — you edit a registry, and the Guardian's next decision reflects that edit, deterministically.

This doc covers all three registries together because they share the same shape (a typed data store with separate read views per consumer) and they're commonly read together at decision time.

---

## The three registries at a glance

| Registry | Source | What it stores | Who writes it | Who reads it |
|---|---|---|---|---|
| **Action registry** | `action_registry/` | The universal *taxonomy* — every action that *can* exist (`READ_FILE`, `RUN_COMMAND`, `PAY_INVOICE`, …), its category, its metadata | IntentFrame developers (it's a static catalog) | Policy registry (to validate user policies); pipeline (to dispatch to adapters) |
| **Policy registry** | `policy_registry/` | The user's *rules* — which actions are allowed, what constraints apply, what intent limits, plus a system-level blocked-pattern floor | The user (via dashboard / CLI / SDK at registration time) | Guardian (every validation), Analysis Engine (to adjust depth) |
| **Resource registry** | `resource_registry/` | The user's *workspaces* and resource mounts — virtual paths, real paths, writability, file filters, plus the registered adapter inventory | The user (when defining workspaces) and platform (when adapters register) | Agent client (sees `ClientView` — virtual paths only); executor (sees `ExecutorView` — full mount table with real paths) |

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
│ of every action  │   │ intent limits +    │   │ mounts + adapter   │
│ that CAN exist   │   │ system floor       │   │ inventory          │
│                  │   │                    │   │                    │
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
│  Pipeline uses action_registry to dispatch to the right adapter      │
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

`action_registry/` defines the universal action vocabulary. It's a static, in-process catalog — not a service.

### What's in it

```
ActionCategory ─── enum (FILE, HOST_FILE, TERMINAL, EMAIL, CALENDAR, …)
ActionType ─────── enum (READ_FILE, WRITE_FILE, RUN_COMMAND, PAY_INVOICE, …)
ActionMeta ─────── per-action metadata (category, domain, description)
DomainType ─────── enum (FINANCE, COMMUNICATION, FILESYSTEM, …)
ActionCatalog ──── lookup: ActionType → ActionMeta
```

Each `ActionType` belongs to exactly one `ActionCategory`. Categories determine which constraint schema applies when a user writes a policy. For example:

- `READ_FILE`, `WRITE_FILE`, `LIST_DIRECTORY` → `ActionCategory.FILE` → `FileConstraints` (allowed paths, file filters)
- `SEND_EMAIL`, `READ_EMAIL` → `ActionCategory.EMAIL` → `EmailConstraints` (recipient sources)
- `RUN_COMMAND` → `ActionCategory.TERMINAL` → `TerminalConstraints` (allow/deny capability tags)
- `PAY_INVOICE` → `ActionCategory.API` + `DomainType.FINANCE` → finance hard gate

### Why it's a separate module

So the policy registry can validate that a user's rule references a real action type, and so the pipeline can dispatch typed intents to the right adapter — both without depending on each other. Both `policy_registry` and the IntentFrame pipeline import from `action_registry`; nothing else points the other way.

### Where to look

- `action_registry/types.py` — enums and metadata models
- `action_registry/catalog.py` — `ActionCatalog` registration

---

## The policy registry

`policy_registry/` is what holds the user's actual rules.

### Process and storage

Runs as a uvicorn FastAPI service on `~/.intentframe/run/policy-registry.sock`. Source: `policy_registry/server.py`. Backed by local SQLite. Started by the supervisor as one of its four core services.

### What it stores

```
UserPolicy
├── user_id
├── allowed_actions: dict[ActionType → ActionPermission]
│        ActionPermission:
│          • safe: bool                ← critical for fast-path routing
│          • constraints: typed schema  ← FileConstraints / EmailConstraints / …
│          • description
│
├── intent_limits: list[SemanticIntentLimit]
│        SemanticIntentLimit:
│          • limit_id, domain, raw text, optional threshold
│
└── (per-policy metadata)

SYSTEM_TERMINAL_BLOCKED_PATTERNS  ← system-level safety floor
                                     merged into every user's TerminalConstraints
                                     on read; users can append, cannot remove
```

### Two important properties

**Policies are declared at registration time.** The user (or developer) declares the policy when they install or onboard an agent. The agent itself cannot influence what's in the policy registry at runtime. This is what closes the "compromised agent talks the Guardian into a policy exception" attack — there's nothing for the agent to talk *to*. The policy is data, not a conversation.

**Rules are deterministic.** The policy registry stores facts (action allowlists, path constraints, intent limits, deny patterns). The Guardian's deterministic gate (`DeterministicGuardian`) consults these facts and produces ALLOW / BLOCK / UNDECIDED without an LLM. Most safe and most catastrophic intents are decided here.

### What `safe: true` does

`ActionPermission.safe` is a routing decision the user makes at registration time. If an action is marked `safe: true` AND it's in the developer-curated `_PRE_AE_SAFE_READS` set (passive reads like `LIST_DIRECTORY`), the pipeline takes the fast-path and never calls an LLM. Mutating actions (`PAY_INVOICE`, `WRITE_FILE`, `SEND_EMAIL`) are declared `safe: false` so they always reach the AI gates. See [architecture.md § Two ALLOW branches](architecture.md#two-allow-branches).

### System floor

The registry merges `SYSTEM_TERMINAL_BLOCKED_PATTERNS` (a tuple of regex patterns for known-catastrophic shell command shapes) into every user's `TerminalConstraints` on read. A user can *add* deny patterns; they cannot remove the system floor. This guarantees a baseline even if the user's terminal policy is empty.

### Where to look

- `policy_registry/__init__.py` — public API
- `policy_registry/registry.py` — `PolicyRegistry` class, system floor merging
- `policy_registry/models.py` — `UserPolicy`, `ActionPermission`, `SemanticIntentLimit`
- `policy_registry/constraints/` — typed constraint schemas (`file.py`, `email.py`, `message.py`, `terminal.py`)
- `policy_registry/server.py` — FastAPI service
- `policy_registry/client.py` — async client for callers
- `policy_registry/contacts_client.py` — bridges contact-based recipient policies to the macOS Contacts framework

---

## The resource registry

`resource_registry/` is what holds the user's workspaces and the platform's adapter inventory.

### Process and storage

Runs as a uvicorn FastAPI service on `~/.intentframe/run/resource-registry.sock`. Source: `resource_registry/server.py`. Backed by local SQLite. Started by the supervisor as one of its four core services.

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

- `resource_registry/__init__.py` — public API
- `resource_registry/registry.py` — `ResourceRegistry` class, view derivation
- `resource_registry/models.py` — `ClientView`, `ExecutorView`, `ResourceMount`, `Workspace`
- `resource_registry/server.py` — FastAPI service
- `resource_registry/client.py` — async client
- `resource_registry/floor.py` — defaults / floor mounts

---

## How they get used together at decision time

When an `IntentFrame` arrives at the pipeline:

```
1. Pipeline looks up the action in action_registry
   → finds the ActionCategory and dispatching adapter
   → "READ_FILE belongs to FILE category, served by FilesAdapter"

2. Pipeline calls policy_registry.get_user_policy(user_id)
   → returns UserPolicy with allowed_actions and intent_limits
   → "user has READ_FILE allowed with FileConstraints(allowed_paths=['/invoices/'])"

3. DeterministicGuardian checks:
   - is the action in allowed_actions?     (permission check)
   - does target satisfy constraints?       (constraint check)
   - any deny capability tags hit?          (capability check)
   - any domain hard gate fire?             (domain module check)
   - any fast-path ALLOW?                   (passive-read or run-command read-only)

4. If executor reached:
   executor calls resource_registry.executor_view(workspace_id)
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
- **Static action registry.** `action_registry` is in-process Python. New action types require a code change. (Adapters are pluggable; the action vocabulary is not, intentionally — it's the shared language between policy and pipeline.)
- **In-memory by default in dev mode.** The demo setup uses in-memory stores. Production runs the registries as supervised services with SQLite.

---

## Related documents

- [architecture.md](architecture.md) — How the Guardian uses policies in the deterministic gate and AI gate
- [processes.md](processes.md) — Where the policy and resource registries sit in the process tree
- [executor.md](executor.md) — How the executor uses the resource registry's `ExecutorView`
- [vfs-vs-host-tools.md](vfs-vs-host-tools.md) — Virtual filesystem vs host filesystem tools, both backed by resource_registry
- [executor/security-model.md](executor/security-model.md) — How `TerminalConstraints` (in policy registry) interact with `command_shield` capability tags
- [`../command_shield/README.md`](../command_shield/README.md) — Capability tag taxonomy
