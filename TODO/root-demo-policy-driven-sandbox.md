# Root Demo Policy-Driven Sandbox

> Root demo plan: keep the normal pipeline and action model intact, then enable broad root capability through a separate demo policy/workspace profile plus a minimal executor sandbox.

---

## Goal

Support a clean "Jarvis with root" demo without distorting the normal IntentFrame model.

The demo should show:

- the agent can operate with real root privileges
- the agent can see and use the full system root workspace
- the prevention pipeline still blocks dangerous actions before execution
- the executor still applies a minimal safety-net sandbox chosen by policy

This is a demo profile, not a new permanent action model.

---

## Core Decision

Do **not** add a new `ROOT_RUN_COMMAND` action.

Do **not** add special `sudo` parsing, stripping, or support.

Do **not** mutate the normal `RUN_COMMAND` policy/profile.

Instead:

1. Keep the same `RUN_COMMAND` action.
2. Run the executor (or full stack for the demo) as root.
3. Seed a separate root-demo policy/workspace profile.
4. Let policy select a broad, minimal sandbox template for `RUN_COMMAND`.
5. Tell the agent directly that commands already execute with root privileges and that its root workspace is `/`.

That keeps the model honest:

- privilege comes from how the executor runs
- scope comes from workspace + policy
- containment comes from the sandbox template
- prevention remains the primary defense

---

## Why This Plan

This avoids the wrong kinds of complexity:

- no duplicate action types
- no root-only terminal tool
- no `sudo`-aware branching through the pipeline
- no changes to the normal-mode command policy just to make the demo work

It also matches the execution-security design already written down:

- prevention first
- sandbox as safety net
- policy chooses capability ceiling
- workspace defines visible filesystem scope

---

## What Changes In Demo Mode

### 1. Separate demo policy/profile

Normal mode remains unchanged.

Root demo mode gets its own seeded profile with:

- broader file path permissions (`/*` instead of `/home/*`)
- a broad sandbox policy for `RUN_COMMAND`
- prompt metadata that says commands already run as root

This should be represented as a **separate policy/workspace shape**, not as a mutation of the normal one.

### 2. Root workspace is `/`

For the demo, the agent's workspace root should be `/`.

That means:

- file tools can reference system paths directly
- onboarding can honestly tell the agent its workspace root is `/`
- the demo feels like real root access instead of "root with a fake home-only shell"

### 3. Sandbox is policy-selected and minimal

`RUN_COMMAND` should still go through a sandbox template, but the demo profile should choose a **broad** template with a **small** deny base.

The sandbox is not the star of the demo. It is the last-resort safety net.

### 4. Agent is told the truth

The prompt / runtime context should say:

- your commands run with root privileges
- do not use `sudo`
- your workspace root is `/`

We should leverage the existing handshake/onboarding path for this rather than invent a separate root-only onboarding engine.

---

## What Must Stay Unchanged

These should stay exactly as principles of the design:

- `RUN_COMMAND` remains the only terminal action
- `sudo` remains blocked; the agent should not need it
- the prevention pipeline still runs before executor launch
- normal-mode workspace and policies stay strict
- file tools remain VFS/workspace based

The demo should not depend on weakening the normal model.

---

## Current Gap This Plan Fixes

Today there is a mismatch:

- onboarding/guardrails can tell the agent its file scope is `/home/*`
- file tools respect that workspace
- but `RUN_COMMAND` is not workspace-bound in the same way

For the demo, we do **not** need to solve the fully general "terminal obeys normal workspace boundaries" problem first.

We only need a coherent root-demo profile where:

- the declared workspace is `/`
- the agent is told `/`
- the sandbox is broad enough that `cd /`, `ls /`, `cat /etc/hosts`, etc. work

That keeps the demo aligned without overengineering the terminal model.

---

## Implementation Shape

### Policy / bootstrap

Add a root-demo seed profile that differs from the current bootstrap defaults in two ways:

1. file path scope becomes `/*`
2. sandbox policy for `RUN_COMMAND` becomes broad/minimal

The normal bootstrap seed remains unchanged.

### Workspace / resource registry

Seed a root-demo workspace mount of `/ -> /` (or the broadest acceptable equivalent).

This keeps:

- file tools
- runtime `virtual_paths`
- agent prompt
- executor view

all aligned to the same root workspace model.

### Handshake / onboarding / prompt

Reuse the existing `RuntimeContext` + onboarding flow.

The root-demo profile should surface:

- root workspace `/`
- root privilege note
- "do not use sudo" instruction

No separate root-only onboarding engine is needed.

### Executor / sandbox

`RUN_COMMAND` keeps the same action path.

The executor applies the sandbox template selected by policy for the current profile.

For the demo, that template should be broad enough to preserve the root story while still keeping a minimal immutable deny base.

---

## Minimal Sandbox For The Demo

The demo sandbox should be intentionally broad.

It should allow:

- filesystem access across the declared root workspace
- ordinary root command execution
- `cd /`, `cd ..`, `pwd`, `ls /`, `cat /etc/hosts`, and similar admin operations

It should only keep a very small deny base.

The exact deny base should be reviewed explicitly rather than inherited blindly, but the likely shape is:

- protect IntentFrame internals
- protect raw device writes
- protect anything that would trivially self-disable the platform during the demo

The point is to keep the sandbox honest as a safety net without undermining the "real root capability" story.

---

## Non-Goals

This plan does **not** try to solve:

- a fully general workspace-aware shell for normal mode
- new root-specific terminal action types
- `sudo` support
- terminal path parsing in Guardian
- a fake or virtualized terminal filesystem illusion

Those are separate problems.

---

## Acceptance Criteria

The root demo is correct when all of these are true:

1. The agent is told its workspace root is `/` and that commands already run as root.
2. `READ_FILE`, `WRITE_FILE`, and `LIST_DIRECTORY` can operate on system paths through the root-demo profile.
3. `RUN_COMMAND` can successfully do things like:
   - `pwd`
   - `cd / && ls -la`
   - `cat /etc/hosts`
4. The agent does not need `sudo`, and `sudo` remains blocked.
5. Dangerous commands are still blocked by the prevention pipeline.
6. Normal mode still uses the current stricter policy/workspace profile.

---

## Summary

The clean demo path is:

- same action model
- same prevention pipeline
- same onboarding mechanism
- different seeded profile
- different workspace root
- broader policy-selected sandbox

In short:

**Do not teach IntentFrame how to escalate.**

**Teach the demo profile that it already has root, give it `/`, and keep the sandbox minimal.**


-----
#### New Concrete "ready-to-hand-root" checklist
Before giving the executor a root handle on a real Mac with any persistent state, all of these should be done:

Phase 7a shipped — WRITE_FILE payload inspection + destination sensitivity policy + DG branch that rejects fast-path on auto-load/startup/runtime-shape targets. This closes the single biggest gap.
Phase 7c shipped — per-intent sandbox-template selection in policy + non-overridable deny-path list hardened for root (LaunchAgents, LaunchDaemons, /etc, /System, sshd configs, sudoers, PAM, kexts, ~/Library/Keychains, ~/Library/Messages, ~/Library/Mail, ~/.ssh, ~/.gnupg, shell rc files).
Bundle C overlay bodies authored for critical_generic, critical_network_mutation, critical_network_probe, and Guardian's critical. Today the AI depth for "root RUN_COMMAND" is the same as for "list calendars" prompt-wise.
Root demo profile — a separate UserContext / policy profile whose allow_capabilities is a short, explicit list (capability:read_only:*, capability:package_install:brew maybe) and whose deny_capabilities covers network_bind, background_exec, process_signal, download_and_exec, and the network_probe:{http_mutate,http_download,port_scan,file_transfer} family as a floor.
Red-team corpus run against the root profile specifically — the existing 24-attack test set was built before Bundles A–C and doesn't exercise capability edges, composition fast-path, or WRITE_FILE payload. At least a dozen new attacks: persistence (LaunchAgent plist, crontab, shell rc, .pth), privilege (sudoers, sshd_config, PAM), egress (reverse shell via curl | sh, nc -e, bash -i >& /dev/tcp), interpreter indirection, and TCC-circumvention paths.
Audit-side verification — every matched_gate and decision_path value makes sense in the trace, and ae_prompt_id = critical_* fires on every RUN_COMMAND that went UNDECIDED.

