# IntentFrame Executor: System Design & Architecture Plan

> "The Hands" -- A Standalone, Protocol-Driven Capability Service

---

## Part 1: Design Philosophy

**The Executor is not a workflow engine. It's an OS Capability Bridge.**

```
Traditional thinking:  Executor = Workflow Engine + Retry + Saga + Audit
Correct thinking:      Executor = OS Native API Router + Thin Orchestration Glue
```

**The Executor is a standalone, process-isolated service.**

It runs in its own process. Communication happens exclusively through validated,
supported protocols (gRPC, REST, Unix socket) and secure channels. Nothing reaches
the executor except through a formal contract. This is true whether it runs on a
consumer device or in the cloud -- the fundamentals don't change per deployment.

```
The Executor does NOT know or care:
  • WHO is calling it (Guardian, CI/CD pipeline, admin tool, test harness)
  • WHERE the caller runs (local, cloud, another device)
  • WHY the caller wants the action (business logic is the caller's problem)

The Executor ONLY cares:
  • Was the request received through a supported transport protocol?
  • Does the request carry valid authorization proof?
  • Does the request conform to the supported schema and action types?
  • Can the requested action be executed with available capabilities?
```

**Guardian is one protocol implementation, not a hardwired dependency.**

In IntentFrame's pipeline, Guardian is the primary (and initially, the only) system
that sends authorized execution requests. But the executor is not coupled to Guardian.
It's coupled to a **contract**: "Present valid authorization through a supported
protocol, and I'll execute." Guardian happens to satisfy this contract. So could
any other authorized system that speaks the same protocol and presents valid proof.

```
Analogy:
  • PostgreSQL doesn't care if you're pgAdmin or SQLAlchemy -- valid credentials + valid SQL
  • Kubernetes doesn't care if you're kubectl or ArgoCD -- valid kubeconfig
  • OS kernel doesn't care which app makes a syscall -- valid permission bits
  • Executor doesn't care who sends the request -- valid auth proof + valid schema
```

**Four rules:**
1. If the host OS already provides it, use it (Keychain, SQLite, EventKit, AppleScript, launchd)
2. If an OSS library wraps it cleanly, use the library (pyobjc, keyring, Tenacity)
3. Only write custom code for the **routing + glue** between these pieces
4. Design once, deploy anywhere -- the same executor core runs on device and cloud;
   only the transport layer, credential backend, and available adapters change

**Core invariant from IntentFrame architecture:**

> "No single entity can: Think + Judge + Act.
> Agent Thinks. Guardian Judges. Executor Acts."

The Executor can ACT but cannot JUDGE. It executes what authorized callers approve.
It does not question the wisdom of decisions -- that's the caller's job.

---

## Part 2: Executor as a Service

The Executor is a **standalone service** that runs in its own isolated process.
It exposes a well-defined API through supported transport protocols. Any system
that presents valid authorization proof and a well-formed request can use it.

