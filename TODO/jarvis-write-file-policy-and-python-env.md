# Jarvis Write-File Policy And Per-Agent Python Env

> Tighten `WRITE_FILE` around actual execution risk, not just file mutation in general, and move Jarvis toward an explicit per-agent Python environment instead of ambient system or executor Python.

---

## Goal

Keep Jarvis broadly useful without giving it unnecessary power to create new execution surfaces.

The main idea is:

- do **not** over-restrict ordinary file writing,
- do **not** treat every non-Python file as equally dangerous,
- do treat executable, auto-loaded, persistence-bearing, or runtime-shaping files as higher risk,
- use `command_shield.inspect_code(...)` as a deterministic payload-inspection helper,
- and eventually give each agent a dedicated Python environment inside the sandbox.

---

## The Tension

Jarvis is practically a shell + Python agent today.

That means there is a mismatch if we let it freely:

- write arbitrary executable code in runtimes it cannot safely reason about,
- create startup or persistence files,
- change build/deploy/workflow behavior,
- or install dependencies into ambient Python state.

But the opposite extreme is also wrong:

- blocking every non-Python write would prevent many legitimate tasks,
- many safe writes are docs, JSON, YAML, TOML, config, notes, or passive data,
- and some non-Python files are operationally harmless while some Python files are not.

So the policy should be based on **execution risk + destination sensitivity + payload inspection**, not extension alone.

---

## Core Decision

Do **not** make the default rule:

> "Jarvis may only write Python files."

Instead, make the default rule:

> "Jarvis may write ordinary passive files freely, but executable or auto-loaded writes require stronger checks."

This keeps capabilities broad where they are low-risk and narrow where they materially increase control over the system.

---

## Where `command_shield.inspect_code(...)` Fits

`inspect_code(...)` is a good fit for `WRITE_FILE` payload triage when we already have content in memory.

It can help answer:

- does this payload look like code,
- what language does it appear to be,
- does it look binary,
- what deterministic findings exist if it is Python or shell,
- what structured signals should downstream policy or AI consume.

It should **not** be the final authority for "safe to write".

It is a fact producer, not policy.

For `WRITE_FILE`, it should feed a later decision layer that also considers:

- target path sensitivity,
- overwrite vs create,
- whether the file is executable or auto-loaded,
- whether the current action/task justifies creating this kind of file,
- and whether the language/runtime is one Jarvis is expected to operate in.

---

## Proposed Write-File Policy Shape

### 1. Passive files: generally allow

These should usually remain low-friction:

- `*.md`
- `*.txt`
- `*.json`
- `*.yaml`, `*.yml`
- `*.toml`
- `*.csv`
- ordinary app/local config files that are not auto-executed

These may still need path-based checks, but they should not automatically be treated as high-risk just because they are writes.

### 2. Python and shell: allow, but inspect

Jarvis should usually be allowed to write:

- `*.py`
- `*.sh`
- shell snippets in known-safe project/workspace paths

But the payload should be inspected and the result should surface to policy and Guardian:

- language
- binary/unknown detection
- code findings
- signals

### 3. Other executable or runtime-shaping files: review by default

These should normally require stronger review, not silent allow:

- `*.js`, `*.mjs`, `*.cjs`, `*.ts`
- `*.rb`, `*.pl`
- launchd plists
- CI/workflow files
- Dockerfiles / Compose files
- Makefiles
- editor automation / hooks
- shell startup files

The reason is not that these languages are bad. The reason is that these files can create new execution surfaces that Jarvis is not primarily scoped to manage today.

### 4. Sensitive destinations: block or escalate regardless of extension

Certain paths should be high-risk even when the file is plain text:

- `~/.ssh/*`
- `.env` and credential stores
- `~/.gitconfig`, git hooks
- `.github/workflows/*`
- `~/Library/LaunchAgents/*`
- `/Library/LaunchDaemons/*`
- shell startup files like `.zshrc`, `.bashrc`
- runtime or product internals such as `~/.intentframe/*`

