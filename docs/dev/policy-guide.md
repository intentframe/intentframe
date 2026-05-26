# IntentFrame Policy Guide

This guide explains how users configure IntentFrame policy for Jarvis today, how
policy updates are loaded, and what still needs to be built for third-party
agent policy installation.

IntentFrame policy answers one question: when an agent proposes an action, is
that action allowed for this user and this agent?

Jarvis is the reference agent, but the policy model is already agent-scoped. The
policy registry stores policy by `(user_id, agent_id)`, so Jarvis and future
third-party agents can have separate policies for the same user.

## Current State

The latest policy-loading refactor moved Jarvis policy out of hardcoded Python
and into YAML.

The important pieces are:

- `jarvis_pa/jarvis/policies/jarvis.yaml`: packaged user-mode Jarvis policy.
- `jarvis_pa/jarvis/policies/jarvis_root.yaml`: packaged root-demo Jarvis policy.
- `policy_registry/seeds/loader.py`: YAML → `UserPolicy` (opaque constraint dicts; bundle shape validation via `validate_policy_against_registry`).
- `policy_registry/seeds/resolver.py`: resolves user override files under
  `~/.intentframe/policies/`.
- `intentframe_gateway/bootstrap.py`: seeds Jarvis policy and workspace on
  gateway startup.
- `jarvis_pa/seed_policies.py`: development convenience script using the same
  loader as the gateway.

The gateway auto-seeds only Jarvis today. External agents are mentioned in the
loader API, but policy install and review flows are still TODOs.

## Packaged Jarvis Policies

Jarvis ships with two policy variants.

User mode is the default:

```text
jarvis_pa/jarvis/policies/jarvis.yaml
agent_id: jarvis
```

It gives Jarvis home-scoped host-file access, standard personal-assistant
actions, and conservative guards around shell, email, messages, deletion, and
spending.

Root mode is for the root demo:

```text
jarvis_pa/jarvis/policies/jarvis_root.yaml
agent_id: jarvis_root
```

It is selected with `JARVIS_VARIANT=root` or the gateway CLI root profile. Do not
use root mode as a normal daily-driver default unless you understand the root
demo execution model.

## Do Not Edit Packaged Policies

Do not edit files under `jarvis_pa/jarvis/policies/` for local customization.
Those files are source-controlled package defaults and can change when you pull
or reinstall IntentFrame.

Use an override file instead:

```text
~/.intentframe/policies/<agent_id>.yaml
```

For normal Jarvis:

```text
~/.intentframe/policies/jarvis.yaml
```

For root-demo Jarvis:

```text
~/.intentframe/policies/jarvis_root.yaml
```

The resolver checks the override path first. If an override exists, it wins over
the packaged YAML.

## Create A Jarvis Policy Override

Start by copying the packaged default:

```bash
mkdir -p ~/.intentframe/policies
python -c "from jarvis.policies import builtin_policy_path; print(builtin_policy_path('user'))" \
  | xargs -I{} cp {} ~/.intentframe/policies/jarvis.yaml
```

Then edit:

```bash
$EDITOR ~/.intentframe/policies/jarvis.yaml
```

Restart the gateway after changing the override:

```bash
uv run intentframe-gateway-cli
```

Inside the CLI, you can inspect active policy state with:

```text
intentframe> policies
```

## Loading Behavior

Policy loading is intentionally simple.

For Jarvis, `intentframe_gateway/bootstrap.py` resolves:

1. Active variant: `JARVIS_VARIANT`, defaulting to `user`.
2. User id: gateway identity config, with environment fallback.
3. Agent id: `jarvis` for user mode or `jarvis_root` for root mode.
4. YAML path: user override first, packaged policy second.
5. Validated policy: `policy_registry.seeds.load_policy_seed(...)` (registry fields + bundle constraint schemas).

The bootstrapper then posts the policy into the policy registry.

Important current behavior: bootstrap is idempotent and checks whether a policy
already exists for `(user_id, agent_id)`. If it exists, bootstrap skips seeding.
For a clean policy override update, quit and restart the gateway so the in-memory
registry is rebuilt and the override is seeded.

## Policy File Shape

Every policy YAML must declare the schema version and agent id:

```yaml
intentframe_schema_version: 1
agent_id: jarvis

metadata:
  note: My local Jarvis policy

allowed_actions:
  READ_HOST_FILE:
    safe: true
    constraints:
      allowed_host_paths:
        - "~/*"

intent_limits:
  - limit_id: confirm-before-delete
    domain: deletion
    description: Always confirm before deleting
    raw: Ask me before deleting anything I can't get back
    effect: require_confirmation
    scope: per_action
```

`intentframe_schema_version` is required. If the file is missing it, or declares
a version this build does not support, the loader fails with a friendly migration
error.

`agent_id` must match the agent the policy governs. Jarvis user mode uses
`jarvis`; root-demo mode uses `jarvis_root`.

## Safe And Unsafe Actions

Each action in `allowed_actions` has a `safe` flag.

`safe: true` means the action can take the deterministic fast path when its
constraints pass. Typical examples are reads, listing resources, or showing a
message.

`safe: false` means the action is consequential and must go through the stronger
review path. Typical examples are writes, sending messages, sending email,
deleting data, running commands, and mutating system settings.

Changing `safe: false` to `safe: true` is a security decision. Do it only for
actions whose effects you are comfortable allowing without semantic review.

## File Access

Jarvis uses host-file tools in the default policy:

```yaml
READ_HOST_FILE:
  safe: true
  constraints:
    allowed_host_paths:
      - "~/*"

WRITE_HOST_FILE:
  safe: false
  constraints:
    allowed_host_paths:
      - "~/*"
```