```
┌─────────────────────────────────────────────────────────────────────┐
│  EXECUTOR: A STANDALONE CAPABILITY SERVICE                          │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │  AUTHORIZED CALLERS (any system that speaks the protocol)     │ │
│  │                                                               │ │
│  │  IntentFrame Guardian ─────┐                                  │ │
│  │  CI/CD Pipeline ───────────┤                                  │ │
│  │  Admin Dashboard ──────────┤  All use the SAME protocol       │ │
│  │  Test Harness ─────────────┤  All present valid auth proof    │ │
│  │  Another AI Framework ─────┘  All get the SAME contract       │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                         │                                           │
│              ═══════════╤═══════════  PROTOCOL BOUNDARY              │
│                         │            (gRPC / REST / Unix Socket)     │
│                         ▼                                           │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │  EXECUTOR SERVICE (isolated process)                          │ │
│  │                                                               │ │
│  │  1. Validate transport protocol                               │ │
│  │  2. Verify authorization proof                                │ │
│  │  3. Validate request schema                                   │ │
│  │  4. Route to capability adapter                               │ │
│  │  5. Execute + audit + respond                                 │ │
│  │                                                               │ │
│  │  Doesn't know WHO called. Doesn't care.                       │ │
│  │  Only cares: valid proof + valid request + supported action.  │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

### How It Fits IntentFrame's Pipeline

IntentFrame is an **Operating System for Agency**. The Executor is the kernel's
device driver layer -- the only component that touches the real world. Guardian is
the **primary authorized caller**, but the executor itself is caller-agnostic.

```
┌─────────────────────────────────────────────────────────────────────┐
│  THE INTENTFRAME PIPELINE (one client of the Executor service)      │
│                                                                     │
│  Agent (brain in a jar, ZERO direct I/O)                            │
│    │                                                                │
│    │  Intent Frame: "I want to do X because Y"                      │
│    ▼                                                                │
│  Actor SDK → Analysis Engine (cloud) → Guardian (cloud)             │
│    │                                                                │
│    │  Validated Intent (with authorization proof)                    │
│    ▼                                                                │
│  Guardian (local) ══[ protocol boundary ]══► EXECUTOR SERVICE       │
│    │                                                                │
│    │  Touches the real world: files, email, calendar, APIs...       │
│    ▼                                                                │
│  ExecutionResult → back through protocol → back to Agent            │
│                                                                     │
│  KEY: Agent NEVER touches the OS directly.                          │
│       Executor is the ONLY entity with credentials and real access. │
│       Everything is audited. Everything is reversible where possible.│
│       Guardian is one authorized caller -- the protocol is the gate.│
└─────────────────────────────────────────────────────────────────────┘
```

### Design Once, Deploy Anywhere

The executor's core is deployment-agnostic. Only three things change per deployment:

```
┌──────────────────────┬──────────────────────┬──────────────────────┐
│  WHAT CHANGES         │  ON DEVICE (macOS)   │  ON CLOUD            │
├──────────────────────┼──────────────────────┼──────────────────────┤
│  Transport protocol   │  Unix domain socket  │  gRPC / REST         │
│  Credential backend   │  macOS Keychain      │  HashiCorp Vault     │
│  Available adapters   │  EventKit, Contacts, │  Cloud APIs, S3, SES │
│                      │  EDI, SQLite         │                      │
│  Lifecycle manager    │  launchd             │  Kubernetes / systemd│
├──────────────────────┼──────────────────────┼──────────────────────┤
│  WHAT DOESN'T CHANGE │                      │                      │
├──────────────────────┼──────────────────────┴──────────────────────┤
│  Gateway logic        │  Same: receive → verify → validate → route  │
│  Auth verification    │  Same interface, pluggable implementations  │
│  Adapter pattern      │  Same ABC, same execute/rollback contract   │
│  Audit trail          │  Same SQLite schema, same hash chain        │
│  Fail-closed          │  Same: any error → reject                   │
│  Credential isolation │  Same: creds never leave executor process   │
└──────────────────────┴─────────────────────────────────────────────┘
```

### OS Analogy

| OS Concept | Executor Equivalent |
|---|---|
| Kernel | Executor Gateway |
| Device drivers | Capability Adapters |
| Syscalls | Execution Requests (via protocol) |
| File descriptors | Virtual paths (MountPoints) |
| Keyring / Credential Manager | Pluggable credential backend (Keychain on Mac) |
| System log | SQLite audit trail with hash chain |
| Process supervisor | Pluggable lifecycle (launchd on Mac) |
| Auth module (PAM) | Authorization Verifier (Guardian impl on IntentFrame) |

---

## Part 3: High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  EXECUTOR SERVICE (standalone isolated process)                         │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  LAYER 1: TRANSPORT (pluggable -- how requests arrive)          │   │
│  │                                                                 │   │
│  │  ┌───────────────┐ ┌───────────────┐ ┌───────────────────────┐│   │
│  │  │ Unix Socket   │ │ gRPC Server   │ │ REST/HTTP Server      ││   │
│  │  │ (device)      │ │ (cloud/device)│ │ (cloud/admin)         ││   │
│  │  └───────────────┘ └───────────────┘ └───────────────────────┘│   │
│  │  Only ONE active per deployment. Selected at config time.      │   │
│  └──────────────────────────┬──────────────────────────────────────┘   │
│                              │ raw request                             │
│  ┌──────────────────────────▼──────────────────────────────────────┐   │
│  │  LAYER 2: EXECUTOR GATEWAY              [Main Process]          │   │
│  │                                                                 │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐     │   │
│  │  │ Request  │→│ Auth     │→│ Pydantic │→│ Action    │     │   │
│  │  │ Parser   │  │ Verifier │  │ Validator│  │ Router    │     │   │
│  │  │          │  │(pluggable│  │          │  │ (Dispatch)│     │   │
│  │  │          │  │ impls)   │  │          │  │           │     │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └───────────┘     │   │
│  │       INVARIANT: Reject if auth invalid (fail-closed)          │   │
│  │                                                                 │   │
│  │  Auth Verifier implementations:                                 │   │
│  │    • GuardianSignatureVerifier (HMAC -- IntentFrame default)    │   │
│  │    • mTLSVerifier (mutual TLS -- cloud deployments)             │   │
│  │    • TokenVerifier (JWT/opaque -- admin/CI tools)               │   │
│  └──────────────────────────┬──────────────────────────────────────┘   │
│                              │ async dispatch                          │
│  ┌──────────────────────────▼──────────────────────────────────────┐   │
│  │  LAYER 3: CAPABILITY WORKER POOL         [Worker Processes]     │   │
│  │                                                                 │   │
│  │  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌──────────────┐  │   │
│  │  │ Mail      │ │ Calendar  │ │ Files     │ │ Browser     │  │   │
│  │  │(EDI      )│ │(EventKit) │ │ (VFS +   │ │(subprocess  │  │   │
│  │  │           │ │           │ │  pathlib) │ │ + httpx)    │  │   │
│  │  └───────────┘ └───────────┘ └───────────┘ └──────────────┘  │   │
│  │  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌──────────────┐  │   │
│  │  │ Contacts  │ │ Notes     │ │ Terminal  │ │ HTTP/API    │  │   │
│  │  │(Contacts  │ │(SQLite +  │ │ (asyncio) │ │ (httpx)     │  │   │
│  │  │ framework)│ │ osascript)│ │           │ │             │  │   │
│  │  └───────────┘ └───────────┘ └───────────┘ └──────────────┘  │   │
│  │  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌──────────────┐  │   │
│  │  │ Messages  │ │ Reminders │ │ Shortcuts │ │ System      │  │   │
│  │  │(SQLite +  │ │(EventKit) │ │ (CLI)     │ │(osascript)  │  │   │
│  │  │ osascript)│ │           │ │           │ │             │  │   │
│  │  └───────────┘ └───────────┘ └───────────┘ └──────────────┘  │   │
│  │  ┌───────────┐ ┌───────────┐ ┌───────────┐                   │   │
│  │  │ UserIO    │ │ Clipboard │ │ Spotlight │                   │   │
│  │  │(osascript)│ │(osascript)│ │(osascript)│                   │   │
│  │  └───────────┘ └───────────┘ └───────────┘                   │   │
│  │  (Adapters are also pluggable per deployment -- macOS adapters │   │
│  │   shown above; cloud adapters would be S3, SES, etc.)          │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                              │                                         │
│  ┌──────────────────────────▼──────────────────────────────────────┐   │
│  │  LAYER 4: SHARED SERVICES (in-process, accessed via module)     │   │
│  │                                                                 │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐  │   │
│  │  │ Credential   │  │ Audit        │  │ State               │  │   │
│  │  │ Vault        │  │ Logger       │  │ Store               │  │   │
│  │  │ (pluggable:  │  │ (structlog + │  │ (SQLite)            │  │   │
│  │  │  keyring on  │  │  SQLite)     │  │                     │  │   │
│  │  │  Mac, Vault  │  │              │  │                     │  │   │
│  │  │  on cloud)   │  │              │  │                     │  │   │
│  │  └──────────────┘  └──────────────┘  └─────────────────────┘  │   │
│  │  ┌──────────────┐  ┌──────────────┐                            │   │
│  │  │ Virtual      │  │ Credential   │                            │   │
│  │  │ FileSystem   │  │ Scrubber     │                            │   │
│  │  │ (MountPoints)│  │ (for audit)  │                            │   │
│  │  └──────────────┘  └──────────────┘                            │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  LIFECYCLE: Pluggable (launchd on Mac, systemd on Linux, K8s on cloud) │
│  STORAGE:   ~/Library/Application Support/IntentFrame/ (on Mac)        │
│  LOGS:      ~/Library/Logs/IntentFrame/ (on Mac)                       │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Part 4: Process Model

**Two-process architecture** (simple, reliable, portable):

### Process 1: Executor Gateway (always running)
- Listens for execution requests via configured transport protocol
- **Verifies authorization proof** (INVARIANT -- reject if invalid, fail-closed)
- Validates request structure (Pydantic)
- Dispatches to correct capability adapter
- Manages concurrency (asyncio event loop)
- Aggregates results, returns to caller through same protocol

### Process 2: Capability Worker Pool (on-demand)
- Spawned via `ProcessPoolExecutor` (Python stdlib)
- Isolates capability execution from gateway
- If a capability crashes, gateway survives
- Pool size configurable (default: 4 workers)

### Transport Protocol Selection

The gateway accepts requests through exactly ONE transport protocol, selected
at startup via configuration:

```
┌──────────────────────┬────────────────────────────────────────────────┐
│  TRANSPORT            │  WHEN TO USE                                  │
├──────────────────────┼────────────────────────────────────────────────┤
│  Unix Domain Socket   │  Same-machine IPC (default for device deploy) │
│  gRPC                 │  Cross-machine, high-perf (cloud/device)      │
│  REST/HTTP            │  Admin tools, debugging, cloud (simple/broad) │
└──────────────────────┴────────────────────────────────────────────────┘
```

All transports produce the same internal `ExecutionRequest` after parsing.
The gateway doesn't know or care which transport delivered the request.

**Why not more processes?** Because:
- The host OS already isolates credential access per-app (Keychain on Mac)
- SQLite handles concurrent writes with WAL mode
- More processes = more complexity for zero benefit on desktop
- The process boundary is for **crash isolation**, not security boundaries

---

## Part 5: Security Invariants

These are non-negotiable properties the Executor MUST enforce at all times.
They come directly from IntentFrame's core architecture documents.

### Invariant 1: Fail-Closed

> Any failure, timeout, ambiguity, or error results in rejection -- NEVER silent approval.

```
Gateway cannot parse intent              → REJECT (return ExecutionResult success=false)
Guardian signature invalid               → REJECT (do not execute, log attempt)
Adapter throws exception                 → REJECT (catch, log, return failure)
Adapter hangs past timeout               → REJECT (kill worker, return timeout error)
Keychain access denied                   → REJECT (do not execute without credentials)
Framework access denied (TCC)            → REJECT (permission not granted, return error)
Unknown action type                      → REJECT (no default/fallback execution)
Worker process crashes                   → REJECT (gateway survives, returns failure)