This is path risk, not just content risk.

---

## Recommended Decision Matrix

For `WRITE_FILE(target_path, content)`:

1. classify the target path:
   - passive path
   - executable/runtime path
   - sensitive/persistence path
2. inspect the payload:
   - text vs binary-like
   - language inferred from path / shebang / content
   - deterministic findings if language is in scope
3. combine both:
   - passive path + passive content -> allow
   - ordinary code path + Python/shell payload -> inspect + allow/review
   - unsupported executable language -> review
   - persistence/sensitive path -> block or require explicit higher-trust route

The key is:

- path alone is insufficient,
- extension alone is insufficient,
- code findings alone are insufficient,
- but together they form a useful risk model.

---

## Suggested `inspect_code(...)` Interpretation For Writes

`CodeReport` can drive policy roughly like this:

- `language == "binary"` -> not a normal text/code write; treat as higher risk or reject from normal write path
- `language == "unknown"` -> ambiguous; review instead of assuming safe
- `signals` includes `CODE_TOO_LARGE` -> reduced confidence; review
- `signals` includes `resolved:unsupported-language` -> inspection depth limited; review if executable path
- `code_intel.findings` non-empty -> surface to Guardian / policy / audit

This is especially useful for:

- generated Python scripts,
- generated shell scripts,
- notebook cell export,
- small helper tools created during a task,
- policy decisions like "writing Python into `scripts/` is acceptable, but writing shell init into home dotfiles is not."

---

## Why Not Extension-Only Blocking

An extension-only rule would create bad incentives and blind spots:

- safe YAML/TOML/JSON writes would be treated too harshly,
- risky plain-text files like `.bashrc` or `.env` might slip through if they are not on a denylist,
- Python files could still be dangerous while non-Python files could be benign,
- future agent capabilities would be artificially constrained by today's runtime assumptions.

We want to reduce **unsafe effects**, not just reduce the number of file types.

---

## Per-Agent Python Environment

Longer term, Jarvis should not rely on ambient system Python or the executor's own venv for task execution.

Instead, each agent (or task/session) should get a dedicated Python environment with:

- an explicit filesystem location,
- explicit sandbox write permission,
- explicit interpreter path,
- isolated package state,
- lifecycle control and cleanup.

### Why this is better

- no dependency pollution across agents,
- no accidental coupling to executor internals,
- safer package installation story,
- easier auditability,
- clearer policy boundaries for Python execution,
- easier future support for "this agent can use Python, but only inside its own env."

### Current state (implemented)

