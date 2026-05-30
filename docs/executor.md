# The Executor

> The only thing in IntentFrame that touches the real world.

Everything else in IntentFrame thinks, parses, understands, or judges. The
Executor is the only component that **acts**. It holds every credential, owns
every IO surface, applies the kernel sandbox, writes the audit trail, and
executes the validated intent.

If you understand nothing else about IntentFrame, understand this: the Executor
is the structural reason agents in IntentFrame cannot do harm. Guardian decides
*whether* an action should happen. The Executor is *what makes* "happens" mean
something — and it is the only component with the keys.

This document is the canonical reference. Deeper material lives in the
[`executor/`](executor/) subfolder. For the wider picture of which processes
run alongside the Executor and how data flows on disk, see
[processes.md](processes.md) and [privacy.md](privacy.md).

---

## 1. What it is, in one paragraph

The Executor is a standalone, caller-agnostic service that performs validated
actions on behalf of a caller (in IntentFrame, that caller is the Guardian).
It is the only process with credentials, the only process with direct access
to files and APIs, and the only process whose output mutates the user's world.
It is mechanical, not judgmental — it executes what Guardian approves and does
not second-guess that decision. It speaks a defined wire protocol, runs as a
separate process, exposes capabilities through a pluggable adapter pattern,
and applies a kernel-enforced sandbox to every shell subprocess it spawns.

---

## 2. The mental model: an engine, not a workbench

The most common confusion is treating the Executor like a tool gateway or a
management UI. It is neither.

```
MySQL world                          IntentFrame world
─────────────────────────────────    ─────────────────────────────────
MySQL Workbench (GUI client)     →   Guardian / Agent / CLI (callers)
Wire protocol (TCP, socket)      →   Transport (Unix socket, gRPC)
Query parser / optimizer         →   Gateway (auth → validate → route)
Privilege system                 →   Auth verifier
Storage engines (InnoDB, etc.)   →   Capability adapters
Binary log                       →   Audit logger + hash chain
```

Workbench is a convenience wrapper that translates clicks into protocol calls.
If Workbench crashes, MySQL keeps serving queries. Workbench has no say in
whether a query is authorized. It is a client, not the database.

The Executor is the database. It is the process that performs the operation,
enforces auth, audits everything, manages credentials, and controls execution.
Guardian is one client of that engine. A CLI tool is another. A CI/CD pipeline
could be a third. The engine doesn't care who is calling — only that the caller
authenticated and spoke the protocol correctly.

This is why the Executor stands on its own: it is infrastructure, not glue.
See [executor/standalone-product.md](executor/standalone-product.md) for the
full positioning argument.

---

## 3. What it does and does not do

### Does

| Responsibility | Description |
|----------------|-------------|
| Execute actions | Perform validated intents (file IO, API calls, transactions) |
| Hold credentials | Only entity in the system with API keys, OAuth tokens, secrets |
| Sandbox `RUN_COMMAND` | Kernel-enforced restrictions on every shell subprocess |
| Handle errors | Retry logic, circuit breakers, graceful failures |
| Roll back | Undo reversible actions when safe |
| Log everything | Immutable, hash-chained audit trail of every execution |

### Does not

| Forbidden | Why |
|-----------|-----|
| Question wisdom of an intent | Guardian already decided. Executor obeys. |
| Modify an intent | Breaks audit trail and approval semantics. |
| Decide what's "good for the user" | Prevents executor overreach. |
| Make policy exceptions | Maintains structural integrity. |
| Share credentials with any other component | Credentials never leave the Executor process. |

The Executor has **mechanical intelligence** — smart about *how* to execute,
not *whether* to execute. It can be sophisticated about retries, error
recovery, rollback strategies, and resource management. It is not allowed to
form an opinion about whether the action should happen.

---

## 4. The execution flow

Every request follows the same pipeline, regardless of which capability is
being invoked:

```
1. RECEIVE        Transport deserializes the request
       ↓
2. VERIFY AUTH    AuthVerifier checks caller identity
       ↓          Invalid → REJECT + SecurityEvent
3. VALIDATE       Pydantic schema validation of action + params
       ↓
4. LOG START      AuditLogger records the request (params hashed, creds scrubbed)
       ↓
5. ROUTE          ActionDispatcher resolves which adapter handles this action
       ↓          Unknown action → REJECT (fail-closed)
6. CREDENTIAL     CredentialVault provides secrets in-process to the adapter
       ↓          Credentials never serialized, never leave the process
7. EXECUTE        WorkerPool runs adapter.execute() with timeout + exception catch
       ↓          RUN_COMMAND: planner.plan() → engine.wrap() → sandboxed subprocess
8. ROLLBACK?      If reversible, StateStore saves a rollback entry
       ↓
9. LOG END        AuditLogger records the result and links to the hash chain
       ↓
10. RESPOND       Transport serializes and returns the result
```

Every step is fail-closed: any failure, any timeout, any unexpected exception
becomes a clean `ExecutionResult(success=False)` returned to the caller. The
gateway never crashes because an adapter misbehaved.

---

## 5. Credential isolation

Credentials are the highest-value target in any agent system. IntentFrame's
answer is structural: there is exactly one process that has them.

```
┌─────────────────────────────────────────────────────────────────┐
│  CREDENTIAL BOUNDARY                                            │
│                                                                 │
│  Third-party agent:      NO credentials                         │
│  Actor SDK:              NO credentials                         │
│  Analysis Engine:        NO credentials                         │
│  Guardian:               NO credentials                         │
│  Executor:               ALL credentials (isolated)             │
│                                                                 │
│  Credentials never leave the Executor process.                  │
│  Credentials are never logged, transmitted, or serialized.      │
│  Credentials are never visible to the agent or pipeline.        │
└─────────────────────────────────────────────────────────────────┘
```

This is why a prompt injection that says "print your environment variables"
fails to leak anything useful in IntentFrame: the agent's environment doesn't
contain the credentials. The Executor, in a separate process, holds them.

The audit logger automatically scrubs credential-shaped values from every log
record. The credential vault serves secrets directly into adapter call frames
that never cross a process boundary.

---

## 6. Adapters: how capability is added

Every capability in the Executor is implemented as a small adapter class. The
gateway has zero knowledge of which specific adapters exist — it works through
an interface.

### The contract

```
CapabilityAdapter (abstract base class)

  IMPLEMENT:
    execute(action, params, credentials)  → ExecutionResult
    rollback(rollback_id)                 → ExecutionResult
    supported_actions()                   → list of action types
    manifest()                            → identity + capability metadata

  FRAMEWORK PROVIDES (do not override):
    safe_execute()    timeout + exception wrapper
    safe_rollback()   timeout + exception wrapper

  CONTRACT:
    Adapters can raise, hang, or crash.
    safe_execute() catches everything and returns a clean failure result.
```

A typical adapter is 50–100 lines. The framework wraps every adapter call
with `safe_execute()`, which means an adapter author cannot accidentally
break the gateway.

### Adding a new service: the Telegram example

Suppose you want to add Telegram messaging.

**Step 1: write the adapter (~50 lines)**

```
TelegramAdapter(CapabilityAdapter)
  ├── supported_actions()  → ["SEND_TELEGRAM", "READ_TELEGRAM"]
  ├── manifest()           → adapter_id="telegram", name="Telegram Messaging"
  ├── execute()            → uses bot token from vault, sends message
  └── rollback()           → returns failure ("Messages are irreversible")
```

**Step 2: register inside an executor pack**

Adapters are not loaded automatically. Your pack's `register_all()` (or
`register_all_adapters()`) must call `register_adapter()` so the executor
knows the adapter exists when that pack is listed in config:

```python
# my_org_pack/adapters/__init__.py
from executor_sdk.adapters import register_adapter
from my_org_pack.adapters.telegram import TelegramAdapter

def register_all_adapters() -> None:
    register_adapter("telegram", TelegramAdapter)
```

Third-party packs can advertise themselves under the
`intentframe.executor_packs` entry-point group in `pyproject.toml` so
deployments reference them by short name.

**Step 3: list the pack in config**

```yaml
# executor.yaml
packs:
  - my_org_pack          # or full module path / entry-point name
```

**Step 4: enable the adapter**

```yaml
# executor.yaml
adapters:
  enabled:
    - telegram
```