NEVER: Silent approval, assumed success, fail-open, default-allow
```

The base adapter enforces this with a mandatory timeout wrapper around every
`execute()` call. If the adapter doesn't return within the timeout, the gateway
cancels it and returns failure.

### Invariant 2: Authorization Proof Required

Every request arriving at the Executor MUST carry valid authorization proof.
Without this, any process on the machine (or network) could spoof requests
directly to the executor. The authorization verifier is **pluggable** --
Guardian's HMAC signature is one implementation, not the only one.

```
Request arrives at transport layer
  │
  ▼
Parse according to transport protocol
  │
  ▼
Verify authorization proof (via configured AuthVerifier)
  │
  ├── VALID   → proceed to Pydantic validation → route to adapter
  └── INVALID → REJECT immediately, log the attempt as security event

AuthVerifier is an interface:
  • GuardianSignatureVerifier  -- verifies HMAC token from Cloud Guardian
  • mTLSVerifier               -- verifies mutual TLS certificate
  • TokenVerifier              -- verifies JWT or opaque bearer token
  • (future implementations)   -- any system that can prove authorization
```

In IntentFrame's deployment, the default verifier is `GuardianSignatureVerifier`.
This is the trust boundary between "conditionally trusted" local Guardian
and "trusted" Executor. But the executor itself doesn't know it's "Guardian" --
it just sees a valid (or invalid) authorization proof.

### Invariant 3: Credentials Never Leave Executor

```
Credentials NEVER leave Executor process
Credentials NEVER exposed to other layers
Credentials NEVER logged or transmitted
Credentials NEVER included in audit entries (params are hashed, not stored)
```

The audit logger enforces this by accepting ONLY pre-scrubbed data.
The credential vault provides credentials directly to adapters in-process;
they are never serialized, never passed over the socket, never written to disk
outside of macOS Keychain.

### Invariant 4: Virtual Paths Only

Agents operate in a sandboxed virtual filesystem. They see `/invoices/` not
`/Users/john/Documents/finance/invoices/`. The Executor's files adapter resolves
virtual paths to real paths via MountPoints. This prevents:

- Path traversal attacks (`../../../etc/passwd`)
- Information leakage (agent learning OS, username, directory structure)
- Escape from allowed boundaries

The existing MountPoint system from `demo/data_structures.py` and
`demo/resources/file_system.py` is carried forward into the production executor.

---

## Part 6: Complete Technology Stack

### Layer-by-Layer (Everything OSS or Built-in)

```
┌──────────────────────┬───────────────────────────────┬──────────────┐
│  CONCERN             │  OSS / BUILT-IN SOLUTION      │  CUSTOM CODE │
├──────────────────────┼───────────────────────────────┼──────────────┤
│                      │                               │              │
│  ── TRANSPORT ───────│───────────────────────────────│──────────────│
│  Transport Layer     │  Pluggable (one active):      │  Interface + │
│                      │    Unix socket (stdlib)        │  ~40 lines   │
│                      │    gRPC (grpcio)               │  per impl    │
│                      │    REST (uvicorn + starlette)  │              │
│  Auth Verification   │  Pluggable (one active):      │  Interface + │
│                      │    HMAC/hashlib (stdlib)       │  ~30 lines   │
│                      │    mTLS (ssl stdlib)           │  per impl    │
│                      │    JWT (PyJWT)                 │              │
│                      │                               │              │
│  ── GATEWAY ─────────│───────────────────────────────│──────────────│
│  Request Validation  │  Pydantic v2                  │  Models only │
│  Action Routing      │  Python dict dispatch         │  ~50 lines   │
│  Concurrency         │  asyncio + ProcessPoolExecutor│  ~30 lines   │
│  Lifecycle Mgmt      │  Pluggable:                   │  Config file │
│                      │    launchd (macOS)             │              │
│                      │    systemd (Linux)             │              │
│                      │    Kubernetes (cloud)          │              │
│                      │                               │              │
│  ── CAPABILITIES ────│───────────────────────────────│──────────────│
│  Calendar            │  EventKit (pyobjc)            │  Adapter     │
│  Reminders           │  EventKit (pyobjc)            │  Adapter     │
│  Contacts            │  Contacts framework (pyobjc)  │  Adapter     │
│  Mail                │  EDI EmailClient              │  Adapter     │
│  Notes               │  SQLite reads + osascript     │  Adapter     │
│  Messages            │  SQLite reads + osascript     │  Adapter     │
│  Files/Finder        │  VFS (MountPoints) + pathlib  │  Adapter     │
│  Browser             │  subprocess `open` + httpx    │  Adapter     │
│  Terminal/Shell      │  asyncio.subprocess (stdlib)  │  Adapter     │
│  HTTP/API calls      │  httpx                        │  Adapter     │
│  Shortcuts           │  subprocess → shortcuts CLI   │  Adapter     │
│  System Settings     │  osascript (subprocess)       │  Adapter     │
│  Clipboard           │  osascript (subprocess)       │  Adapter     │
│  Notifications       │  osascript (subprocess)       │  Adapter     │
│  Spotlight Search    │  osascript (subprocess)       │  Adapter     │
│  Filesystem Watch    │  watchdog                     │  Config only │
│  UserIO              │  osascript (subprocess)       │  Adapter     │
│  (macOS adapters shown; cloud adapters would be different set)      │
│                      │                               │              │
│  ── CROSS-CUTTING ───│───────────────────────────────│──────────────│
│  Credentials         │  Pluggable:                   │  Interface   │
│                      │    keyring → Keychain (macOS)  │              │
│                      │    HashiCorp Vault (cloud)     │              │
│  Credential Scrubbing│  Custom scrubber for audit    │  ~20 lines   │
│  Retry / Resilience  │  Tenacity                     │  Decorators  │
│  Timeout Enforcement │  asyncio.wait_for (stdlib)    │  In base.py  │
│  Audit Logging       │  structlog + SQLite (stdlib)  │  Schema only │
│  State Persistence   │  SQLite WAL mode (stdlib)     │  Schema only │
│  Data Validation     │  Pydantic v2                  │  Models only │
│  Serialization       │  JSON (stdlib)                │  None        │
│  Error Handling      │  Python exceptions + Tenacity │  Patterns    │
│  Rollback Tracking   │  SQLite state table           │  ~60 lines   │
│  Virtual FileSystem  │  MountPoint resolver          │  ~80 lines   │
└──────────────────────┴───────────────────────────────┴──────────────┘
```

---

## Part 7: Module Design (The Capability Adapter Pattern)

Every capability follows the **exact same pattern**. This is the only "framework"
code you write:

```python
# This is the ENTIRE pattern. Every capability is an adapter.

