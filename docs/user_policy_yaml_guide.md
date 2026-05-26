# Jarvis Policy YAML Guide

Your policy file tells IntentFrame what Jarvis is and isn't allowed to do on your Mac. You write it in YAML. If the file doesn't exist, Jarvis uses the safe defaults it ships with.

---

## Where to put the file

| Which Jarvis | File path |
|---|---|
| Normal Jarvis | `~/.intentframe/policies/jarvis.yaml` |
| Root-demo Jarvis | `~/.intentframe/policies/jarvis_root.yaml` |

Create the folder if it doesn't exist:

```bash
mkdir -p ~/.intentframe/policies
```

After saving your edits, restart the gateway for the new policy to take effect.

---

## How to start

Copy the default policy and edit it:

```bash
mkdir -p ~/.intentframe/policies
python -c "from jarvis.policies import builtin_policy_path; print(builtin_policy_path('user'))" \
  | xargs -I{} cp {} ~/.intentframe/policies/jarvis.yaml
```

Then open `~/.intentframe/policies/jarvis.yaml` in any text editor.

---

## The minimum valid file

```yaml
intentframe_schema_version: 1
agent_id: jarvis

allowed_actions:
  READ_HOST_FILE:
    safe: true
    constraints:
      allowed_host_paths:
        - "~/Documents/*"
```

Three rules that always apply:

1. `intentframe_schema_version: 1` is required at the top. Only `1` is valid today.
2. `agent_id` is required. Use `jarvis` for normal mode or `jarvis_root` for root-demo.
3. **Anything not listed under `allowed_actions` is blocked.** There is no default-allow.

---

## Top-level keys

These are the only supported top-level keys. Do not add your own top-level keys;
they are not part of the policy format.

| Key | Required | What it does |
|---|---|---|
| `intentframe_schema_version` | yes | Schema version. Always `1`. |
| `agent_id` | yes | `jarvis` or `jarvis_root` |
| `allowed_actions` | yes | What Jarvis can do |
| `intent_limits` | no | Plain-English rules the AI guardian reads |
| `domain_constraints` | no | Hard spending/deletion limits |
| `metadata` | no | Free-form notes (`note: my policy`) |

---

## Every action you can allow

Actions are listed under `allowed_actions` by their exact name. If a name isn't
on this list, it is not a supported IntentFrame action. Stick to these names.

### Files on your Mac (real paths like `~/Documents`)

> These require `allowed_host_paths` — see constraints section below.

| Action | What it does |
|---|---|
| `READ_HOST_FILE` | Read a file |
| `WRITE_HOST_FILE` | Create or overwrite a file |
| `DELETE_HOST_FILE` | Delete a file |
| `LIST_HOST_DIRECTORY` | List folder contents |

### Files in the virtual workspace (paths like `/home/`)

> These require `allowed_paths` — see constraints section below.

| Action | What it does |
|---|---|
| `READ_FILE` | Read a file in the workspace |
| `WRITE_FILE` | Create or overwrite a file in the workspace |
| `APPEND_ROW` | Append a row to a file |
| `DELETE_FILE` | Delete a file in the workspace |
| `LIST_DIRECTORY` | List workspace folder contents |

### Terminal

> Requires shell/capability constraints — see constraints section below.

| Action | What it does |
|---|---|
| `RUN_COMMAND` | Run a shell or Python command |

### Email

| Action | What it does | Write constraint needed? |
|---|---|---|
| `READ_EMAIL` | Read an email | no |
| `GET_EMAIL` | Fetch a specific email | no |
| `SEARCH_EMAIL` | Search emails | no |
| `DOWNLOAD_ATTACHMENT` | Download an attachment | no |
| `SEND_EMAIL` | Send an email | yes — `allowed_recipients` |
| `REPLY_EMAIL` | Reply to an email | yes — `allowed_recipients` |
| `FORWARD_EMAIL` | Forward an email | yes — `allowed_recipients` |
| `MARK_READ_EMAIL` | Mark as read | no |
| `MOVE_EMAIL` | Move to a folder | no |
| `DELETE_EMAIL` | Delete an email | no |