Both steps are required: `packs:` loads implementations at startup;
`adapters.enabled` selects which registered adapters the gateway wires up.

### What you get for free

Without writing another line, the new adapter automatically inherits:

| Feature | How |
|---------|-----|
| Authentication | Gateway verifies caller before routing |
| Credential isolation | Bot token loaded from vault, never serialized or logged |
| Timeout enforcement | `safe_execute()` wraps with configurable timeout |
| Exception safety | Any crash → clean failure, not a gateway crash |
| Audit trail | Every send logged with hash chain integrity |
| Credential scrubbing | Bot token redacted from all logs automatically |
| Concurrency control | Worker pool manages parallel execution |
| Rollback tracking | Framework records reversibility |

The gateway code does not change. The wire protocol does not change. You plug
in an adapter.

For the full architecture and registry pattern, see
[executor/architecture.md](executor/architecture.md).

---

## 7. Current capabilities (macOS)

The current macOS deployment ships 18 adapters:

| Category | Adapters |
|----------|----------|
| Core | Files, Terminal, HTTP API, User IO |
| Communication | Mail, Messages, Notifications |
| PIM | Calendar, Contacts, Notes, Reminders |
| System | Browser, System, Clipboard, Shortcuts, Spotlight, Filesystem Watch |

Each adapter implements the same contract and inherits the same security
guarantees. New deployments choose which **executor packs** to load (`packs:`)
and which adapters to enable (`adapters.enabled`) in `executor.yaml`.

---

## 8. `RUN_COMMAND` and the kernel sandbox

Of all the action types the Executor handles, exactly one spawns a subprocess
running arbitrary code: `RUN_COMMAND`. Every other action is performed by
typed adapter code that does one specific thing — there is no command string
to interpret, no subprocess to confine.

`RUN_COMMAND` is therefore the only action that needs both the full prevention
pipeline (Command Shield → Deterministic Guardian → Analysis Engine → AI
Guardian → adapter `quick_check`) AND a kernel sandbox as a safety net.

### What the sandbox does

Every `RUN_COMMAND` subprocess is wrapped in a macOS Seatbelt profile
(`sandbox-exec`) before it runs. The kernel denies syscalls that violate the
profile. This is real OS-level enforcement, not string matching or process
filtering.

```
TerminalAdapter.execute()
  ├── command_shield.quick_check()    last-resort pattern check
  ├── planner.plan(cwd)               uses max(allowed_templates) from config
  ├── engine.wrap(command, plan)      builds SBPL profile inline
  │       └── sandbox-exec -p '<profile>' /bin/sh -c '<cmd>'
  └── create_subprocess_exec(*argv)
```

### Templates

```python
class SandboxTemplate(str, Enum):
    PURE_COMPUTE     = "pure_compute"
    FILE_READ_ONLY   = "file_read_only"
    FILE_READ_WRITE  = "file_read_write"
    NETWORK_OUTBOUND = "network_outbound"
    NETWORK_FULL     = "network_full"
    UNRESTRICTED     = "unrestricted"
```

| Template | File read | File write | Net out | Net bind | Fork | Signal |
|----------|-----------|------------|---------|----------|------|--------|
| PURE_COMPUTE | No | No | No | No | No | No |
| FILE_READ_ONLY | Allowed paths | No | No | No | No | No |
| FILE_READ_WRITE | Allowed paths | Allowed paths | No | No | No | No |
| NETWORK_OUTBOUND | Allowed paths | Allowed paths | Yes | No | No | No |
| NETWORK_FULL | Allowed paths | Allowed paths | Yes | Yes | Limited | No |
| UNRESTRICTED | Allowed paths | Allowed paths | Yes | Yes | Yes | No |

### Non-negotiable deny base

Every template, regardless of how permissive, denies:

- writes to system paths (`/System`, `/usr`, `/bin`, `/sbin`)
- writes to persistence paths (`/Library/LaunchDaemons`, `~/Library/LaunchAgents`)
- reads or writes to IntentFrame runtime data (`~/.intentframe/`)
- removing or modifying the sandbox itself (Seatbelt is one-way)