from abc import ABC, abstractmethod
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

class ExecutionResult(BaseModel):
    success: bool
    data: dict | None = None
    error: str | None = None
    rollback_available: bool = False
    rollback_id: str | None = None

class CapabilityAdapter(ABC):
    """Base class - every capability implements this.

    The gateway wraps every execute() call with:
    - asyncio.wait_for(timeout=ADAPTER_TIMEOUT)
    - try/except catching ALL exceptions
    - On any failure or timeout → ExecutionResult(success=False)
    This enforces fail-closed at the framework level.
    Caller identity is irrelevant -- the gateway already verified auth.
    """

    @abstractmethod
    async def execute(self, action: str, params: dict,
                      credentials: dict | None = None) -> ExecutionResult:
        """Do the thing."""
        ...

    @abstractmethod
    async def rollback(self, rollback_id: str) -> ExecutionResult:
        """Undo the thing (if possible)."""
        ...

    @abstractmethod
    def supported_actions(self) -> list[str]:
        """What actions does this adapter handle?"""
        ...
```

Then each adapter is concise because native frameworks / stdlib do the real work:

```python
# Example: Mail adapter (EDI EmailClient — no GUI app launch, no credential handling)

class MailAdapter(CapabilityAdapter):

    def supported_actions(self):
        return [
            "SEND_EMAIL", "READ_EMAIL", "SEARCH_EMAIL", "GET_EMAIL",
            "REPLY_EMAIL", "FORWARD_EMAIL", "MARK_READ_EMAIL",
            "MOVE_EMAIL", "DELETE_EMAIL", "DOWNLOAD_ATTACHMENT",
        ]

    async def execute(self, action, params, credentials=None):
        client = EmailClient()
        if action == "SEND_EMAIL":
            result = await client.send(
                params["account_email"], to=params["to"],
                subject=params["subject"], body=params["body"],
            )
            return ExecutionResult(success=result.success)

        if action == "READ_EMAIL":
            emails = await client.get_recent(params["account_email"], limit=20)
            return ExecutionResult(success=True, data={"emails": [...]})
        # ... dispatch to other actions ...

    async def rollback(self, rollback_id):
        return ExecutionResult(success=False, error="Email actions are irreversible")
```

```python
# Example: Files adapter -- uses Virtual FileSystem (MountPoints)

class FilesAdapter(CapabilityAdapter):
    """File operations use Virtual FileSystem.
    Agents see virtual paths (/invoices/), never real paths.
    MountPoint resolver maps virtual → real.
    """

    def __init__(self, vfs: VirtualFileSystem):
        self._vfs = vfs  # MountPoint-based resolver

    def supported_actions(self):
        return ["LIST_DIRECTORY", "READ_FILE", "WRITE_FILE", "APPEND_ROW",
                "DELETE_FILE"]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential())
    async def execute(self, action, params, credentials=None):
        if action == "LIST_DIRECTORY":
            files = self._vfs.list_directory(params["path"])
            return ExecutionResult(success=True, data={"files": files})

        if action == "READ_FILE":
            content = self._vfs.read_file(params["path"])
            return ExecutionResult(success=True, data={"content": content})

        # ... virtual paths resolved by VFS, agent never sees real paths

    async def rollback(self, rollback_id):
        # File rollback via state store checkpoint
        ...
```

```python
# Example: UserIO adapter -- user interaction is just another resource

class UserIOAdapter(CapabilityAdapter):
    """UserIOService is a PROTECTED RESOURCE, not a special channel.
    ASK_USER, SHOW_MESSAGE, GET_CONFIRMATION all go through the caller's
    validation pipeline. In IntentFrame, Guardian validates the PROMPT is
    safe (not phishing) before the authorized request reaches Executor.
    """

    def supported_actions(self):
        return ["ASK_USER", "SHOW_MESSAGE", "GET_CONFIRMATION", "SHOW_OPTIONS"]

    async def execute(self, action, params, credentials=None):
        if action == "ASK_USER":
            # Render via native macOS dialog / Superagent UI
            response = await self._show_dialog(
                prompt=params["prompt"],
                options=params.get("options", [])
            )
            return ExecutionResult(success=True, data={"response": response})

        if action == "SHOW_MESSAGE":
            await self._show_notification(params["message"])
            return ExecutionResult(success=True)

    async def rollback(self, rollback_id):
        return ExecutionResult(success=False, error="User interaction is irreversible")
```

**Every new capability = one new file, ~50-150 lines, using native frameworks or stdlib.**

---

## Part 8: Concurrency Model

```
┌─────────────────────────────────────────────────────────────────────┐
│  CONCURRENCY ARCHITECTURE                                           │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │  asyncio Event Loop (Gateway Process)                         │ │
│  │                                                               │ │
│  │  Incoming intents are received as async tasks.                │ │
│  │  Multiple intents can be in-flight simultaneously.            │ │
│  │  The event loop is NEVER blocked.                             │ │
│  │                                                               │ │
│  │  Intent A ──→ [verify sig] → [validate] → [dispatch] → [log] │ │
│  │  Intent B ──→ [verify sig] → [validate] → [dispatch] → [log] │ │
│  │  Intent C ──→ [verify sig] → [validate] → [dispatch] → [log] │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                              │                                      │
│                 asyncio.run_in_executor()                           │
│                              │                                      │
│  ┌───────────────────────────▼───────────────────────────────────┐ │
│  │  ProcessPoolExecutor (4 workers)                              │ │
│  │                                                               │ │
│  │  Worker 1: [Mail: SEND_EMAIL]         ← CPU/IO isolated      │ │
│  │  Worker 2: [Calendar: CREATE_EVENT]   ← crash-isolated       │ │
│  │  Worker 3: [Files: READ_FILE]         ← concurrent           │ │
│  │  Worker 4: [idle, waiting]            ← scales down           │ │
│  │                                                               │ │
│  │  Each worker has ADAPTER_TIMEOUT enforced by gateway.         │ │
│  │  If worker hangs → cancelled → failure returned.              │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  WHY THIS MODEL:                                                    │
│  - asyncio = free concurrency for I/O (no threads needed)           │
│  - ProcessPool = crash isolation (worker dies, gateway lives)       │
│  - 4 workers = sane default for consumer Mac (configurable)         │
│  - Zero external dependencies (all Python stdlib)                   │
│  - Timeout enforcement = fail-closed guarantee                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Part 9: Data Flow (End-to-End)

