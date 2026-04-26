# Executor Sandbox

> Kernel-enforced sandboxing for `RUN_COMMAND`. Confined entirely to the executor — the agent, pipeline, Guardian, and wire protocol know nothing about it.

---

## What It Does

Every shell command that reaches `TerminalAdapter.execute()` is wrapped in a macOS Seatbelt sandbox before the subprocess runs. The kernel denies syscalls that violate the generated profile. This is not string matching or process-level filtering — it is the same `sandbox-exec` mechanism Apple uses internally.

The sandbox:

- starts from `(deny default)` — everything blocked unless explicitly allowed
- globally allows all file reads (`(allow file-read*)`) — reads are not the threat model
- restricts writes to paths explicitly listed in `SandboxConfig.allowed_write_paths`
- blocks network access unless the template permits it
- denies writes to system directories and IntentFrame internals regardless of template
- sets a controlled `TMPDIR` so sandboxed processes don't inherit the user's temp tree
- overrides `PATH` with a clean system path (from `/etc/paths` + `/etc/paths.d/*`), preventing the executor's venv from leaking into sandboxed commands

---

## Architecture

```
RUN_COMMAND arrives at TerminalAdapter
    │
    ├── command_shield.quick_check()     catastrophic pattern filter
    │
    ├── planner.plan(cwd)                uses max(allowed_templates) from config
    │       │
    │       ├── reads SandboxConfig from executor.yaml
    │       ├── derives write paths from config.allowed_write_paths
    │       ├── canonicalizes all paths via pathing.canonical_sandbox_path()
    │       │
    │       ▼
    │   ExecutionPlan
    │       { template, allowed_read_paths=(),
    │         allowed_write_paths, deny_write_paths, deny_access_paths }
    │
    ├── engine.wrap(command, plan)        build SBPL profile, return argv
    │       │
    │       ▼
    │   SandboxedCommand
    │       { argv: [sandbox-exec, -p, '<profile>', /bin/sh, -c, '<command>'],
    │         env_overrides: {TMPDIR: ..., PATH: ...} }
    │
    └── asyncio.create_subprocess_exec(*argv, env=clean_env | overrides)
```

All commands get the same sandbox template: `max(allowed_templates)` — the highest-privilege template the admin approved in config. No per-command classification. The security decision is made once in config, not per-command at runtime.

The engine returns a `SandboxedCommand` dataclass with an `argv` list and `env_overrides` dict. The adapter passes `argv` directly to `create_subprocess_exec` — no shell re-parsing, no `shlex.quote()` issues.

---

## Module Layout

```
executor/sandbox/
├── __init__.py
├── capabilities.py      Capability enum + CapabilityReport dataclass
├── classifier.py        Deterministic command analysis (shlex-based, not used in execution path)
├── templates.py         SandboxTemplate enum, capability lattice, deny lists
├── pathing.py           canonical_sandbox_path() — realpath normalization
├── planner.py           SandboxPlanner + ExecutionPlan
├── engine.py            SandboxEngine ABC + SandboxedCommand + platform factory
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
  working_directory: ~/
  allowed_write_paths:
    - ~/
  allowed_templates:
    - pure_compute
    - file_read_only
    - file_read_write
    - network_outbound
  # executor_venv_path: null           # auto-resolve to ~/.intentframe-venvs/executor
  # executor_venv_required: true       # fail-closed at startup if missing
  # escalate: none                     # "sudo" only for root demo profile
```

The root demo profile (`jarvis_pa/executor_root.yaml`) sets `escalate: sudo`:

```yaml
sandbox:
  enabled: true
  working_directory: /
  allowed_write_paths:
    - /
  allowed_templates:
    - pure_compute
    - file_read_only
    - file_read_write
    - network_outbound
    - unrestricted
  escalate: sudo
```

### Fields