These rules are appended last in the SBPL profile, and Seatbelt is
last-match-wins, so they always override more permissive earlier rules.

### `max(allowed_templates)` policy

There is no per-command classification. The admin lists allowed templates in
`executor.yaml`, and every command runs under `max(allowed_templates)` — the
highest-privilege template approved. Prevention is the prevention pipeline's
job. The sandbox is a consistent safety net, not a policy engine.

### Configuration

```yaml
pack_options:
  sandbox:
    enabled: true
    allowed_templates:
      - pure_compute
      - file_read_only
      - file_read_write
    # All commands run under file_read_write (the max).
```

### Platform support

| Platform | Mechanism | Status |
|----------|-----------|--------|
| macOS | `sandbox-exec` (Seatbelt) | Implemented — dynamic SBPL profile, 126 tests |
| Linux | `seccomp-bpf` or Bubblewrap | Planned — engine ABC is platform-pluggable |
| Windows | Job Objects + Restricted Tokens | Planned |

No containers. No VMs. No installation. No startup latency. The sandbox is a
kernel flag on the spawned process.

For the full implementation reference (SBPL profile structure, path
canonicalization, controlled `TMPDIR`, fail-closed behavior),
see [`executor/sandbox.md`](../executor/sandbox.md). For the broader
prevention-vs-containment philosophy and how the sandbox slots into the full
5-gate prevention pipeline, see
[executor/security-model.md](executor/security-model.md).

---

## 9. Audit trail and rollback

### Every action is logged

```json
{
  "execution_id": "exec_abc123",
  "intent_frame_id": "if_xyz789",
  "action": "PAY",
  "target": "vendor_123",
  "amount": 45.00,
  "timestamp": "2026-05-07T10:30:15Z",
  "result": "SUCCESS",
  "external_reference": "txn_stripe_456",
  "duration_ms": 234,
  "rollback_available": true,
  "audit_hash": "sha256:..."
}
```

Audit records are hash-chained: each record links to the previous record's
hash. Tampering with one record invalidates every later record. Credentials
are scrubbed before write.

### Rollback model

For reversible actions, the Executor records how to undo:

```
Action: CREATE file
Rollback: DELETE file
Window: 24 hours

Action: SEND email
Rollback: NOT POSSIBLE — irreversible action, was flagged to Guardian

Action: PAY invoice
Rollback: REQUEST_REFUND (depends on processor)
Window: Varies by payment processor
```

Irreversibility is information that flows back to Guardian for future
decisions, not just an Executor implementation detail.

---

## 10. Why the Executor is the structural foundation

IntentFrame's safety story is often told in terms of Guardian: "the AI judge
that decides whether actions are allowed." That framing is correct but
incomplete. The structural reality is that Guardian decides *logically*. The
Executor enforces *structurally*.

```
EXECUTOR  =  the vault door (physical barrier)
GUARDIAN  =  the combination lock + security guard (access control)

Without the vault door → the lock protects nothing.
Without the lock → the vault door still blocks entry, just less intelligently.
```

Most of IntentFrame's hard safety properties are Executor properties:

| Safety property | Provided by |
|-----------------|-------------|
| Agents have zero direct IO | Executor (only process with credentials) |
| Credentials never leave the boundary | Executor (credential isolation) |
| Agents see virtual paths, not the real filesystem | Executor (VirtualFileSystem) |
| Every action is hash-chain audited | Executor (AuditLogger) |
| Failures result in clean rejection, not undefined state | Executor (`safe_execute` + fail-closed) |
| Actions can be rolled back | Executor (StateStore + rollback) |
| `RUN_COMMAND` subprocesses are kernel-sandboxed | Executor (Seatbelt / `sandbox-exec`) |
| Agents are told yes or no before anything happens | Guardian (policy) |
| Unusual patterns are detected | Guardian (anomaly detection) |
| Policy limits enforced (caps, paths) | Guardian (rule engine) |

A robust Executor with a dumb rules-only Guardian is meaningfully safe.
A brilliant Guardian with a weak Executor is theater.

For the full thought experiment — what happens if you remove either component
— see [executor/why-foundation.md](executor/why-foundation.md).

---

## 11. Deploy anywhere

The same Executor core runs on any platform. Only the pluggable pieces change.

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