```
Authorized Caller ──execution request + auth proof──→ Transport Layer
                                                           │
                                                    Protocol-specific
                                                    (socket/gRPC/REST)
                                                           │
                                                           ▼
┌────────────────────────── EXECUTOR GATEWAY ──────────────────────────┐
│                                                                      │
│  1. RECEIVE       │ Read execution request from transport            │
│                   │ Deserialize to internal format                   │
│                   │ OSS: transport-specific (json/protobuf/etc.)     │
│                   ▼                                                  │
│  2. VERIFY AUTH   │ Verify authorization proof (via AuthVerifier)    │
│                   │ INVARIANT: Invalid → REJECT immediately          │
│                   │ Log rejected attempts as security events         │
│                   │ OSS: hmac/ssl/PyJWT (depends on verifier impl)  │
│                   ▼                                                  │
│  3. VALIDATE      │ Validate structure (fields, types, required)     │
│                   │ OSS: Pydantic v2 (automatic)                     │
│                   ▼                                                  │
│  4. LOG START     │ Write "EXECUTION_STARTED" to audit log           │
│                   │ Params are HASHED, not stored raw                │
│                   │ Credentials are SCRUBBED before logging          │
│                   │ OSS: structlog → SQLite                          │
│                   ▼                                                  │
│  5. ROUTE         │ Map action_type → CapabilityAdapter              │
│                   │ Unknown action → REJECT (fail-closed)            │
│                   │ CUSTOM: ~20 line dispatch dict                    │
│                   ▼                                                  │
│  6. CREDENTIAL    │ If adapter needs creds, fetch from vault         │
│                   │ Creds passed in-process, NEVER serialized        │
│                   │ OSS: keyring/vault (depends on cred backend)     │
│                   ▼                                                  │
│  7. EXECUTE       │ Run adapter.execute() in worker process          │
│                   │ Wrapped in asyncio.wait_for(timeout=...)         │
│                   │ Wrapped in try/except (catch ALL exceptions)     │
│                   │ Any failure or timeout → ExecutionResult(fail)   │
│                   │ OSS: ProcessPoolExecutor + adapters + Tenacity   │
│                   ▼                                                  │
│  8. ROLLBACK?     │ If success + rollback_available → save to        │
│                   │   rollback_registry for future undo              │
│                   │ If failed + partial state → attempt cleanup      │
│                   │ OSS: SQLite state table                          │
│                   ▼                                                  │
│  9. LOG END       │ Write "EXECUTION_COMPLETED/FAILED" to audit      │
│                   │ Include: duration, result hash, hash chain        │
│                   │ OSS: structlog → SQLite                          │
│                   ▼                                                  │
│  10. RESPOND      │ Return ExecutionResult to caller                 │
│                   │ OSS: Pydantic serialization → transport protocol │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘

IntentFrame example: Guardian (cloud) → Guardian (local) → Unix Socket → Executor
CI/CD example:       Pipeline system → gRPC → Executor
Admin example:       Dashboard → REST API → Executor
```

---

## Part 10: Storage Design (All SQLite, Already on Every Mac)

**Single SQLite database** with WAL mode (concurrent reads + writes):

```
~/Library/Application Support/IntentFrame/executor.db

Tables:
┌─────────────────────────────────────────────────────────────────┐
│  audit_log                                                       │
│  ├── id              INTEGER PRIMARY KEY                         │
│  ├── execution_id    TEXT UNIQUE                                  │
│  ├── intent_frame_id TEXT                                         │
│  ├── action_type     TEXT                                         │
│  ├── adapter         TEXT                                         │
│  ├── status          TEXT  (STARTED/COMPLETED/FAILED/ROLLEDBACK) │
│  ├── params_hash     TEXT  (SHA-256 of params, NOT raw params)   │
│  ├── result_summary  TEXT  (scrubbed of any credential data)     │
│  ├── error           TEXT                                         │
│  ├── duration_ms     INTEGER                                      │
│  ├── timestamp       TEXT  (ISO 8601)                             │
│  ├── prev_hash       TEXT  (hash chain → immutability)            │
│  └── entry_hash      TEXT  (SHA-256 of this row + prev_hash)     │
├─────────────────────────────────────────────────────────────────┤
│  rollback_registry                                               │
│  ├── id              INTEGER PRIMARY KEY                         │
│  ├── execution_id    TEXT                                         │
│  ├── rollback_id     TEXT                                         │
│  ├── adapter         TEXT                                         │
│  ├── rollback_data   TEXT  (JSON - what to undo)                 │
│  ├── expires_at      TEXT                                         │
│  ├── status          TEXT  (AVAILABLE/EXECUTED/EXPIRED)           │
│  └── created_at      TEXT                                         │
├─────────────────────────────────────────────────────────────────┤
│  execution_state                                                 │
│  ├── id              INTEGER PRIMARY KEY                         │
│  ├── execution_id    TEXT UNIQUE                                  │
│  ├── status          TEXT                                         │
│  ├── checkpoint      TEXT  (JSON - resumption data)              │
│  ├── attempts        INTEGER                                      │
│  └── updated_at      TEXT                                         │
├─────────────────────────────────────────────────────────────────┤
│  security_events     (NEW: tracks rejected/suspicious attempts)  │
│  ├── id              INTEGER PRIMARY KEY                         │
│  ├── event_type      TEXT  (INVALID_SIGNATURE/SPOOFED_INTENT/...) │
│  ├── source_info     TEXT  (what we know about the caller)       │
│  ├── details         TEXT  (scrubbed details of the attempt)     │
│  └── timestamp       TEXT  (ISO 8601)                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## Part 11: Lifecycle

The executor is a long-running process managed by the host OS's native supervisor.
The lifecycle is pluggable -- the executor doesn't care who starts or restarts it.

```
┌─────────────────────────────────────────────────────────────────┐
│  macOS DEVICE DEPLOYMENT (default)                               │
│                                                                  │
│  INSTALL:                                                        │
│    Drop .plist into ~/Library/LaunchAgents/                      │
│    com.intentframe.executor.plist                                │
│                                                                  │
│  AUTO-START:                                                     │
│    launchd starts executor on login (KeepAlive: true)            │
│    Restarts automatically if it crashes                          │
│    No Docker. No server. No startup scripts.                     │
│                                                                  │
│  CONFIG:                                                         │
│    ~/Library/Application Support/IntentFrame/executor.yaml       │
│    Specifies: transport=unix_socket, auth=guardian_hmac,          │
│               credential_backend=keyring, adapters=[macos set]   │
│                                                                  │
│  STORAGE:                                                        │
│    ~/Library/Application Support/IntentFrame/executor.db         │
│                                                                  │
│  LOGS:                                                           │
│    ~/Library/Logs/IntentFrame/executor.log                       │
│                                                                  │
│  CREDENTIALS:                                                    │
│    macOS Keychain (via keyring library)                          │
│    No .env files. No plaintext secrets. Ever.                    │
│                                                                  │
│  TRANSPORT:                                                      │
│    /tmp/intentframe/executor.sock                                │
│    (Unix domain socket for local IPC)                            │
│                                                                  │
│  PERMISSIONS:                                                    │
│    macOS will prompt user for:                                   │
│    - Contacts access (first use)                                 │
│    - Calendar access (first use)                                 │
│    - Mail access (first use)                                     │
│    - Automation permissions (first use per app)                  │
│    These are one-time. macOS handles this natively.              │
├─────────────────────────────────────────────────────────────────┤
│  CLOUD DEPLOYMENT (alternative)                                  │
│                                                                  │
│  SUPERVISOR: systemd / Kubernetes                                │
│  CONFIG:     executor.yaml mounted as config volume               │
│              transport=grpc, auth=mtls,                           │
│              credential_backend=vault, adapters=[cloud set]      │
│  TRANSPORT:  gRPC on port 50051 (or REST on 8080)                │
│  CREDENTIALS: HashiCorp Vault (or cloud KMS)                     │
│                                                                  │
│  Same binary. Same gateway. Same adapters pattern.               │
│  Different config file.                                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Part 12: Project Structure