### Calendar

| Action | What it does |
|---|---|
| `LIST_CALENDARS` | List your calendars |
| `LIST_EVENTS` | List events |
| `SEARCH_EVENTS` | Search events |
| `CREATE_EVENT` | Create an event |
| `UPDATE_EVENT` | Edit an event |
| `DELETE_EVENT` | Delete an event |

> Optionally restrict to specific calendars using `allowed_calendars`.

### Reminders

| Action | What it does |
|---|---|
| `LIST_REMINDER_LISTS` | List reminder lists |
| `LIST_REMINDERS` | List reminders |
| `CREATE_REMINDER` | Create a reminder |
| `UPDATE_REMINDER` | Edit a reminder |
| `COMPLETE_REMINDER` | Mark a reminder complete |
| `DELETE_REMINDER` | Delete a reminder |

### Notes

| Action | What it does |
|---|---|
| `LIST_NOTES` | List notes |
| `READ_NOTE` | Read a note |
| `CREATE_NOTE` | Create a note |
| `DELETE_NOTE` | Delete a note |

### Contacts

| Action | What it does |
|---|---|
| `SEARCH_CONTACTS` | Search contacts |
| `GET_CONTACT` | Get a contact |
| `ADD_CONTACT` | Add a contact |
| `UPDATE_CONTACT` | Edit a contact |
| `DELETE_CONTACT` | Delete a contact |

### Messages (iMessage / SMS)

| Action | What it does |
|---|---|
| `READ_MESSAGES` | Read messages |
| `SEND_MESSAGE` | Send a message — requires `allowed_contacts` |

### Browser

| Action | What it does |
|---|---|
| `GET_PAGE_CONTENT` | Read a page's text |
| `SEARCH_WEB` | Run a web search |
| `OPEN_URL` | Open a URL in the browser — optionally restrict with `allowed_urls` |

### Clipboard

| Action | What it does |
|---|---|
| `GET_CLIPBOARD` | Read clipboard contents |
| `SET_CLIPBOARD` | Write to clipboard |

### Spotlight search

| Action | What it does |
|---|---|
| `SEARCH_SPOTLIGHT` | Run a Spotlight search |

### Notifications

| Action | What it does |
|---|---|
| `SHOW_NOTIFICATION` | Show a macOS notification |

### HTTP / API

| Action | What it does |
|---|---|
| `HTTP_GET` | Make an HTTP GET request |
| `HTTP_POST` | Make an HTTP POST request |
| `HTTP_PUT` | Make an HTTP PUT request |
| `HTTP_DELETE` | Make an HTTP DELETE request |
| `PAY_INVOICE` | Pay an invoice |

> Optionally restrict with `max_amount` and `allowed_endpoints`.

### Talk to you

| Action | What it does |
|---|---|
| `ASK_USER` | Ask you a question |
| `SHOW_MESSAGE` | Show you a message |
| `GET_CONFIRMATION` | Ask for yes/no confirmation |
| `SHOW_OPTIONS` | Show a list of options to pick from |

### System settings

| Action | What it does |
|---|---|
| `GET_SYSTEM_INFO` | Read system info |
| `GET_VOLUME` | Read current volume |
| `SET_VOLUME` | Set volume |
| `GET_MUTE` | Read mute state |
| `TOGGLE_MUTE` | Toggle mute |
| `GET_BRIGHTNESS` | Read brightness |
| `SET_BRIGHTNESS` | Set brightness |
| `GET_DARK_MODE` | Read dark-mode state |
| `TOGGLE_DARK_MODE` | Toggle dark mode |

---

## The `safe` flag

Every action entry requires a `safe` field:

```yaml
SOME_ACTION:
  safe: true   # or false
```