### Examples

**macOS device (current Jarvis deployment)**

```
Transport:    Unix socket
Auth:         Guardian HMAC
Credentials:  macOS Keychain
Adapters:     Files, Mail, Calendar, Browser, Messages, Terminal, …
Sandbox:      Seatbelt / sandbox-exec (dynamic SBPL profiles)
Audit:        SQLite
```

**Cloud server (future)**

```
Transport:    gRPC
Auth:         mTLS
Credentials:  HashiCorp Vault
Adapters:     S3, SES, Lambda, custom APIs
Audit:        CloudWatch / managed DB
```

**Custom enterprise (future)**

```
Transport:    REST
Auth:         JWT / Bearer
Credentials:  AWS KMS
Adapters:     Telegram, Slack, Jira, internal APIs
Audit:        Enterprise SIEM
```

In every case, the gateway, fail-closed behavior, credential isolation, audit
integrity, and adapter contract are identical.

---

## 12. Current limitations

These are honest constraints, not design flaws:

| Limitation | Detail | Implication |
|------------|--------|-------------|
| Static registration | Adapters register at import time, before gateway starts | No hot-plugging adapters at runtime |
| One adapter per action | `SEND_TELEGRAM` maps to exactly one adapter | No competing adapters for the same action |
| No workflow composition | Deliberately single-action | Multi-step logic must live in the caller |
| Manual platform registration | Must call `register_all()` explicitly | No auto-discovery from filesystem |
| Some features planned | ProcessPoolExecutor, gRPC, mTLS, Redis state store | In the implementation plan |

The Executor is intentionally *not* a workflow engine. Each `ExecutionRequest`
maps to one action on one adapter. Multi-step orchestration is the caller's
job — different callers want different orchestration semantics, and composing
actions at the Executor level would blur the audit trail. See
[executor/architecture.md § What about custom workflows](executor/architecture.md#what-about-custom-workflows)
for the full reasoning.

---

## 13. SDK environment (development)

The SDK ships an Executor Simulator for development:

```
┌─────────────────────────────────────────────────────────────────┐
│  EXECUTOR SIMULATOR (dev only)                                  │
│                                                                 │
│  • Receives validated intents from Guardian Emulator            │
│  • Simulates execution (no real actions)                        │
│  • Predicts outcomes based on action type                       │
│  • Returns simulated results                                    │
│  • Logs simulated audit trail                                   │
│                                                                 │
│  Developers see what would happen without real side effects.    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 14. Deeper reading

The `executor/` subfolder contains the long-form material this overview is
distilled from:

| Document | What it covers |
|----------|----------------|
| [executor/architecture.md](executor/architecture.md) | Internal four-layer architecture, gateway pipeline, adapter pattern, registry, why workflows live above the Executor |
| [executor/security-model.md](executor/security-model.md) | The prevention-first philosophy, the three-tier execution model, sandbox templates as safety net, why rich adapters reduce attack surface |
| [executor/why-foundation.md](executor/why-foundation.md) | The structural argument that the Executor — not Guardian — is the foundation of agent safety |
| [executor/standalone-product.md](executor/standalone-product.md) | The Executor as a novel piece of infrastructure, the gap in the current ecosystem, comparison to MCP / Composio / n8n / Open Interpreter |

Implementation references (in the codebase, not in `docs/`):

- [`executor/plan.md`](../executor/plan.md) — full implementation plan with module design
- [`executor/sandbox.md`](../executor/sandbox.md) — kernel sandbox implementation reference

Related public docs:

- [architecture.md](architecture.md) — the full pipeline (agent → actor → AE → Guardian → Executor)
- [processes.md](processes.md) — what processes actually run on your machine and which one the Executor is
- [privacy.md](privacy.md) — what data the Executor stores on disk and what (doesn't) leave the machine
- [threat-model.md](threat-model.md) — what's in scope and out of scope
- [principles.md](principles.md) — the invariants behind the design
- [root_demo/executor-root-mode.md](root_demo/executor-root-mode.md) — root execution model used in the root demo
- [vfs-vs-host-tools.md](vfs-vs-host-tools.md) — workspace VFS vs host filesystem tools