The executor now has a dedicated venv at `~/.intentframe-venvs/executor` (sibling of `~/.intentframe/`, not nested under it — the latter is in `NON_NEGOTIABLE_DENY_ACCESS` and would make `exec` of the venv's `python3` fail in the sandbox). Provisioned by `intentframe_setup.sh` via `uv venv --seed`. The path is configurable via `--executor-venv` (setup flag), `INTENTFRAME_EXECUTOR_VENV` (env var), or `sandbox.executor_venv_path` (runtime). The macOS sandbox engine explicitly exposes that venv to sandboxed `RUN_COMMAND` via env overrides:

- `PATH` is prepended with `<venv>/bin` on top of the system-derived `PATH` from `/etc/paths`.
- `VIRTUAL_ENV` is set to the venv path.
- `PYTHONNOUSERSITE=1` is set to block `pip install --user` escapes.
- `PYTHONHOME` is never set (venvs break if it is).

This means in the normal case `python`, `python3`, `pip`, and `uv pip install` all resolve to the executor venv. `<repo>/.venv` (the gateway's venv) and `~/Library/Python/...` (user site) are structurally protected from pollution. The config knobs are `sandbox.executor_venv_path` (absolute path, `None` = auto-resolve) and `sandbox.executor_venv_required` (default `True` → fail-closed at startup if the venv is missing).

Path resolution is identity-aware: it uses `SUDO_USER` if present, else the current uid's HOME, so the design works whether the executor runs as a regular user or as root. Bare root with no `SUDO_USER` fails loud rather than silently picking `/var/root/`.

The planner also cross-checks the resolved venv path against `NON_NEGOTIABLE_DENY_ACCESS` at startup: a venv path nested under any deny-access subpath is rejected (returns `None`), which triggers fail-closed when `executor_venv_required=True`. This catches the "default path inside the deny perimeter" footgun deterministically at startup rather than at first `RUN_COMMAND`. `intentframe_setup.sh` mirrors the same guardrail.

Uninstall is handled by `intentframe_uninstall.sh` — it removes `~/.intentframe-venvs/` and `~/.intentframe/` (interactive confirm unless `--yes`), and optionally the signing cert (`--remove-cert`) and keychain vault entries (`--remove-keychain-vault`). TCC grants remain a manual cleanup step (macOS doesn't expose a programmatic API).

### Unchanged constraints

- `command_shield/env.py` whitelist still drops `VIRTUAL_ENV` and friends from the parent env. The venv exposure is an **explicit override** added by the sandbox engine, not inheritance from whatever was activated in the parent shell.
- `_system_path()` still replaces `PATH` with `/etc/paths`-derived values. The venv prepend sits **on top** of that, so regular binaries (`git`, `rg`, `grep`, etc.) still resolve normally.
- Absolute-interpreter bypasses (`/usr/bin/python3 foo.py`) are not blocked by this design — they're a `command_shield.inspect_code(...)` concern, handled by a separate layer.

### Per-agent: next

Now that the plumbing is "plan carries an absolute venv path, engine adds env overrides", per-agent venvs are a substitution, not new plumbing:

- agent session lifecycle manager creates `~/.intentframe-venvs/agent-<id>`,
- planner pulls venv path from agent context instead of `SandboxConfig.executor_venv_path`,
- add an explicit `install_package` tool separate from `RUN_COMMAND`.

---

## Future Shape

### Near-term

- add write-file policy that distinguishes passive files from executable/runtime-shaping files
- use `inspect_code(...)` for deterministic payload triage
- add path sensitivity rules for persistence, startup, secrets, workflows, and product internals
- fix `SandboxConfig.working_directory` to use the same identity-aware expansion as the executor venv (currently `os.path.expanduser` in `terminal.py` resolves against whatever HOME the executor process has — wrong under bare root)

### Mid-term

- create a dedicated `WRITE_FILE` critical-path route when the write creates executable code or touches sensitive paths
- feed `inspect_code(...)` findings into Guardian as structured signals
- `command_shield.inspect_code(...)` should flag absolute-interpreter invocations (`/usr/bin/python3 …`) and absolute-shebang scripts as signals, since those bypass the executor-venv PATH steering

### Longer-term

- provision a per-agent Python environment (plumbing already in place: swap the venv path on the plan)
- constrain Python package installs and execution to that environment
- add an explicit `install_package` tool so free-form `pip install` in `RUN_COMMAND` can be deprecated
- make "agent can write Python here and run it there" an explicit, inspectable policy decision

---

## Open Questions

1. Should `WRITE_FILE` split into passive vs critical routing deterministically based on path + payload classification?
2. Which paths should be non-negotiable deny-write for file tools, analogous to the command sandbox deny list?
3. Should shell startup files and workflow files be blocked outright or only escalated?
4. Should unsupported code languages be reviewed or blocked by default?
5. What is the lifecycle of a per-agent env: per request, per chat, per workspace, or per long-lived agent identity?

---

## Summary

The right policy is not:

> "Jarvis may only write Python files."

The right policy is:

> "Jarvis may write broadly, but writes that create execution surfaces or touch sensitive paths must go through stronger inspection and policy."

And the long-term clean execution model is:

> "If Jarvis is a Python-capable agent, give it its own explicit Python environment instead of letting Python capability leak in from ambient runtime state."
