# VFS vs Host File Tools

Status: **design note**. This document explains the two filesystem tool
families in IntentFrame, when each one should be used, and why they
should not normally be exposed to the same LLM tool list.

---

## The two families

IntentFrame supports two distinct file-action families:

| Family | Actions | Path examples | Constraint field |
|---|---|---|---|
| VFS / workspace file tools | `READ_FILE`, `WRITE_FILE`, `LIST_DIRECTORY`, `DELETE_FILE`, `APPEND_ROW` | `/home/report.md` | `FileConstraints.allowed_paths` |
| Host file tools | `READ_HOST_FILE`, `WRITE_HOST_FILE`, `LIST_HOST_DIRECTORY`, `DELETE_HOST_FILE` | `~/Documents/report.md` | `HostFileConstraints.allowed_host_paths` |

They are intentionally separate products at the action-model level.
They do not share a checker, a constraint field, or a path
canonicalizer.

---

## What VFS tools are for

VFS tools are the right fit for **workspace-scoped agents**.

Characteristics:

- The agent works inside a declared workspace abstraction.
- Paths are stable and product-facing, such as `/home/...`.
- Policy, onboarding, and tool descriptions can stay inside that
  workspace vocabulary.
- This is the better choice when the product does **not** grant shell
  access and wants a narrower mental model for the LLM.

The point of VFS is not "fake files." The point is that the agent sees
and reasons about a curated workspace shape rather than the raw host
filesystem.

---

## What host file tools are for

Host file tools are the right fit for **agents that intentionally work
with real OS paths**.

Characteristics:

- The agent is expected to read or write actual host locations.
- Paths are literal user or system paths, such as `~/Documents/...`.
- Policy and execution both reason in host-path space.
- This is the better choice when the product wants the LLM to operate on
  the host filesystem directly rather than through a workspace mount
  abstraction.

Host file tools are especially natural alongside shell-style workflows,
because both operate on the real filesystem vocabulary.

---

## Why they should not be used together

In a real product profile, do **not** expose both families to the same
LLM unless you have a very strong reason and have explicitly chosen to
accept the added prompt complexity.

The problem is not runtime enforcement. IntentFrame can enforce both.
The problem is the **LLM-facing mental model**.

If both families are present at once, the model must keep track of two
different path languages:

- workspace paths like `/home/project/file.py`
- host paths like `~/project/file.py`

That creates several failure modes:

1. Path confusion  
   The model writes `/home/script.sh` with `WRITE_FILE` and then tries
   to use that same string in a host-level context.

2. Prompt bloat  
   Tool descriptions and onboarding guardrails have to spend tokens
   explaining the difference between families instead of just teaching
   safe usage of the granted tools.

3. Tool-selection ambiguity  
   The model may choose the wrong family for a task that conceptually
   looks like "read a file", even though only one family matches the
   product's intended workflow.

4. Product drift  
   A combined test harness can quietly become a de facto product shape,
   and downstream agent developers inherit unnecessary complexity.

The clean rule is:

- if the product is workspace-first, expose VFS tools only
- if the product is host-files-first, expose host file tools only

The combined mode is useful for **testing and comparison**, but it is
not the recommended steady-state product surface.

---

## Relationship to `RUN_COMMAND`

`RUN_COMMAND` is its own tool family. It should be reasoned about
independently from file tools.

However, if a product grants `RUN_COMMAND`, host file tools are usually
the more coherent filesystem family to pair with it. Both operate on
real host paths, and neither requires the LLM to translate between a
workspace path vocabulary and a shell path vocabulary.

That does **not** mean every shell-enabled product must expose host file
tools. It means a product team should choose one filesystem mental model
deliberately, not mix both by default.

---

## Policy and onboarding implications

The runtime can enforce either family, or both, because the two families
stay disjoint in policy and checker wiring:

- `FileConstraints.allowed_paths` routes to `FileChecker`
- `HostFileConstraints.allowed_host_paths` routes to `HostFileChecker`

That enforcement separation is necessary, but it does not remove the
LLM-UX problem described above.

So the guidance is:

- runtime may support both families
- tests may exercise both families
- product prompts and tool lists should usually pick one family

Onboarding and tool docstrings should describe the **granted** family
directly, without forcing the model to learn a second adjacent family it
will not use.

---

## Testing the families separately

The standalone onboarding harness supports explicit filesystem-family
selection:

```bash
.venv/bin/python tests/test_onboarding_jarvis_policy.py --fs-mode vfs
.venv/bin/python tests/test_onboarding_jarvis_policy.py --fs-mode host
.venv/bin/python tests/test_onboarding_jarvis_policy.py --fs-mode none
.venv/bin/python tests/test_onboarding_jarvis_policy.py --fs-mode both
```

The script filters **both**:

- Jarvis `AgentCapabilities.action_types`
- the bootstrap policy's `allowed_actions`

This lets you inspect onboarding behavior for each family in isolation,
for the combined comparison case, or with no filesystem tools at all.

---

## Recommended rule of thumb

If you are defining a real agent profile and are unsure which family to
pick:

- choose **VFS** for workspace products
- choose **host file tools** for real-path products
- do **not** expose both to the same LLM by default

If you need both for debugging, evaluation, or migration work, keep that
shape confined to test harnesses and explicit developer-only profiles.