| Field | Purpose |
|---|---|
| `enabled` | Master switch. When `false`, commands run bare. |
| `allowed_templates` | All commands run under the highest-privilege template in this list. |
| `working_directory` | Default cwd for sandboxed commands. Expanded via `os.path.expanduser()` at runtime. Defaults to `~/`. |
| `allowed_write_paths` | Paths where sandboxed commands can write. Expanded + canonicalized at runtime. Defaults to `["~/"]`. |
| `executor_venv_path` | Absolute path to the executor's dedicated Python venv. `None` = auto-resolve to `<owner_home>/.intentframe-venvs/executor`. Owner is `SUDO_USER` if set, else the running uid's HOME; bare root with no `SUDO_USER` resolves to `None`. Provisioned by `intentframe_setup.sh` via `uv venv --seed`. Must not sit under any `NON_NEGOTIABLE_DENY_ACCESS` entry (e.g. `~/.intentframe/`); the planner rejects such paths at startup because the sandbox would deny reads on `bin/python3`, breaking exec. |
| `executor_venv_required` | Default `True`. When `True`, executor startup fails if the venv is missing or lacks `bin/python3`. Set `False` to fall back silently to system `python3`. |
| `escalate` | `"none"` (default) or `"sudo"`. When `"sudo"`, the macOS engine prepends `sudo -n --preserve-env=PATH,VIRTUAL_ENV,PYTHONNOUSERSITE,TMPDIR` to the `sandbox-exec` argv so the kernel sandbox subprocess runs as root. Only takes effect when the gateway also sets `INTENTFRAME_ESCALATION_ARMED=1` (set iff `intentframe_setup_root_demo.sh` has installed the narrow sudoers entry). See `docs/executor-root-mode.md` for the full operator flow. |

### Executor venv exposure

When `executor_venv_path` resolves to a usable venv, the macOS sandbox engine adds four env overrides for every `RUN_COMMAND` subprocess:

- `PATH` — `<venv>/bin` prepended to the `/etc/paths`-derived system PATH, so `python`, `python3`, `pip`, and `uv pip` resolve into the venv
- `VIRTUAL_ENV` — set to the venv path, so `pip install X` lands in the venv rather than `<repo>/.venv` or user-site
- `PYTHONNOUSERSITE=1` — blocks `pip install --user` escapes to `~/Library/Python/...`
- `PYTHONHOME` — never set (venvs break if it is)

This is the **only** explicit pathway a venv reaches sandboxed commands. The `command_shield.env.clean_env()` whitelist still drops `VIRTUAL_ENV` from the parent environment, so a venv activated in the shell that launched the gateway does **not** leak into `RUN_COMMAND` — only the executor-configured venv does.

### Template selection

The planner picks `max(allowed_templates)` — the highest-privilege template the admin listed. If the admin put `network_outbound` in the list, every command gets `network_outbound`. If they only listed `file_read_write`, every command gets `file_read_write`.

This is intentional: the outer pipeline (command_shield → AE → Guardian) already made the trust decision for each command. The sandbox enforces the admin's privilege ceiling uniformly — it doesn't try to be clever about which template to pick per-command.

### Filesystem scope is self-contained

The sandbox does **not** read VFS mounts. Write paths come directly from `SandboxConfig.allowed_write_paths`. Read paths are not restricted (global `(allow file-read*)`).

This decoupling is intentional: `RUN_COMMAND` is a different tool from file I/O adapters. The VFS translates virtual paths for `READ_FILE`/`WRITE_FILE` — that's a completely separate concern from what a shell command can touch. A sandboxed `cp` or `python3` needs real filesystem access, not virtual path translation.

With `allowed_write_paths: ["~/"]`, the generated SBPL profile includes:

```
(allow file-write* (subpath "/Users/prince"))
```

---

## Read Policy: Allow All, Deny Sensitive

The sandbox uses a **permissive read / restrictive write** model, mirroring Anthropic's `sandbox-runtime` approach:

```
(allow file-read*)
```

Reads are globally allowed. Sensitive paths are protected by deny-access overrides placed last (Seatbelt last-match-wins), which block both reads and writes:

```
(deny file-read* file-write* (subpath "/Users/prince/.intentframe"))
```

Why not a read whitelist? Because macOS system binaries need to read from unpredictable paths:

- `/usr/bin/python3` is an `xcrun` shim that loads a dylib from `/Applications/Xcode.app/Contents/Developer/...`
- Homebrew lives in `/opt/homebrew` on Apple Silicon, `/usr/local` on Intel
- System frameworks load from `/System/Library`, `/usr/lib`, `/Library/Apple/...`

Whitelisting individual system directories is a losing game. Reads are not the threat model — writes and network exfiltration are.

---

## Clean PATH (No Venv Leakage)

The engine sets `PATH` in `env_overrides` to a clean system path built from `/etc/paths` and `/etc/paths.d/*` — the same source macOS uses for login shells:

```python
env_overrides = {
    "TMPDIR": "/private/tmp/intentframe",
    "PATH": _system_path(),  # e.g. /usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin
}
```