```
intentframe/
└── executor/
    ├── main.py                      # Entry point -- config-driven startup (~40 lines)
    ├── gateway.py                   # Request handler: auth → validate → route → respond (~150 lines)
    ├── models.py                    # Pydantic models (~120 lines)
    ├── dispatch.py                  # Action → Adapter routing (~50 lines)
    ├── worker_pool.py               # ProcessPool management + timeout (~50 lines)
    │
    ├── transport/                   # Pluggable transport layer
    │   ├── base.py                  # TransportServer ABC (~30 lines)
    │   ├── unix_socket.py           # Unix domain socket impl (~60 lines)
    │   ├── grpc_server.py           # gRPC server impl (~80 lines)
    │   └── rest_server.py           # REST/HTTP server impl (~80 lines)
    │
    ├── auth/                        # Pluggable authorization verification
    │   ├── base.py                  # AuthVerifier ABC (~20 lines)
    │   ├── guardian_hmac.py         # Guardian HMAC signature verifier (~40 lines)
    │   ├── mtls.py                  # Mutual TLS cert verifier (~40 lines)
    │   └── token.py                 # JWT / bearer token verifier (~40 lines)
    │
    ├── adapters/                    # One file per capability (18 adapters)
    │   ├── base.py                  # CapabilityAdapter ABC + timeout wrapper (~50 lines)
    │   ├── _eventkit.py             # Shared EventKit store + TCC access (~120 lines)
    │   ├── calendar.py              # EventKit framework (~230 lines)
    │   ├── reminders.py             # EventKit framework (~245 lines)
    │   ├── contacts.py              # Contacts framework (~265 lines)
    │   ├── mail.py                  # EDI EmailClient (~390 lines)
    │   ├── notes.py                 # SQLite reads + osascript writes (~280 lines)
    │   ├── messages.py              # SQLite reads + osascript writes (~205 lines)
    │   ├── files.py                 # VFS (MountPoints) + pathlib (~100 lines)
    │   ├── browser.py               # subprocess `open` + httpx (~115 lines)
    │   ├── terminal.py              # asyncio.subprocess (~60 lines)
    │   ├── http_api.py              # httpx for REST APIs (~70 lines)
    │   ├── shortcuts.py             # subprocess → shortcuts CLI (~40 lines)
    │   ├── system.py                # osascript subprocess (~105 lines)
    │   ├── clipboard.py             # osascript subprocess (~40 lines)
    │   ├── notifications.py         # osascript subprocess (~30 lines)
    │   ├── spotlight.py             # osascript subprocess (~40 lines)
    │   ├── filesystem_watch.py      # watchdog (~50 lines)
    │   └── user_io.py               # osascript subprocess (~80 lines)
    │
    ├── services/                    # Cross-cutting concerns
    │   ├── credential_vault.py      # Credential backend interface + keyring impl (~60 lines)
    │   ├── credential_scrubber.py   # Scrub creds before audit logging (~20 lines)
    │   ├── audit_logger.py          # structlog + SQLite (~70 lines)
    │   ├── state_store.py           # SQLite state/rollback (~80 lines)
    │   ├── hash_chain.py            # SHA-256 chain for audit (~30 lines)
    │   └── virtual_filesystem.py    # MountPoint resolver (~80 lines)
    │
    ├── config/
    │   ├── executor.yaml            # Main config: transport, auth, adapters, cred backend
    │   └── com.intentframe.executor.plist  # macOS launchd config (device deploy)
    │
    └── requirements.txt             # Dependencies
```

---

## Part 13: Dependencies (The Complete List)

```
# requirements.txt - EVERYTHING the executor needs

# ── CORE (always installed) ──────────────────────────────────────────

# Data validation & serialization
pydantic>=2.0            # Request/response validation

# Resilience
tenacity>=9.0.0          # Retry with backoff

# Logging
structlog>=25.0.0        # Structured audit logging

# HTTP client (used by adapters + REST transport)
httpx>=0.27.0            # Async HTTP client

# ── TRANSPORT (install per deployment) ───────────────────────────────

# Unix socket transport: no extra deps (stdlib socket)
# gRPC transport:
# grpcio>=1.60.0         # gRPC server
# grpcio-tools>=1.60.0   # Protobuf compilation
# REST transport:
# uvicorn>=0.30.0        # ASGI server
# starlette>=0.40.0      # Lightweight HTTP framework

# ── AUTH (install per deployment) ────────────────────────────────────

# Guardian HMAC: no extra deps (stdlib hmac + hashlib)
# JWT auth:
# PyJWT>=2.8.0           # JWT token verification
# mTLS auth: no extra deps (stdlib ssl)

# ── macOS DEVICE ADAPTERS (install for device deployment) ────────────

pyobjc-framework-EventKit>=11.0  # Calendar & Reminders (EventKit framework)
pyobjc-framework-Contacts>=11.0  # Contacts (Contacts framework)
keyring>=25.0.0                  # macOS Keychain access
watchdog>=4.0.0                  # Cross-platform fs events

# ── PYTHON STDLIB (no install needed) ────────────────────────────────

# sqlite3                # Database
# asyncio                # Concurrency
# multiprocessing        # Process pool
# json                   # Serialization
# hashlib                # SHA-256 for audit chain
# hmac                   # HMAC for Guardian auth verifier
# ssl                    # mTLS for cert auth verifier
# pathlib                # File paths
# subprocess             # Shell/CLI execution
# socket                 # Unix domain sockets
```

**Core: 4 pip packages (always). Transport + Auth + Adapters: varies by deployment.**
**macOS device deployment: 4 core + 4 macOS = 8 pip packages total.**
**(pyobjc-core and pyobjc-framework-Cocoa are transitive deps of EventKit/Contacts)**

---

## Part 14: What's Custom vs What's OSS

| What | Lines | Source |
|---|---|---|
| Gateway (receive + verify auth + route + respond) | ~150 | **Custom** |
| Pydantic models (Request, Result, etc.) | ~120 | **Custom** (Pydantic does validation) |
| Transport layer (ABC + Unix socket impl) | ~90 | **Custom** (stdlib does the work) |
| Auth verifier (ABC + Guardian HMAC impl) | ~60 | **Custom** (stdlib does the work) |
| Dispatch table (action → adapter) | ~50 | **Custom** |
| Worker pool management + timeout wrapper | ~50 | **Custom** (stdlib does the work) |
| Base adapter (ABC + fail-closed enforcement) | ~50 | **Custom** |
| Each adapter (avg ~120 lines x 18) | ~2160 | **Custom** (native frameworks do the work) |
| Virtual FileSystem (MountPoint resolver) | ~80 | **Custom** (extends demo) |
| Audit logger + hash chain + credential scrubber | ~120 | **Custom** (structlog + sqlite) |
| State store + rollback registry | ~80 | **Custom** (sqlite does the work) |
| Credential vault interface + keyring impl | ~60 | **Custom** (keyring does the work) |
| Config loader (YAML → runtime config) | ~40 | **Custom** |
| **TOTAL CUSTOM CODE** | **~2,030** | |
| | | |
| pyobjc (EventKit, Contacts, Foundation) | 10,000+ | **OSS** |
| Pydantic (validation engine) | 50,000+ | **OSS** |
| Tenacity (retry engine) | 2,000+ | **OSS** |
| structlog (logging engine) | 5,000+ | **OSS** |
| httpx (HTTP client) | 20,000+ | **OSS** |
| keyring (credential mgmt) | 3,000+ | **OSS** |
| watchdog (fs monitoring) | 8,000+ | **OSS** |
| SQLite (database) | 150,000+ | **Built-in** |
| asyncio (concurrency) | 20,000+ | **Built into Python** |
| launchd / systemd (lifecycle) | N/A | **Built into OS** |
| Keychain / Vault (credential storage) | N/A | **Built-in / OSS** |
| **TOTAL OSS/BUILT-IN** | **~270,000+** | |