| `safe: true` | The action is approved to run after a fast deterministic check only. No AI review. Use for reads and harmless display actions. |
|---|---|
| `safe: false` | The AI Guardian reviews every run of this action before it executes. Use for anything that writes, deletes, sends, or runs code. |

> Changing a write action to `safe: true` removes AI oversight. Only do it if you are certain you want every instance of that action to skip review.

---

## Constraints

Constraints narrow what an allowed action can touch. They are optional except where noted.

### Real-path files — `allowed_host_paths`

Use with: `READ_HOST_FILE`, `WRITE_HOST_FILE`, `DELETE_HOST_FILE`, `LIST_HOST_DIRECTORY`

```yaml
READ_HOST_FILE:
  safe: true
  constraints:
    allowed_host_paths:
      - "~/Documents/*"
      - "~/Projects/intentframe/*"
```

Rules:
- At least one path is required if you include `constraints`.
- `~` is supported and expanded at runtime.
- Use `dir/*` to allow a directory's children. **Do not use trailing slashes** (`dir/` is rejected — use `dir/*`).
- `dir/*` matches direct children only. Use `dir/**` for all descendants.
- Paths outside the listed patterns are blocked even if the action is allowed.

### Virtual-workspace files — `allowed_paths`

Use with: `READ_FILE`, `WRITE_FILE`, `APPEND_ROW`, `DELETE_FILE`, `LIST_DIRECTORY`

```yaml
READ_FILE:
  safe: true
  constraints:
    allowed_paths:
      - "/home/Documents/"
      - "/home/Projects/intentframe/"
```

> **Do not mix `allowed_paths` and `allowed_host_paths` on the same action.**
> They are for different file systems.

### Terminal — `blocked_patterns`, `deny_capabilities`, `allowed_commands`

Use with: `RUN_COMMAND`

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
      - "capability:system_mutate:firewall"
      - "capability:data_read:credential_material"
    allowed_commands: []
```

| Field | What it does |
|---|---|
| `blocked_patterns` | Any command containing one of these strings is blocked immediately, before any other check. |
| `deny_capabilities` | Block commands that are tagged with any of these capability tags. See the full list below. |
| `allowed_commands` | If non-empty, the command must match at least one glob pattern here to run. Leave `[]` to allow all non-blocked commands. |
| `allow_capabilities` | Advanced: whitelist mode for capabilities. Leave `[]` for normal use. |

### Email recipients

Use with: `SEND_EMAIL`, `REPLY_EMAIL`, `FORWARD_EMAIL`

```yaml
SEND_EMAIL:
  safe: false
  constraints:
    allowed_recipients:
      - "alice@example.com"
      - "*@mycompany.com"
    recipient_sources:
      - source: contacts_all
        filter: ""
        enabled: true
```

| Field | What it does |
|---|---|
| `allowed_recipients` | Explicit email addresses or patterns (supports `*` wildcard). |
| `recipient_sources` | Dynamically pull allowed recipients from a contact list. |

`recipient_sources` values for `source`:

| Value | Who it allows |
|---|---|
| `contacts_all` | Everyone in your Contacts |
| `contacts_group` | A specific Contacts group — set `filter: "Group Name"` |

To disable a source without deleting it, set `enabled: false`.

Contact list resolution (`recipient_sources`, `contact_sources`) happens at
runtime when the email or message bundle enforces constraints — not when the
policy registry stores the policy. See
`intentframe_native_bundles/platform/contacts_client.py`.

### Message contacts

Use with: `SEND_MESSAGE`

```yaml
SEND_MESSAGE:
  safe: false
  constraints:
    allowed_contacts:
      - "Alice"
      - "+15551234567"
    contact_sources:
      - source: contacts_all
        filter: ""
        enabled: true
```

Same structure as email constraints, but for iMessage/SMS. `allowed_contacts` can be a name, phone number, or email.

### Calendar

Use with any calendar action:

```yaml
LIST_EVENTS:
  safe: true
  constraints:
    allowed_calendars:
      - "Work"
      - "Family"