This guarantees that `python3` inside the sandbox resolves to `/usr/bin/python3` (system Python), not the executor's `.venv/bin/python3`. The executor runs inside a venv, but sandboxed commands must not inherit it.

The fallback path (if `/etc/paths` can't be read) is: `/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin`.

---

## Templates

Templates form a lattice from narrowest to broadest:

| Template | File Read | File Write | Process Info | Network Out | Network Bind | Background | Signals | Opaque |
|---|---|---|---|---|---|---|---|---|
| `pure_compute` | | | same-sandbox | | | | | |
| `file_read_only` | x | | same-sandbox | | | | | |
| `file_read_write` | x | x | same-sandbox | | | | | |
| `network_outbound` | x | x | **global** | x | | | | |
| `network_full` | x | x | **global** | x | x | x | | |
| `unrestricted` | x | x | **global** | x | x | x | x | x |

**Process Info** — Templates below `network_outbound` restrict `process-info*` to `(target same-sandbox)`, meaning sandboxed code can only see processes inside the sandbox. Templates at `network_outbound` and above get unrestricted `process-info*`, enabling system-wide process enumeration (`ps`, `top`, `lsof`, Activity Monitor queries). This is gated at the network tier because if the sandbox already trusts commands enough for outbound network (where data could be exfiltrated to external servers), process visibility is a strictly lesser disclosure.

**SUID `/bin/ps`** — `/bin/ps` is a setuid-root binary (`-rwsr-xr-x`). macOS Seatbelt unconditionally blocks execution of SUID binaries (`forbidden-exec-sugid`) regardless of any `(allow process-exec)` rule. For `network_outbound`+ templates, the profile includes `(allow process-exec (literal "/bin/ps") (with no-sandbox))` which permits executing this specific binary without sandbox inheritance. Lower templates cannot run `ps` at all.

The admin controls which templates are available via `allowed_templates`. The planner uses the highest one in the list for all commands.

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

This protects IntentFrame's runtime data: config, secrets, databases, logs, audit trail. Even though `~/` is typically an allowed write path, the deny override blocks all access to `~/.intentframe`.

---

## Path Canonicalization

All paths in the `ExecutionPlan` are canonical — resolved via `os.path.realpath()`. This is critical on macOS where:

- `/var` → `/private/var`
- `/tmp` → `/private/tmp`
- `/etc` → `/private/etc`
- `tempfile.TemporaryDirectory()` returns `/var/folders/...` → resolves to `/private/var/folders/...`

The macOS kernel (Seatbelt) enforces rules against canonical paths. If the SBPL profile says `(allow file-write* (subpath "/var/folders/..."))` but the kernel sees `/private/var/folders/...`, the rule doesn't match and the write is denied.

`executor/sandbox/pathing.py` provides `canonical_sandbox_path()` which the planner applies to:
- every path in `SandboxConfig.allowed_write_paths`
- working directory
- all deny list paths

---

## Controlled Temp Directory

Sandboxed commands use `/tmp/intentframe` (canonicalized to `/private/tmp/intentframe`) instead of the system's per-user temp tree under `/var/folders/...`.

The engine:
1. Creates `/tmp/intentframe` with mode `0o700` if it doesn't exist
2. Adds a write SBPL rule for that directory
3. Sets `TMPDIR=/private/tmp/intentframe` in the subprocess environment

This avoids blanket-allowing `/private/var/folders` in the profile, which would undermine deny rules for paths under the user's temp tree.

---

## SBPL Profile Structure

The generated Seatbelt profile follows this order (last-match-wins):

1. **Header**: `(version 1)` + `(deny default)`
2. **Essential system allowances**: process-exec, process-fork, process-info* (same-sandbox), mach-lookup, sysctl-read, iokit, pseudo-tty, etc.
3. **Global file reads**: `(allow file-read*)` — reads are unrestricted
4. **Controlled temp directory**: write for `/private/tmp/intentframe`
5. **Device writes**: `/dev/null`, `/dev/tty`
6. **Template-specific rules**: global `(allow process-info*)` and SUID `/bin/ps` exec (`with no-sandbox`) for `network_outbound`+; network-outbound, network-bind, network-inbound (only for network templates); `(allow default)` for `unrestricted`. Placed after essential rules so Seatbelt last-match-wins widens the baseline same-sandbox process-info to global.
7. **Config-derived write allow rules**: `(allow file-write* (subpath ...))` for each path in `allowed_write_paths` (only for `file_read_write` and higher templates)
8. **Non-negotiable deny overrides**: deny-write for system dirs, deny-access for `~/.intentframe` (always last)

The profile is generated entirely in Python code (`executor/sandbox/platforms/macos.py`), following Anthropic's `sandbox-runtime` pattern. There is no static `.sbpl` file.

---

## Classifier (Library Only)

The classifier (`executor/sandbox/classifier.py`) performs deterministic, shlex-based analysis of command strings. It is **not used in the execution path** — the planner applies the same template to all commands regardless of what the classifier would say.

The classifier module is retained as a library for potential use in auditing or logging (e.g. "this command would have needed network access"). It does not affect sandbox behavior.

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
- It does not classify commands to pick a template. All commands get the same template (admin-configured ceiling).
- It does not teach the agent about sandbox templates. The agent has no visibility into sandbox internals.
- It does not modify `IntentFrame`, `RuntimeContext`, `ExecutionRequest`, or any pipeline types.
- It does not touch policy registry, resource registry, or Guardian.
- It does not allow agent-authored `sudo`. `sudo` in a command string is blocked by `command_shield` before it ever reaches the sandbox.
- It does not use VFS mounts. Write paths come from `SandboxConfig`, not `MountPointResolver`.

The `escalate: sudo` path is the one narrow exception to the "no sudo" rule — the sandbox engine itself prepends `sudo -n` to the `sandbox-exec` argv during the root demo mode, as an internal implementation detail invisible to the agent. This is only armed when both the executor config opts in (`sandbox.escalate: sudo`) and the gateway has confirmed the machine-level capability is present (`INTENTFRAME_ESCALATION_ARMED=1`).

---

## Testing

Tests in `tests/test_sandbox.py` covering:

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
| `TestPlanner` | Template = max(allowed_templates), config write paths, deny paths |
| `TestPlannerConfigShapes` | Write path canonicalization, tilde expansion, working dir, deny paths |
| `TestEngineFactory` | Platform detection, unsupported platform |
| `TestProfileGeneration` | SBPL structure: global file-read, deny ordering, TMPDIR write, path escaping, template-gated process-info |
| `TestSeatbeltEnforcement` | **Real `sandbox-exec` calls**: echo, read, write, deny-write, deny-access, pure-compute block |
| `TestNetworkEnforcement` | **Real `sandbox-exec` calls**: outbound connect, bind, template-specific network blocking |
| `TestProcessInfoEnforcement` | **Real `sandbox-exec` calls**: ps, pidinfo, rusage, listpids — global for network_outbound+, same-sandbox for lower |
| `TestUnrestrictedEnforcement` | **Real `sandbox-exec` calls**: unrestricted template with deny overrides still holding |
| `TestTerminalAdapterSandbox` | Adapter wiring: disabled, unavailable, wrapped, bare compat |
| `TestEndToEnd` | Full pipeline: plan → wrap → subprocess for echo, cat, cp, network ceiling |
| `TestExecutorVenvResolver` | Venv path resolution from config, `SUDO_USER`, and uid HOME |
| `TestExecutorVenvValidator` | Venv validation: missing, unusable, valid |
| `TestExecutionPlanVenvThreading` | Planner threads venv path through `ExecutionPlan` |
| `TestMacOSEngineVenvOverrides` | Engine sets `VIRTUAL_ENV`, venv `PATH` prefix, `PYTHONNOUSERSITE` |
| `TestSeatbeltVenvEnforcement` | **Real `sandbox-exec`**: `which python3` resolves to venv; env vars set |
| `TestPlannerRejectsVenvUnderDenyAccess` | Planner logs error and returns `None` when venv is under deny-access path |
| `TestSeatbeltProductionDenyBehavior` | **Real `sandbox-exec`**: deny-access blocks venv exec; sibling path execs cleanly |
| `TestMacOSEngineEscalationWrap` | `sudo -n` wrapping only when both `INTENTFRAME_ESCALATION_ARMED=1` and `sandbox_escalate="sudo"`; `--preserve-env` preserves venv env vars; `env_overrides` still populated |

The enforcement tests run actual commands through `sandbox-exec` and verify the kernel blocks or allows operations.

---

## Relationship to Other Docs

| Doc | Relationship |
|---|---|
| `executor/plan.md` | Overall executor architecture. Sandbox is a capability of the Terminal adapter (Layer 3). |
| `TODO/executor-only-run-command-sandbox.md` | Original design doc. Implementation has since been simplified — classifier removed from execution path, uniform template selection. |
