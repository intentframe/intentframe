# Executor Architecture & Extensibility

> How the Executor is built, why it's an engine (not a workbench), and how it adapts to any service.

---

## Prerequisite

Read [../executor.md](../executor.md) first. That document covers **what** the
Executor does and its role in the IntentFrame separation of concerns. This
document covers **how** it is built internally and why that architecture
matters.

---

## The database engine analogy

A common question: *"Is the Executor like MySQL Workbench for capabilities?"*

No. MySQL Workbench is a convenience GUI that sits on top of a database
engine. It translates user actions into SQL protocol calls. If Workbench
crashes, MySQL keeps running. Workbench has no say in whether a query is
authorized.

The Executor is something more fundamental. It is the **engine itself**, not
the management tool.

```
MySQL world                          IntentFrame world
─────────────────────────────────    ─────────────────────────────────
MySQL Workbench (GUI client)     →   Guardian / Agent / CLI (callers)
Wire Protocol (TCP, socket)      →   Transport (Unix socket, gRPC)
Query Parser / Optimizer         →   Gateway (auth → validate → route)
Privilege System                 →   Auth Verifier
Storage Engines (InnoDB, etc.)   →   Capability Adapters
Binary Log                       →   Audit Logger + Hash Chain
```

The Executor **is** the process that performs operations — sends the email,
reads the file, hits the API. If the Executor rejects something, it doesn't
happen. Period. It enforces auth, audits everything, manages credentials, and
controls concurrency.

Guardian (or any future caller) is the *client* that speaks the protocol. The
Executor doesn't care who is calling — as long as they authenticate and speak
the protocol correctly.

```
                    The Executor is NOT this:
                    ┌─────────────────────────────┐
                    │  Management GUI / Workbench  │
                    │  (convenience layer on top)  │
                    └─────────────────────────────┘

                    The Executor IS this:
                    ┌─────────────────────────────┐
                    │  The Engine                  │
                    │  (does the actual work,      │
                    │   enforces all invariants,   │
                    │   owns the security model)   │
                    └─────────────────────────────┘
```

---

## Internal architecture

The Executor is structured as four layers within a single process:

```
┌─────────────────────────────────────────────────────────────┐
│ LAYER 1: TRANSPORT (pluggable)                              │
│   One active per deployment. Pure I/O pipe.                 │
│   Unix Socket (device) · gRPC (cloud) · REST (admin/debug)  │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ LAYER 2: EXECUTOR GATEWAY (orchestrator)                    │
│   Request Parser → Auth Verifier → Validator → Router       │
│   The gateway NEVER changes when you add capabilities.      │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ LAYER 3: CAPABILITY WORKER POOL                             │
│   Adapters execute actions with concurrency + timeout.      │
│   Each adapter: ~50-100 lines. Pluggable per deployment.    │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ LAYER 4: SHARED SERVICES (in-process)                       │
│   CredentialVault · AuditLogger · StateStore                │
│   VirtualFileSystem · HashChain · CredentialScrubber        │
│   SandboxEngine · SandboxPlanner                            │
└─────────────────────────────────────────────────────────────┘
```

**Key property:** Layers 1, 3, and 4 are all pluggable. Layer 2 (the gateway)
is the stable core — it orchestrates the flow but never needs modification
when capabilities, transports, or services change.

The worker pool is a bounded execution mechanism, not the singleton safety
boundary. In the local IntentFrame deployment, `intentframe-core` is the
serialized caller: it holds its runtime lock across evaluation, decision,
execution, and audit, so the executor normally receives one validated
execution request at a time. `max_workers` is a ceiling for executor robustness
if concurrent requests ever arrive; it must not be read as permission to run
multiple cores or callers against the same protected environment.

---

## The gateway flow: intent to execution

Every request follows the same pipeline, regardless of what capability is
being executed:

```
1. RECEIVE        Transport deserializes request
       ↓
2. VERIFY AUTH    AuthVerifier checks caller identity
       ↓          Invalid → REJECT + SecurityEvent
3. VALIDATE       Pydantic schema validation
       ↓
4. LOG START      AuditLogger records (params HASHED, creds SCRUBBED)
       ↓
5. ROUTE          ActionDispatcher resolves adapter
       ↓          Unknown action → REJECT (fail-closed)
6. CREDENTIAL     CredentialVault provides secrets in-process
       ↓          Credentials NEVER serialized
7. EXECUTE        WorkerPool runs adapter with timeout + exception catch
       ↓          adapter.safe_execute() wraps everything
       ↓          RUN_COMMAND: plan(max template) → sandbox-wrap → subprocess
8. ROLLBACK?      If reversible, StateStore saves rollback entry
       ↓
9. LOG END        AuditLogger records result + hash chain link
       ↓
10. RESPOND       Transport serializes and returns result
```

**Invariants enforced at every step:**

- Fail-closed: any failure → `ExecutionResult(success=False)`
- Credential isolation: secrets never serialized, never logged
- Virtual paths: agents never see real filesystem paths
- Timeout enforcement: `safe_execute()` wraps with `asyncio.wait_for()`
- Kernel sandbox: `RUN_COMMAND` subprocesses restricted by Seatbelt profile
  using `max(allowed_templates)`

---

## The adapter pattern: how extensibility works

Every capability follows the same pattern. An adapter is a class that
implements four methods:

```
┌─────────────────────────────────────────────────────────────┐
│  CapabilityAdapter (Abstract Base Class)                     │
│                                                              │
│  IMPLEMENT:                                                  │
│  ├── execute(action, params, credentials)  → result          │
│  ├── rollback(rollback_id)                 → result          │
│  ├── supported_actions()                   → ["ACTION_TYPE"] │
│  └── manifest()                            → identity + caps │
│                                                              │
│  FRAMEWORK PROVIDES (do not override):                       │
│  ├── safe_execute()   timeout + exception wrapper            │
│  └── safe_rollback()  timeout + exception wrapper            │
│                                                              │
│  CONTRACT:                                                   │
│  Adapters can raise, hang, or crash.                         │
│  safe_execute() catches EVERYTHING and returns failure.      │
└─────────────────────────────────────────────────────────────┘
```

The framework wraps every adapter call with `safe_execute()`. This means
adapter authors cannot accidentally break the gateway — any exception,
timeout, or crash becomes a clean failure result.

---

## The registry pattern

All extensible components use the same registration mechanism:

```
┌─────────────────────────────────────────────────────────────┐
│  REGISTRY PATTERN (used everywhere)                          │
│                                                              │
│  register_*("name", ComponentClass)   ← at import time      │
│  create_*("name", **config)           ← at startup          │
│                                                              │
│  APPLIES TO:                                                 │
│  ├── Adapters         register_adapter()                     │
│  ├── Transports       register_transport()                   │
│  ├── Auth Verifiers   register_auth_verifier()               │
│  ├── Credential Vault register_credential_vault()            │
│  ├── Audit Logger     register_audit_logger()                │
│  └── State Store      register_state_store()                 │
│                                                              │
│  Registration: executor pack startup (`register_all()`)    │
│  Instantiation: startup (config-driven via executor.yaml)    │
│                                                              │
│  Deployments list packs explicitly in executor.yaml `packs:`;│
│  there are no built-in or platform-default packs.            │
└─────────────────────────────────────────────────────────────┘
```

The gateway has zero knowledge of which specific adapters, transports, or
services exist. It works through interfaces. Swap the pieces, the gateway
doesn't notice.

---

## Adding a new service: concrete example

Suppose you want to add **Telegram messaging** as a capability.

### Step 1: create the adapter (~50–100 lines)

```
TelegramAdapter(CapabilityAdapter)
│
├── supported_actions()  → ["SEND_TELEGRAM", "READ_TELEGRAM"]
├── manifest()           → adapter_id="telegram", name="Telegram Messaging"
├── execute()            → uses bot token from vault, sends message
└── rollback()           → returns failure ("Messages are irreversible")
```

### Step 2: register inside an executor pack

