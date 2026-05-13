# Jarvis Config YAML Guide

`~/.jarvis/config.yaml` controls how Jarvis runs: which AI model it uses, how often it checks in, where it keeps its memory, and more.

**This file does not control what Jarvis is allowed to do.** That's the policy file at `~/.intentframe/policies/jarvis.yaml`. See `docs/user_policy_yaml_guide.md`.

---

## Where to put the file

```
~/.jarvis/config.yaml
```

Create the folder if it doesn't exist:

```bash
mkdir -p ~/.jarvis
```

The file is optional. If it doesn't exist, Jarvis uses built-in defaults for everything.

---

## The minimum file you can write

Everything is optional. Set only what you want to change.

```yaml
model: gpt-4o
heartbeat_enabled: false
```

---

## How to apply changes

Edit the file and restart the gateway:

```bash
$EDITOR ~/.jarvis/config.yaml
uv run intentframe-gateway-cli
```

---

## Every setting you can use

Set only what you want to change. Anything not in the file stays at its default.
Settings not listed in this guide are ignored.

### Identity

Most users should leave these alone. Jarvis and the IntentFrame policy slot must
agree on identity, or actions may be blocked because no matching policy is found.

| Setting | Default | What to write |
|---|---|---|
| `agent_id` | `jarvis` | Usually leave alone |
| `user_id` | `jarvis_default` | Usually leave alone |

```yaml
agent_id: jarvis
user_id: jarvis_default
```

---

### Model

Which AI model Jarvis uses to think and respond.

| Setting | Default | What to write |
|---|---|---|
| `model` | `gpt-5-mini-2025-08-07` | Any OpenAI model ID, e.g. `gpt-4o` |
| `sub_agent_model` | `gpt-5-mini-2025-08-07` | Model used for focused sub-tasks |

```yaml
model: gpt-4o
sub_agent_model: gpt-4o-mini
```

`model` is what Jarvis uses for normal conversation. `sub_agent_model` is used when Jarvis delegates a focused sub-task to a specialized inner agent.

The IntentFrame Guardian and Analysis Engine have their own model configuration separate from Jarvis. Changing `model` here only affects Jarvis's thinking, not the security review layers.

---

### Context window

How much conversation Jarvis keeps in memory at once.

| Setting | Default | What to write |
|---|---|---|
| `context_window_tokens` | `128000` | Integer matching your model's context limit |
| `max_history_share` | `0.5` | Fraction of window used for history. `0.0` to `1.0` |
| `compaction_threshold` | `0.8` | When compaction starts. `0.0` to `1.0` |

```yaml
context_window_tokens: 128000
max_history_share: 0.5
compaction_threshold: 0.8
```

If you switch to a model with a smaller context window, lower `context_window_tokens` to match. Set `max_history_share` lower if you want Jarvis to keep less conversation history.

---

### Memory search

Controls how Jarvis retrieves things it has learned about you.

| Setting | Default | What to write |
|---|---|---|
| `embedding_model` | `text-embedding-3-small` | Any OpenAI embedding model |
| `embedding_dims` | `1536` | Must match the embedding model's output size |
| `chunk_size_tokens` | `400` | Integer |
| `chunk_overlap_tokens` | `80` | Integer |
| `hybrid_vector_weight` | `0.7` | `0.0` to `1.0` |
| `hybrid_text_weight` | `0.3` | `0.0` to `1.0` |
| `search_max_results` | `6` | Integer |
| `search_min_score` | `0.35` | `0.0` to `1.0` |
| `search_candidate_multiplier` | `4` | Integer |

Most users should leave these alone. The only common reason to change them:

- **Better recall** — raise `search_max_results`, lower `search_min_score`.
- **More precise recall** — raise `search_min_score`.
- **Changed embedding model** — update `embedding_model` and set `embedding_dims` to match.

If you change `embedding_model`, you **must** also update `embedding_dims` to the model's output dimension, or searches will silently return wrong results.

---

### Auto-capture

How Jarvis decides which messages to automatically save to memory.

| Setting | Default | What to write |
|---|---|---|
| `auto_capture_min_len` | `10` | Integer (minimum characters) |
| `auto_capture_max_len` | `500` | Integer (maximum characters) |

Leave these at defaults unless Jarvis is capturing too much or too little.

---

### Heartbeat

Whether Jarvis periodically checks in on its own.

