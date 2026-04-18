# Shell-Mode Host File Tools For Jarvis

> When `RUN_COMMAND` is allowed, Jarvis should stop mixing virtual-path file tools with real-path shell execution. Add a host-path file tool mode for shell-enabled agents and keep VFS tools for non-shell workspace mode.

---

## The Problem

Today Jarvis exposes:

- VFS-backed file tools like `READ_FILE`, `WRITE_FILE`, and `LIST_DIRECTORY`
- real shell execution through `RUN_COMMAND`

Those two surfaces operate on different path models:

- file tools use virtual paths like `/home/project/file.py`
- shell commands use real host paths like `~/project/file.py` or `/Users/prince/project/file.py`

That creates three problems:

1. **Path confusion**  
   The agent writes `/home/foo.sh` through `WRITE_FILE`, then tries to run `/home/foo.sh` in the shell and fails because the shell does not understand VFS paths.

2. **Fake safety boundary when shell is allowed**  
   Once `RUN_COMMAND` is available, the agent can already discover usernames, OS paths, and real filesystem layout. VFS no longer meaningfully hides that information.

3. **Mismatched policy vocabulary**  
   File tools are constrained in virtual-path space, while the sandbox and shell operate in real-path space. The admin has to reason in two path systems for one agent.

---

## Core Observation

The current design already admits that `RUN_COMMAND` is different:

- `RUN_COMMAND` intentionally bypasses VFS
- sandbox policy is defined in real host paths
- command inspection and runtime execution both reason about literal shell commands

That means there are really two operational modes in the system:

### 1. Workspace / VFS mode

- no shell, or very constrained shell
- virtual paths are valuable
- workspace abstraction is real
- path hiding and mount isolation matter

### 2. Shell / host-path mode

- `RUN_COMMAND` is allowed
- the agent already sees real paths
- file tools should align with shell semantics
- policy and audit should use the same real-path vocabulary

Trying to serve both with one file action surface is what creates the confusion.

---

## Proposed Direction

Add a second file action family for shell-enabled agents:

- `READ_HOST_FILE`
- `WRITE_HOST_FILE`
- `LIST_HOST_DIRECTORY`
- `DELETE_HOST_FILE`
- `APPEND_HOST_ROW`

Use these for Jarvis when `RUN_COMMAND` is allowed.

Keep the current VFS actions for workspace-mode agents:

- `READ_FILE`
- `WRITE_FILE`
- `LIST_DIRECTORY`
- `DELETE_FILE`
- `APPEND_ROW`

Do **not** expose both families to the same agent at the same time.

If both are visible, the model will mix them and path confusion returns.

---

## Why This Is Better

### 1. One path language per agent

In shell mode:

- shell uses real paths
- file tools use real paths
- policy constraints use real paths
- sandbox write scope uses real paths
- audits record real paths

That makes the system coherent.

### 2. Cleaner reasoning in IntentFrame

A host-file action is semantically closer to `RUN_COMMAND` than to VFS file actions:

- both touch the host filesystem directly
- both rely on real-path policy
- both should share canonicalization rules
- both should be reasoned about with the same mental model

This is a better match for Analysis Engine, Guardian, and auditing than pretending all file actions are workspace-virtual.

### 3. VFS stays valuable where it actually matters

VFS is still the right model for:

- agents without shell access
- workspace-scoped products
- demos that want filesystem abstraction
- future multi-tenant or remote environments

This is not a reason to delete VFS. It is a reason to stop forcing VFS onto shell-enabled Jarvis.

---

## Architectural Consequences

### Action model

These should be separate actions, not a hidden mode bit inside the same action name.

Why:

- `READ_FILE` and `READ_HOST_FILE` have different target semantics
- Guardian should know which policy checker to apply from the action type
- audit logs should reflect whether the agent accessed virtual or host paths
- docs and prompts become more honest

### Guardian

Add a separate host-file checker rather than overloading the current VFS checker.

The current checker assumes virtual-path normalization and `allowed_paths`.
Host-path actions should instead use:

- host-path canonicalization
- explicit allow roots / allowed real paths
- hard denies for infrastructure paths
- optional symlink policy

### Sandbox alignment

Host file tools should align with the sandbox planner's real-path worldview.

That means:

- same canonicalization rules where possible
- same non-negotiable infrastructure denies
- same admin-facing path vocabulary

### Audit

Host-path file actions and shell commands should produce directly comparable audit records.

That makes it easier to answer questions like:

- did the agent read this sensitive file via shell or file tool?
- did it write code and then execute it?
- did it delete a path directly or through `rm`?

---

## Important Caveat

This does **not** solve the shell deletion-policy gap by itself.

Today there is a structural mismatch:

- `DELETE_FILE` can participate in deletion-specific policy / confirmation flows
- `rm` inside `RUN_COMMAND` is just a shell command unless separately detected

If Jarvis keeps `RUN_COMMAND`, the system still needs a way to reason about:

- deletion capability in shell commands
- write-then-execute chains
- sensitive path reads through shell

So this TODO is about **semantic coherence and cleaner architecture**, not about magically making shell safe.

---

## Recommended Rules

1. If `RUN_COMMAND` is **not** allowed:
   use VFS file actions only.

2. If `RUN_COMMAND` **is** allowed:
   use host-path file actions only.

3. Never expose both VFS and host-path file tools to one agent profile.

4. Keep VFS as a first-class capability for non-shell and workspace products.

5. Treat infrastructure paths like `~/.intentframe` as non-negotiable denies in both:
   - shell sandbox
   - host-file policy layer

---

## Implementation Shape

### Executor

- add a host-files adapter parallel to the current VFS files adapter
- reuse structured read/write behavior where possible
- switch only path normalization / boundary enforcement

### Action registry

- add host-file action types
- keep VFS actions unchanged

### Jarvis tool surface

- expose host-file tools when `RUN_COMMAND` is present
- expose VFS tools when running in workspace-only mode

### Policy

- define host-file constraints separately from VFS constraints
- use real paths, not virtual paths

### Docs

- update the "virtual paths only" invariant so it is explicitly scoped to VFS mode
- document shell mode as host-path mode, not "VFS plus shell"

---

## Open Questions

1. Should host-file actions use a new constraint type, or a mode flag inside file constraints?
2. Should host-file reads follow symlinks by default, or require explicit opt-in?
3. Should `RUN_COMMAND` and host-file actions share a common path canonicalization helper?
4. Should shell capability classification eventually emit file-access intents for Guardian and audit correlation?
5. Should Jarvis mode be chosen statically by profile, or dynamically from `allowed_actions` at handshake time?

---

## Recommended First Step

Do the smallest honest version first:

1. add host-file action types and a host-files adapter
2. expose them only in Jarvis shell mode
3. stop exposing VFS file tools in shell-enabled Jarvis
4. leave VFS untouched for non-shell modes
5. separately design how shell deletion / write-exec policy should be reasoned about

---

## Summary

The right framing is not "remove VFS."

It is:

- **VFS mode for workspace agents**
- **host-path mode for shell-enabled agents**

Jarvis with `RUN_COMMAND` belongs in host-path mode.