**Ratio: ~2,030 lines custom vs ~270,000 lines of OSS/built-in. Less than 0.8% custom code.**

The ~230 extra lines (vs the previous ~1,800) come from the transport and auth
abstraction layers. This is the cost of making the executor deployment-agnostic --
a one-time investment that pays off in every new transport or auth verifier being
a single ~40-80 line file with no changes to the core.

---

## Part 15: Implementation Order

Build in 10 phases. Each phase is independently testable.

1. **Foundation** - `models.py` (Pydantic models for ExecutionRequest, ExecutionResult, etc.), `adapters/base.py` (CapabilityAdapter ABC with timeout + fail-closed), `main.py` entry point, extend ActionType enum, `config/executor.yaml` schema
2. **Transport + Auth abstractions** - `transport/base.py` (TransportServer ABC), `auth/base.py` (AuthVerifier ABC), `transport/unix_socket.py` (first impl), `auth/guardian_hmac.py` (first impl) -- these are the protocol boundary
3. **Services** - `audit_logger.py`, `state_store.py`, `credential_vault.py` (interface + keyring impl), `credential_scrubber.py`, `hash_chain.py`, `virtual_filesystem.py` (MountPoint resolver)
4. **Gateway** - `gateway.py` (transport-agnostic request handler: auth → validate → route → respond), `dispatch.py`, `worker_pool.py`
5. **Core adapters** - `files.py` (VFS-backed), `terminal.py`, `http_api.py`, `user_io.py` (easiest to test, covers most demo use cases)
6. **Communication adapters** - `mail.py`, `messages.py`, `notifications.py` (require macOS permissions on first use)
7. **PIM adapters** - `calendar.py`, `contacts.py`, `notes.py`, `reminders.py`
8. **System adapters** - `browser.py`, `system.py`, `clipboard.py`, `shortcuts.py`, `spotlight.py`
9. **Filesystem watch adapter** - `filesystem_watch.py` (watchdog)
10. **Lifecycle & Integration** - launchd `.plist` (macOS), `executor.yaml` profiles (device/cloud), integration with existing `IntentFrameRuntime` as drop-in replacement for demo executor, additional transport impls (gRPC, REST) as needed

Each adapter can be developed and tested in isolation.
Each transport and auth verifier can be developed and tested in isolation.
The gateway doesn't change when you add a new transport, auth verifier, or adapter.

---

## Part 16: Compatibility with Existing Codebase

The production executor maintains full compatibility with the existing demo:

- Implements the same `Executor` ABC from `demo/layers/executor.py`
- Uses the same `IntentFrame` and `ExecutionResult` data structures from `demo/data_structures.py`
- Extends (not replaces) the `ActionType` enum from `demo/enums.py`
- Carries forward the `MountPoint` and `LocalFileSystem` patterns from `demo/resources/file_system.py`
- The existing `IntentFrameRuntime.process_request()` in `demo/runtime.py` calls `self.executor.execute(intent)` -- the production executor is a drop-in replacement
- The demo `InvoiceExecutor` continues to work for demo/test scenarios

**Protocol boundary note:** When the executor runs as a standalone service (its
intended production form), the runtime talks to it over the configured transport
protocol. For development/demo, a thin `ExecutorClient` wraps the transport call
behind the same `Executor` ABC interface, so the runtime doesn't change.

---

## Part 17: What Was Added After Vision Alignment Review

After reviewing the full IntentFrame concept documents (Architecture.md,
System-Design-End-to-End.md, How-The-System-Works.md, Why-IntentFrame.md,
Virtual-FileSystem-Design.md, Intent-Frame.md, Intent-Based-Agent-Security-Pure-Concepts.md),
these items were added or strengthened:

1. **Guardian Signature Verification** (Part 5, Invariant 2) -- Every intent must
   carry a cryptographic token from Cloud Guardian. This is the trust boundary.
   Without it, a compromised local process could spoof intents to the executor.

2. **UserIO Adapter** (Part 7, Part 12) -- `user_io.py` added as the 18th adapter.
   UserIOService is a PROTECTED RESOURCE, not a special channel. ASK_USER,
   SHOW_MESSAGE, GET_CONFIRMATION all go through IntentFrame pipeline. Guardian
   validates the prompt is safe (not phishing) before Executor shows it.

3. **Virtual FileSystem as First-Class Service** (Part 5, Invariant 4; Part 12) --
   `virtual_filesystem.py` added to services. The files adapter wraps the VFS,
   not raw Finder/pathlib. Agents NEVER see real paths. This prevents path
   traversal, info leakage, and sandbox escape.

4. **Fail-Closed Enforcement in Base Adapter** (Part 5, Invariant 1; Part 7) --
   Every adapter execute() call is wrapped with asyncio.wait_for(timeout) and
   try/except catching ALL exceptions. Any failure → ExecutionResult(success=False).
   Never hang, never silently succeed.

5. **Credential Scrubbing for Audit** (Part 5, Invariant 3; Part 12) --
   `credential_scrubber.py` added to services. The audit logger ONLY accepts
   pre-scrubbed data. Credentials are never written to audit logs, never
   serialized, never passed over the socket.

6. **Security Events Table** (Part 10) -- New `security_events` SQLite table
   for logging rejected/suspicious attempts (invalid signatures, spoofed intents).

7. **Architecture Context** (Part 2) -- Added section showing how Executor fits
   into IntentFrame's full pipeline: Agent → Actor SDK → Analysis Engine →
   Guardian → Executor. Including the OS analogy mapping.

---

## Part 18: What Was Added After Protocol-Driven Architecture Review

The following fundamental evolution was applied to the plan after recognizing that
the executor should be a **standalone, process-isolated, protocol-driven capability
service** rather than a component hardwired to Guardian.

### Core Insight

Guardian is one **protocol implementation**, not the executor's identity. The
executor is an action-execution service that any authorized system can use through
supported protocols and contracts. This does NOT defeat IntentFrame's principles --
it strengthens them by enforcing separation through process boundaries and formal
protocol contracts rather than in-process coupling.

```
Before:  Executor is "Guardian's execution arm"
After:   Executor is a "general-purpose capability service"
         Guardian is its primary authorized caller (in IntentFrame's deployment)
         But the executor's interface is caller-agnostic
```

### What Changed