Use `allowed_host_paths` for host-file actions. Do not use `allowed_paths` for
these actions. The loader relies on the field name to choose the correct
constraint model.

Common examples:

```yaml
allowed_host_paths:
  - "~/Documents/**"
  - "~/Projects/intentframe/**"
```

Keep path scopes as narrow as the job allows.

## Shell Commands

Shell policy lives under `RUN_COMMAND`.

```yaml
RUN_COMMAND:
  safe: false
  constraints:
    blocked_patterns:
      - sudo
      - "rm -rf /"
      - mkfs
      - "dd if="
      - "> /dev/"
      - "chmod 777"
    deny_capabilities:
      - "capability:data_read:credential_material"
      - "capability:network_exfil:http_upload"
      - "capability:system_mutate:firewall"
```

`blocked_patterns` are direct string-level hard blocks.

`deny_capabilities` are command-shield capability tags. The default list is
mirrored from `intentframe_native_bundles.actions.terminal.capabilities.DEFAULT_TERMINAL_DENY_CAPABILITIES`
and pinned by tests. If you change the default deny surface in the codebase,
update the capability constant first and keep the YAML parity test passing.

For a local user override, adding more denied capabilities is usually safer than
removing existing ones.

## Email And Messages

Jarvis write actions for email and messages are unsafe by default.

Email write actions can constrain recipients:

```yaml
SEND_EMAIL:
  safe: false
  constraints:
    allowed_recipients:
      - "alice@example.com"
    recipient_sources:
      - source: contacts_all
        filter: ""
        enabled: false
```

Message write actions can constrain contacts:

```yaml
SEND_MESSAGE:
  safe: false
  constraints:
    allowed_contacts:
      - "Alice"
    contact_sources:
      - source: contacts_all
        filter: ""
        enabled: false
```

To allow everyone in Contacts, enable the `contacts_all` source. To keep the
policy narrow, leave contact sources disabled and list explicit recipients or
contacts.

`recipient_sources` and `contact_sources` are stored opaquely in the policy
registry and resolved at runtime by the email and message bundles during
`enforce_constraints` (via `intentframe_native_bundles/platform/contacts_client.py`).
The registry does not expand contact lists at write time.

## Intent Limits

`intent_limits` are plain-English rules the Guardian evaluates for actions where
meaning matters.

Example:

```yaml
intent_limits:
  - limit_id: max-spend-per-txn
    domain: spending
    description: Maximum $500 per transaction
    raw: Don't spend more than $500 on a single thing without asking me
    threshold: 500.0
    effect: block
    scope: per_action
```

Use `raw` for the policy sentence you would say as the owner. The Guardian reads
that text as policy context.

Common effects:

- `block`: deny matching actions.
- `require_confirmation`: require user confirmation when supported by the
  action flow.

## Validate A Policy YAML

There is no dedicated end-user `policy validate` CLI command yet. Developers can
validate a YAML with the same loader the gateway uses:

```bash
python - <<'PY'
from pathlib import Path
from policy_registry.seeds import load_policy_seed

policy = load_policy_seed(Path("~/.intentframe/policies/jarvis.yaml").expanduser())
print(policy.model_dump(mode="json", exclude={"created_at"}))
PY
```

If the YAML has a schema-version problem, unknown fields, invalid constraints,
or an action shape Pydantic cannot validate, this command fails before the
gateway tries to seed it.

## External Agent Policy TODOs

The policy registry already supports multiple agents through `(user_id,
agent_id)`. The missing work is the user-facing installation and review surface
for third-party agents.

Recommended TODOs:

- Define a bundled `policy.yaml` convention for external agents, next to their
  `manifest.yaml`.
- Require `policy.yaml:agent_id` to match `manifest.yaml:name`.
- Require every action requested in `policy.yaml` to be declared in
  `manifest.yaml:capabilities.declared_actions`.
- Treat the manifest as the maximum capability declaration and the policy as the
  user-approved subset.
- Add a `policy install <path-or-package>` CLI flow that loads the manifest,
  loads the proposed policy, shows the requested actions and limits, and asks
  for user confirmation.
- Store the approved policy as `~/.intentframe/policies/<agent_id>.yaml`.
- Add `policy show <agent_id>`, `policy edit <agent_id>`,
  `policy diff <agent_id>`, `policy reset <agent_id>`, and
  `policy validate <path>` commands.
- Add gateway routes for policy review/install if the CLI should avoid direct
  filesystem writes.
- Add tests that prove manifest-declared actions and policy-requested actions
  cannot drift.

A future external agent package should look like:

```text
external_agents/my_agent/
  manifest.yaml
  policy.yaml
  agent.py
```

Example proposed policy:

```yaml
intentframe_schema_version: 1
agent_id: invoice_bot

metadata:
  description: Proposed default policy for invoice processing
  author: intentframe-demo

allowed_actions:
  READ_FILE:
    safe: true
    constraints:
      allowed_paths:
        - "/invoices/**"
  ASK_USER:
    safe: true
  PAY_INVOICE:
    safe: false
  SEND_EMAIL:
    safe: false
    constraints:
      allowed_recipients: []
      recipient_sources:
        - source: contacts_all
          filter: ""
          enabled: false

intent_limits:
  - limit_id: invoice-cap
    domain: spending
    description: Maximum $5000 per invoice
    raw: Do not pay more than $5000 for any single invoice
    threshold: 5000.0
    effect: block
    scope: per_action
```

The default stance for third-party agents should be conservative. Agent authors
can propose capabilities; users approve the policy that actually governs the
agent.

