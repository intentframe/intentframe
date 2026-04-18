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

### Important current constraint

Today the shell sandbox intentionally strips the executor venv from `PATH` and resolves sandboxed `python3` to system Python.

That is the right default.

A future per-agent Python env should therefore be:

- explicitly provisioned,
- explicitly mounted / allowed,
- explicitly invoked,
- not inherited accidentally through ambient `PATH`.

---

## Future Shape

### Near-term

- add write-file policy that distinguishes passive files from executable/runtime-shaping files
- use `inspect_code(...)` for deterministic payload triage
- add path sensitivity rules for persistence, startup, secrets, workflows, and product internals

### Mid-term

- create a dedicated `WRITE_FILE` critical-path route when the write creates executable code or touches sensitive paths
- feed `inspect_code(...)` findings into Guardian as structured signals

### Longer-term

- provision a per-agent Python environment
- constrain Python package installs and execution to that environment
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