```

Omit `constraints` entirely to allow all calendars.

### Browser URLs

Use with: `OPEN_URL`, `SEARCH_WEB`, `GET_PAGE_CONTENT`

```yaml
OPEN_URL:
  safe: false
  constraints:
    allowed_urls:
      - "https://github.com/*"
      - "https://docs.google.com/*"
```

At least one URL is required if you include `constraints`.

### HTTP / API

Use with: `HTTP_GET`, `HTTP_POST`, `HTTP_PUT`, `HTTP_DELETE`, `PAY_INVOICE`

```yaml
PAY_INVOICE:
  safe: false
  constraints:
    max_amount: 5000.0
    allowed_endpoints:
      - "https://api.stripe.com/*"
```

Both fields are optional.

---

## Intent limits

Intent limits are plain-English rules the AI Guardian reads when deciding whether to allow an action. The Guardian understands them in natural language — write them the way you'd say them to another person.

```yaml
intent_limits:
  - limit_id: my-unique-id
    domain: spending
    description: Short description of the rule
    raw: Write your rule here in plain English
    threshold: 500.0
    effect: block
    scope: per_action
```

| Field | Required | What to put |
|---|---|---|
| `limit_id` | yes | Any unique string you choose (`max-spend`, `no-bulk-delete`, etc.) |
| `domain` | yes | A category label. Common values: `spending`, `deletion`. You can write your own (`email`, `privacy`, etc.). |
| `description` | yes | One short sentence describing the rule |
| `raw` | yes | Your rule in plain English — this is what the Guardian actually reads |
| `threshold` | no | A number limit (e.g. dollar amount). Leave out if not relevant. |
| `pattern` | no | A string pattern for the rule. Leave out if not relevant. |
| `effect` | no | `block` (default) or `require_confirmation` |
| `scope` | no | `per_action` (default, only value used today) |

Examples:

```yaml
intent_limits:
  - limit_id: max-spend-per-txn
    domain: spending
    description: Maximum $500 per transaction
    raw: Don't spend more than $500 on a single thing without asking me first
    threshold: 500.0
    effect: block
    scope: per_action

  - limit_id: confirm-before-delete
    domain: deletion
    description: Always confirm before deleting
    raw: Ask me before deleting anything I can't get back
    effect: require_confirmation
    scope: per_action

  - limit_id: no-bulk-email
    domain: email
    description: No sending to more than 5 people at once
    raw: Don't send email to more than 5 recipients at the same time without asking me
    effect: block
    scope: per_action
```

---

## Domain constraints

Domain constraints are hard, deterministic limits that fire before the AI even looks at the action. Two domains are supported today.

### `finance` — spending limits

```yaml
domain_constraints:
  finance:
    max_amount: 5000.0
    allowed_currencies:
      - USD
      - EUR
    allowed_recipients:
      - "vendor@stripe.com"
```

| Field | What it does |
|---|---|
| `max_amount` | Block any payment above this amount |
| `allowed_currencies` | Only allow these currency codes. Omit to allow any. |
| `allowed_recipients` | Only allow payments to these addresses/IDs. Omit to allow any. |

### `deletion` — deletion guards

```yaml
domain_constraints:
  deletion:
    require_confirmation: true
    block_irreversible: false
    allowed_paths:
      - "~/Downloads/*"