| Setting | Default | What to write |
|---|---|---|
| `heartbeat_enabled` | `true` | `true` or `false` |
| `heartbeat_interval_minutes` | `30` | Integer (minutes between check-ins) |
| `heartbeat_active_hours_start` | `"08:00"` | Quoted `"HH:MM"` (24h) |
| `heartbeat_active_hours_end` | `"22:00"` | Quoted `"HH:MM"` (24h) |
| `heartbeat_ack_max_chars` | `50` | Max characters in a heartbeat acknowledgement |

```yaml
# Disable heartbeat entirely
heartbeat_enabled: false
```

```yaml
# Only check in during work hours, once an hour
heartbeat_enabled: true
heartbeat_interval_minutes: 60
heartbeat_active_hours_start: "09:00"
heartbeat_active_hours_end: "18:00"
```

Always quote the time strings with double quotes.

---

### Session and server

How long Jarvis waits for things and when it drops idle sessions.

| Setting | Default | What to write |
|---|---|---|
| `chat_timeout_seconds` | `600` | Integer (seconds) |
| `session_idle_expire_minutes` | `60` | Integer (minutes) |

```yaml
# More patient with long tasks, shorter idle expiry
chat_timeout_seconds: 900
session_idle_expire_minutes: 30
```

---

### Paths

Where Jarvis keeps its workspace and how it connects to the runtime.

| Setting | Default | What to write |
|---|---|---|
| `workspace_dir` | `~/.jarvis` | Any directory. `~` is expanded. |
| `socket_path` | `~/.intentframe/run/intentframe.sock` | Leave unchanged in normal use |

```yaml
workspace_dir: ~/Library/Application Support/Jarvis
```

`socket_path` is where Jarvis connects to the IntentFrame runtime. Don't change it unless you've moved the IntentFrame socket deliberately.

---

### Custom skills

Extra directories Jarvis looks in for skill definitions.

| Setting | Default | What to write |
|---|---|---|
| `skill_dirs` | `[]` | List of directory paths |

```yaml
skill_dirs:
  - ~/my-jarvis-skills
```

If left empty, Jarvis automatically uses its built-in skills folder plus `~/.jarvis/skills`.

---

## What goes elsewhere, not here

| If you want to… | Where it goes |
|---|---|
| Add your OpenAI API key | `intentframe> vault set openai api_key` |
| Add a Telegram bot | `intentframe> vault set telegram bot_token` |
| Add an email account | `intentframe> vault set email.<addr> password` then `intentframe> edi add <addr>` |
| Allow or block what Jarvis can do | `~/.intentframe/policies/jarvis.yaml` |
| Change IntentFrame system settings | `intentframe> config set <key> <value>` |

---

## Quick sanity table

| If you want to… | Edit this | Or run this |
|---|---|---|
| Change Jarvis's model | `~/.jarvis/config.yaml` → `model` | n/a |
| Stop Jarvis from checking in on its own | `~/.jarvis/config.yaml` → `heartbeat_enabled: false` | n/a |
| Allow or deny what Jarvis can do | `~/.intentframe/policies/jarvis.yaml` | n/a |
| Add an OpenAI key | n/a | `intentframe> vault set openai api_key` |
| Add a Telegram bot | n/a | `intentframe> vault set telegram bot_token` |
| Add an email account | n/a | `intentframe> vault set email.<addr> password`, then `intentframe> edi add <addr>` |

---

## Example configs

### Smarter model, same behavior

```yaml
model: gpt-4o
sub_agent_model: gpt-4o-mini
context_window_tokens: 128000
```

### Quiet assistant — no background check-ins

```yaml
heartbeat_enabled: false
session_idle_expire_minutes: 30
```

### Work-hours only, check in once an hour

```yaml
heartbeat_enabled: true
heartbeat_interval_minutes: 60
heartbeat_active_hours_start: "09:00"
heartbeat_active_hours_end: "18:00"
```

### More patient with long tasks

```yaml
chat_timeout_seconds: 1200
session_idle_expire_minutes: 120
```

### Tighter memory recall

```yaml
search_max_results: 10
search_min_score: 0.4
hybrid_vector_weight: 0.75
hybrid_text_weight: 0.25
```

---

## Troubleshooting

**A setting doesn't seem to take effect:**
- Make sure there's no `JARVIS_<FIELD>` environment variable overriding it. Environment variables always win over the file.
- Confirm the key name exactly matches the table above (no typos, no extra characters).
- Restart the gateway after editing.
- Confirm the file is valid YAML (no tabs, correct indentation).

**Jarvis is blocking actions unexpectedly:**
This is policy, not config. Check:
```
intentframe> policies
intentframe> audit
```