8. **Executor as Standalone Service** (Part 1, Part 2) -- The executor is no longer
   described as an internal pipeline stage. It's a standalone isolated process that
   communicates exclusively through validated protocols and secure channels. This
   makes the Think/Judge/Act separation physically enforced via process boundaries.

9. **Pluggable Transport Layer** (Part 3, Part 4, Part 12) -- New `transport/`
   module with `TransportServer` ABC. Implementations: Unix socket (device default),
   gRPC (cloud/device), REST (admin/debug). Only ONE active per deployment,
   selected at config time. All transports produce the same internal
   `ExecutionRequest` after parsing.

10. **Pluggable Authorization Verification** (Part 3, Part 5, Part 12) -- New
    `auth/` module with `AuthVerifier` ABC. Invariant 2 renamed from "Guardian
    Signature Required" to "Authorization Proof Required". Guardian HMAC is one
    implementation. mTLS and JWT verifiers added for cloud/admin scenarios. The
    executor doesn't know WHO authorized the request -- just that the proof is valid.

11. **Pluggable Credential Backend** (Part 6, Part 12) -- `credential_vault.py`
    now defines an interface, not just a keyring wrapper. macOS uses keyring →
    Keychain. Cloud uses HashiCorp Vault. Same interface, different backends.

12. **Design Once, Deploy Anywhere** (Part 2, Part 11) -- New "Design Once, Deploy
    Anywhere" table showing exactly what changes between device and cloud
    deployments (transport, cred backend, adapters, lifecycle manager) vs what
    stays identical (gateway logic, auth interface, adapter pattern, audit trail,
    fail-closed, credential isolation).

13. **Config-Driven Startup** (Part 11, Part 12, Part 15) -- New `executor.yaml`
    configuration file determines which transport, auth verifier, credential backend,
    and adapter set to load at startup. No code changes needed to switch deployment
    profiles.

14. **Protocol Boundary in IntentFrame Integration** (Part 16) -- When used with
    IntentFrame, the runtime talks to the executor over the configured transport.
    A thin `ExecutorClient` wraps the transport call behind the existing `Executor`
    ABC interface, so the runtime code doesn't change.

### Why This Doesn't Defeat IntentFrame Principles

```
┌──────────────────────────────────────┬─────────────────────────────────────┐
│  PRINCIPLE                            │  HOW IT'S STRENGTHENED              │
├──────────────────────────────────────┼─────────────────────────────────────┤
│  No entity can Think + Judge + Act    │  Process boundary makes this        │
│                                      │  PHYSICAL, not just architectural   │
│                                      │                                     │
│  Fail-Closed                          │  Now at protocol level -- harder    │
│                                      │  to bypass than in-process check    │
│                                      │                                     │
│  Credentials Never Leave Executor     │  Separate process = separate memory │
│                                      │  space. Creds physically can't leak │
│                                      │  to runtime via shared references   │
│                                      │                                     │
│  Immutable Audit Trail                │  Executor owns its SQLite store.    │
│                                      │  No other process can touch it.     │
│                                      │                                     │
│  Agent Has Zero Direct I/O            │  Unchanged. Protocol boundary adds  │
│                                      │  another layer between agent and    │
│                                      │  real-world capabilities.           │
└──────────────────────────────────────┴─────────────────────────────────────┘
```

---

This design delivers a **production-grade executor** with ~2,030 lines of custom
code, a minimal set of pip dependencies, zero infrastructure cost, and the ability
for agents to do everything a Mac user can do -- natively, through proper APIs, no
UI hacking -- while enforcing all of IntentFrame's security invariants: fail-closed,
credential isolation, virtual filesystem sandboxing, and cryptographic audit trails.

The executor is now **deployment-agnostic**: the same core runs on a consumer Mac
or in the cloud. The same core accepts requests from Guardian or from any other
authorized system. The protocol is the gate. The contract is the law.

---

## Part 19: Progress — PyXA → Native Framework Migration (Mar 2026)

All macOS adapters have been migrated from PyXA (Apple Events GUI automation)
to native frameworks and stdlib protocols. This eliminates GUI app launches
when Jarvis interacts with the OS programmatically.

### What changed

| Adapter | Before (PyXA) | After (native) | GUI launch? |
|---|---|---|---|
| **Calendar** | `PyXA.Application("Calendar")` | EventKit framework (`pyobjc-framework-EventKit`) | Never |
| **Reminders** | `PyXA.Application("Reminders")` | EventKit framework (`pyobjc-framework-EventKit`) | Never |
| **Contacts** | `PyXA.Application("Contacts")` | Contacts framework (`pyobjc-framework-Contacts`) | Never |
| **Mail** | `PyXA.Application("Mail")` | IMAP/SMTP (stdlib `imaplib`/`smtplib`) | Never |
| **Notes** | `PyXA.Application("Notes")` | SQLite reads + osascript writes | Reads: never. Writes: background |
| **Messages** | `PyXA.Application("Messages")` | SQLite reads + osascript writes | Reads: never. Writes: background |
| **Browser** | `PyXA.Application("Safari")` | `subprocess.run(["open", url])` + httpx | Intentional (user's browser) |
| **System** | `PyXA.Application("System Events")` | osascript subprocess | Never (headless) |
| **Clipboard** | PyXA clipboard | osascript subprocess | Never |
| **Notifications** | PyXA notifications | osascript subprocess | Never |
| **Spotlight** | PyXA spotlight | osascript subprocess | Never |
| **UserIO** | osascript | osascript (unchanged) | Intentional (dialog) |

### New shared modules

- `executor/platforms/macos/_eventkit.py` — Lazy-init `EKEventStore` singleton
  with TCC access request for both Calendar and Reminders entity types.

### Dependency changes

- **Removed:** `mac-pyxa>=0.3` (and its 20+ transitive pyobjc dependencies)
- **Added:** `pyobjc-framework-EventKit>=11.0` and `pyobjc-framework-Contacts>=11.0`
  as explicit darwin-only dependencies in `pyproject.toml`
- **Net result:** 4 pyobjc packages installed (core, Cocoa, EventKit, Contacts)
  vs 22+ before. Leaner environment.

### Seed policy coverage

All 43 actions from enabled adapters now have policy entries in
`jarvis_pa/seed_policies.py` (23 safe + 20 unsafe). Previously only 27 of 45
were covered, blocking Jarvis from using contacts, reading messages/notes,
completing reminders, deleting events/notes, and system controls.

### What this enables next

The native framework migration is a prerequisite for the observation bus:

- **EventKit** provides `EKEventStoreChangedNotification` (push-based calendar/reminder changes)
- **Contacts** provides `CNContactStoreDidChangeNotification` (push-based contact changes)
- **IMAP IDLE** enables push-based email arrival detection
- **FSEvents** (already in `filesystem_watch` adapter) enables push-based file changes
- **SQLite** databases (Notes, Messages) can be monitored via FSEvents for change detection

These push-based sources feed the "Adapter State Change Events" component of the
observation bus — the last piece that PyXA could not provide.

### Verification

`demo/tests/test_adapters.py` — 24-point contract test covering all 16 core
adapters: import, instantiation, `supported_actions()`, `manifest()`, subclass
check, registry population, factory round-trip, action uniqueness, and pyobjc
framework availability. All pass.