```

| Field | What it does |
|---|---|
| `require_confirmation` | Always ask for confirmation before deleting. Default `true`. |
| `block_irreversible` | Block deletions that can't be undone. Default `false`. |
| `allowed_paths` | Only allow deletions within these paths. Omit to allow deletions anywhere the action itself permits. |

---

## Full list of `deny_capabilities` for `RUN_COMMAND`

Paste any of these into `RUN_COMMAND.constraints.deny_capabilities`. They block specific kinds of shell commands before any AI review. Only these exact strings are valid — typos are silently ignored.

**Other script languages (not Python/shell)**
```
capability:script_execution:node
capability:script_execution:ruby
capability:script_execution:perl
capability:script_execution:java
capability:script_execution:go
capability:script_execution:dotnet
capability:script_execution:php
capability:script_execution:lua
capability:script_execution:r
capability:script_execution:julia
capability:script_execution:swift
capability:script_execution:deno_bun
capability:script_execution:local_binary
```

**Compiling code**
```
capability:compilation
```

**Piping code into another interpreter**
```
capability:stdin_exec:node
capability:stdin_exec:ruby
capability:stdin_exec:perl
capability:stdin_exec:php
```

**Installing packages from non-Python/shell ecosystems**
```
capability:package_install:npm
capability:package_install:gem
capability:package_install:cargo
capability:package_install:go
capability:package_install:composer
```

**Reading sensitive data**
```
capability:data_read:browser_cookies
capability:data_read:browser_profile_data
capability:data_read:browser_session_data
capability:data_read:auth_authority
capability:data_read:credential_material
capability:data_read:shell_history
capability:data_read:db_client_history
capability:data_read:messaging_history
capability:data_read:personal_records
capability:data_read:dotfile_secrets
capability:data_read:cloud_tokens
capability:data_read:password_manager_export
capability:data_read:process_env
capability:data_read:ssh_known_hosts
capability:data_read:mail_store
capability:data_read:process_memory
```

**Changing system settings**
```
capability:system_mutate:host_network_config
capability:system_mutate:hostname
capability:system_mutate:time_sync
capability:system_mutate:security_daemon
capability:system_mutate:browser_security_pref
capability:system_mutate:firewall
capability:system_mutate:hosts_file
capability:system_mutate:privilege_config
capability:system_mutate:user_account
capability:system_mutate:remote_access
capability:system_mutate:disk_encryption
capability:system_mutate:kernel_tunable
capability:system_mutate:persistence
capability:system_mutate:mdm_profile
capability:system_mutate:boot_policy
capability:system_mutate:audit_log
capability:system_mutate:tcc_privacy
capability:system_mutate:backup
capability:system_mutate:installer_pkg
capability:system_mutate:kernel_extension
capability:system_mutate:service_mgmt
capability:system_mutate:launchd_mutation
capability:system_mutate:cron_mutation
capability:system_mutate:browser_extension
capability:system_mutate:screen_sharing
capability:system_mutate:print_config
capability:system_mutate:radio_power
capability:system_mutate:ca_trust
capability:system_mutate:shell_init
capability:system_mutate:history_tamper
```

**Sending data out of your Mac**
```
capability:network_exfil:http_upload
capability:network_exfil:file_transfer_outbound
capability:network_exfil:ssh_tunnel
capability:network_exfil:cloud_upload
```

> The default Jarvis policy already denies all of the above. If you're editing the default, removing something from this list is a security decision.

---

## What you cannot write

Do not write any of these in a policy file:

- Use an action name not in the tables above.
- Use `allowed_paths` on a host-file action (`READ_HOST_FILE` etc.) — those
  require `allowed_host_paths`.
- Use `allowed_host_paths` on a virtual-file action (`READ_FILE` etc.) — those
  require `allowed_paths`.
- Write a trailing-slash path like `~/Documents/` — use `~/Documents/*`.
- Set `intentframe_schema_version` to anything other than `1`.
- Set `agent_id` to anything other than `jarvis` or `jarvis_root`.
- Add unknown top-level keys.
- Add unknown constraint fields (for example, inventing your own field names
  inside `constraints`).

Some unsupported fields fail immediately and some are ignored by today's YAML
loader. Treat both cases the same: if it is not listed in this guide, don't put
it in the file.

---

## A complete example

This is a moderately locked-down personal policy. Save it as `~/.intentframe/policies/jarvis.yaml`.

```yaml
intentframe_schema_version: 1
agent_id: jarvis

metadata:
  note: My custom Jarvis policy

allowed_actions:

  # --- Files ---
  READ_HOST_FILE:
    safe: true
    constraints:
      allowed_host_paths:
        - "~/*"
  LIST_HOST_DIRECTORY:
    safe: true
    constraints:
      allowed_host_paths:
        - "~/*"
  WRITE_HOST_FILE:
    safe: false
    constraints:
      allowed_host_paths:
        - "~/Documents/*"
        - "~/Downloads/*"
  DELETE_HOST_FILE:
    safe: false
    constraints:
      allowed_host_paths:
        - "~/Downloads/*"

  # --- Terminal ---
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
        - "capability:data_read:browser_cookies"
        - "capability:data_read:cloud_tokens"
        - "capability:network_exfil:http_upload"
        - "capability:network_exfil:ssh_tunnel"
        - "capability:system_mutate:firewall"
        - "capability:system_mutate:hosts_file"
        - "capability:system_mutate:user_account"
        - "capability:system_mutate:persistence"
        - "capability:system_mutate:launchd_mutation"
        - "capability:script_execution:node"
        - "capability:script_execution:ruby"
        - "capability:script_execution:perl"
        - "capability:compilation"

  # --- Talk to me ---
  ASK_USER:
    safe: true
  SHOW_MESSAGE:
    safe: true
  GET_CONFIRMATION:
    safe: true
  SHOW_OPTIONS:
    safe: true

  # --- Clipboard ---
  GET_CLIPBOARD:
    safe: true
  SET_CLIPBOARD:
    safe: true

  # --- Search / notify ---
  SEARCH_SPOTLIGHT:
    safe: true
  SHOW_NOTIFICATION:
    safe: true

  # --- Calendar (reads only) ---
  LIST_CALENDARS:
    safe: true
  LIST_EVENTS:
    safe: true
  SEARCH_EVENTS:
    safe: true

  # --- Reminders (reads only) ---
  LIST_REMINDER_LISTS:
    safe: true
  LIST_REMINDERS:
    safe: true

  # --- Notes (reads only) ---
  LIST_NOTES:
    safe: true
  READ_NOTE:
    safe: true

  # --- Messages (reads only) ---
  READ_MESSAGES:
    safe: true

  # --- Contacts (reads only) ---
  SEARCH_CONTACTS:
    safe: true
  GET_CONTACT:
    safe: true

  # --- Email reads ---
  SEARCH_EMAIL:
    safe: true
  READ_EMAIL:
    safe: true
  GET_EMAIL:
    safe: true
  DOWNLOAD_ATTACHMENT:
    safe: true

  # --- Email writes (contacts only) ---
  SEND_EMAIL:
    safe: false
    constraints:
      allowed_recipients: []
      recipient_sources:
        - source: contacts_all
          filter: ""
          enabled: true

  # --- System reads ---
  GET_SYSTEM_INFO:
    safe: true
  GET_VOLUME:
    safe: true
  GET_BRIGHTNESS:
    safe: true
  GET_MUTE:
    safe: true
  GET_DARK_MODE:
    safe: true

  # --- HTTP reads ---
  HTTP_GET:
    safe: true

intent_limits:
  - limit_id: max-spend-per-txn
    domain: spending
    description: Maximum $500 per transaction
    raw: Don't spend more than $500 on a single thing without asking me first
    threshold: 500.0
    effect: block
    scope: per_action

  - limit_id: confirm-before-delete
    domain: deletion
    description: Always confirm before deleting
    raw: Ask me before deleting anything I can't get back
    effect: require_confirmation
    scope: per_action
```

---

## How to apply changes

```bash
# 1. Edit your file
$EDITOR ~/.intentframe/policies/jarvis.yaml

# 2. Restart the gateway (quit the CLI first if it's running, then restart)
uv run intentframe-gateway-cli

# 3. Confirm it loaded
intentframe> policies
```

The gateway checks for your override file every time it starts. If you see an error, it will tell you exactly what's wrong in the file.

---