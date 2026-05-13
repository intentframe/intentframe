# Policy control pane — CLI TODO

> **Status: NOT STARTED.** The policy YAML override mechanism works today
> (`~/.intentframe/policies/<agent_id>.yaml`). What's missing is the CLI
> surface for managing policies without hand-editing files and restarting.

---

## What exists today

- Users edit `~/.intentframe/policies/jarvis.yaml` by hand.
- Gateway loads the override on startup via `policy_registry.seeds.resolve_seed_path`.
- `intentframe> policies` lists active policies.
- `intentframe> bootstrap` re-seeds (but skips if policy already exists in registry).
- `intentframe> audit` shows allow/block history.

---

## TODO: Policy CLI commands

### `policy validate <path>`

- Dry-run validate a YAML without restarting the gateway.
- Calls `load_policy_seed(path)` and reports success or the exact error.
- No side effects — does not install or seed.

### `policy show <agent_id>`

- Print the currently active policy for an agent (resolved from registry, not disk).
- Shows which file it was loaded from (override vs builtin).

### `policy edit <agent_id>`

- Opens `~/.intentframe/policies/<agent_id>.yaml` in `$EDITOR`.
- If the override doesn't exist yet, copies the builtin there first.
- After editor closes, runs `policy validate` on the result.

### `policy diff <agent_id>`

- Shows the diff between the user's override and the packaged builtin.
- If no override exists, says so.

### `policy reset <agent_id>`

- Deletes `~/.intentframe/policies/<agent_id>.yaml`.
- Next gateway restart falls back to the packaged default.
- Asks for confirmation before deleting.

### `policy reload`

- Re-seeds the policy from disk into the running registry without a full
  gateway restart.
- Replaces the current `bootstrap` skip-if-exists behavior for the policy slot.

---

## TODO: Third-party agent policy install

### `policy install <path>`

- Reads `manifest.yaml` and `policy.yaml` from the agent directory.
- Validates that `policy.yaml:agent_id` matches `manifest.yaml:name`.
- Validates that every action in `policy.yaml` is declared in
  `manifest.yaml:capabilities.declared_actions`.
- Shows the user what the agent is requesting (actions, limits, constraints).
- On confirmation, copies to `~/.intentframe/policies/<agent_id>.yaml`.
- Seeds the policy into the registry.

### `policy uninstall <agent_id>`

- Removes the override file.
- Removes the policy from the registry.

---

## TODO: Gateway routes (if CLI avoids direct filesystem writes)

- `POST /policies/validate` — accepts YAML body, returns validation result.
- `POST /policies/reload` — re-reads override files and re-seeds.
- `POST /policies/install` — full install flow triggered from CLI.

---

## TODO: UI editor (future)

- Web-based or macOS-native policy editor.
- Visual toggle for safe/unsafe per action.
- Constraint editor with dropdowns for known values.
- Not blocking on any of the above CLI work.

---

## Design constraints

- The manifest is the ceiling (what the agent declares it needs).
- The policy is the floor (what the user actually grants).
- Users approve; agents request. Never the other way around.
- Conservative defaults for third-party agents: contact sources disabled,
  no broad path access, explicit opt-in required.
- Jarvis is the only agent auto-seeded by the gateway today. External agents
  must go through the install flow.