Call `register_adapter()` from your pack's `register_all()` (or
`register_all_adapters()`). Registration only happens when the executor loads
that pack — listing an adapter ID in `adapters.enabled` alone is not enough.

```python
# my_org_pack/adapters/__init__.py
from executor_sdk.adapters import register_adapter
from my_org_pack.adapters.telegram import TelegramAdapter

def register_all_adapters() -> None:
    register_adapter("telegram", TelegramAdapter)
```

External orgs ship a pack module with `register_all()` and optionally advertise
it under the `intentframe.executor_packs` entry-point group.

### Step 3: list the pack in config

```yaml
# executor.yaml
packs:
  - my_org_pack
```

### Step 4: enable the adapter

```yaml
# executor.yaml
adapters:
  enabled:
    - telegram
```

`packs:` loads transport, auth, storage, and adapter registrations at startup.
`adapters.enabled` selects which registered adapters the gateway instantiates.
Both are required.

### What you get for free

Without writing a single extra line, your Telegram adapter automatically
gets:

| Feature | How |
|---------|-----|
| Authentication | Gateway verifies caller before routing to adapter |
| Credential isolation | Bot token loaded from vault, never serialized/logged |
| Timeout enforcement | `safe_execute()` wraps with configurable timeout |
| Exception safety | Any crash → clean failure result (not gateway crash) |
| Full audit trail | Every send logged with hash chain integrity |
| Credential scrubbing | Bot token scrubbed from all logs automatically |
| Concurrency control | Worker pool manages parallel execution |
| Rollback tracking | Framework records whether action is reversible |
| Kernel sandbox | `RUN_COMMAND` subprocesses automatically sandboxed (terminal adapter) |

The gateway code does not change. The protocol does not change. You plug in
an adapter.

---

## What about custom workflows?

This is where the design gets intentional.

### The Executor is NOT a workflow engine

The Executor handles **single actions**. Each `ExecutionRequest` maps to one
action on one adapter.

| The Executor handles | The Executor does NOT handle |
|---------------------|------------------------------|
| "Send this Telegram message" | "Read invoice → extract amounts → send summary to Telegram → create calendar reminder" |
| "Read this file" | Multi-step orchestration |
| "Create this calendar event" | Conditional branching between steps |

### Why this is deliberate

Multi-step orchestration is the **caller's** job. This boundary exists for
three reasons:

**1. Security per step.** Each action is independently authorized, audited,
and isolated. Composing actions at the Executor level would blur the audit
trail. You need to know exactly which step failed and why.

**2. Fail-closed per step.** If step 3 of 5 fails, who decides what happens?
Retry? Roll back steps 1–2? Abort? That's a policy decision — the Executor
shouldn't make policy decisions. The caller decides.

**3. Caller-agnostic orchestration.** Different callers may want different
orchestration logic for the same capabilities. A Guardian might enforce
sequential approval. A batch system might fire-and-forget. A CLI might be
interactive. The Executor serves all of them equally.

### Where workflows live

```
┌──────────────────────────────────────────────┐
│  WORKFLOW LAYER (caller's responsibility)     │
│  Agent / Guardian / Custom Orchestrator       │
│  "Read file → parse → send Telegram → log"   │
└────────────┬──────────┬──────────┬───────────┘
             │          │          │
      ┌──────▼──┐  ┌───▼────┐  ┌─▼──────────┐
      │READ_FILE│  │SEND_   │  │CREATE_     │
      │         │  │TELEGRAM│  │CALENDAR    │
      │(executor│  │(executor│ │(executor   │
      │ call 1) │  │ call 2) │ │ call 3)    │
      └─────────┘  └────────┘  └────────────┘

Each call: independently authed, audited, isolated.
The workflow layer composes them.
The Executor doesn't know or care about the composition.
```

**The Executor is the muscle, not the brain.** The brain (workflow logic)
sits above. This means the same Executor serves completely different workflow
patterns without any changes to its internals.

---

## Deploy anywhere: what changes vs. what doesn't

The same Executor core runs on any platform. Only the pluggable components
change:

| Changes per deployment | Stays identical everywhere |
|------------------------|---------------------------|
| Transport (socket vs gRPC vs REST) | Gateway logic |
| Credential backend (Keychain vs Vault vs KMS) | Auth interface |
| Available adapters (macOS vs cloud vs custom) | Adapter pattern |
| Sandbox engine (Seatbelt vs seccomp vs Job Objects) | Sandbox planner logic |
| Lifecycle manager | Audit trail + hash chain |
|  | Fail-closed behavior |
|  | Credential isolation |
|  | Virtual filesystem abstraction |

### Example deployments

**macOS device:**
```
Transport:   Unix Socket
Auth:        Guardian HMAC
Credentials: macOS Keychain
Adapters:    Files, Mail, Calendar, Browser, Messages, Terminal, etc.
Sandbox:     Seatbelt / sandbox-exec (dynamic SBPL profiles)
Audit:       SQLite
```

**Cloud server:**
```
Transport:   gRPC
Auth:        mTLS
Credentials: HashiCorp Vault
Adapters:    S3, SES, Lambda, custom APIs
Audit:       CloudWatch / managed DB
```

**Custom enterprise:**
```
Transport:   REST
Auth:        JWT / Bearer
Credentials: AWS KMS
Adapters:    Telegram, Slack, Jira, internal APIs
Audit:       Enterprise SIEM
```

In every case, the gateway, fail-closed behavior, credential isolation, audit
integrity, and adapter contract are identical.

---

## Current capabilities (macOS platform)

18 adapters currently registered:

| Category | Adapters |
|----------|----------|
| **Core** | Files, Terminal, HTTP API, User I/O |
| **Communication** | Mail, Messages, Notifications |
| **PIM** | Calendar, Contacts, Notes, Reminders |
| **System** | Browser, System, Clipboard, Shortcuts, Spotlight, Filesystem Watch |

Each follows the same `CapabilityAdapter` pattern. Each gets the same
security guarantees.

---

## Known limitations

These are current architectural constraints, not design flaws:

| Limitation | Detail | Implication |
|------------|--------|-------------|
| **Static registration** | Adapters register at import time, before gateway starts | No hot-plugging new adapters at runtime |
| **One adapter per action** | `SEND_TELEGRAM` maps to exactly one adapter | Cannot have competing adapters for same action |
| **No workflow composition** | Deliberately single-action | Multi-step logic must be external |
| **Manual platform registration** | Must call `register_all()` explicitly | No auto-discovery from filesystem |
| **Some features planned but not built** | ProcessPoolExecutor, gRPC, mTLS, Redis state store | In the implementation plan |

---

## Summary

```
The Executor is:
├── An engine, not a workbench (it does the work, it doesn't manage a UI)
├── Caller-agnostic (Guardian is one client, not the only one)
├── Pluggable at every layer (transport, auth, adapters, services, sandbox engine)
├── Single-action by design (workflow composition is external)
├── Kernel-sandboxed for RUN_COMMAND (Seatbelt on macOS, seccomp planned for Linux)
├── Deploy-anywhere (same core, different plugins per platform)
└── ~50-100 lines per new capability (adapter pattern)

Adding a new service (Telegram, Slack, Jira, anything):
├── Implement CapabilityAdapter (4 methods)
├── Register it
├── Enable in config
└── Get auth, audit, credentials, timeouts, scrubbing for free
```

---

## Related documents

- [../executor.md](../executor.md) — Conceptual role: what the Executor does and doesn't do
- [security-model.md](security-model.md) — Prevention philosophy and the sandbox safety net
- [why-foundation.md](why-foundation.md) — Why the Executor is the structural foundation of agent safety
- [standalone-product.md](standalone-product.md) — The Executor as a standalone piece of infrastructure
- [`../../executor/plan.md`](../../executor/plan.md) — Full implementation plan with module design
- [`../../executor/sandbox.md`](../../executor/sandbox.md) — Kernel sandbox implementation reference
- [../architecture.md](../architecture.md) — Overall system architecture
