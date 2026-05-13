# Jarvis Configuration

This guide explains how to configure Jarvis itself: model selection, identity,
workspace paths, context settings, memory search, heartbeat behavior, skills,
and credentials.

Jarvis configuration is separate from IntentFrame policy.

Policy controls what Jarvis is allowed to do. See `docs/policy-guide.md`.

Jarvis configuration controls how Jarvis runs.

## Configuration Sources

Jarvis configuration is defined in `jarvis_pa/jarvis/config.py`.

Values load in this order, from highest priority to lowest:

1. Constructor arguments passed to `load_config(path=...)` or `JarvisConfig(...)`.
2. Environment variables with the `JARVIS_` prefix.
3. YAML values from `~/.jarvis/config.yaml`.
4. Built-in defaults from `JarvisConfig`.

For normal users, the two useful knobs are:

- `~/.jarvis/config.yaml` for persistent local settings.
- `JARVIS_*` environment variables for one-off overrides.

## Create A Config File

Create the config directory:

```bash
mkdir -p ~/.jarvis
```

Create or edit:

```bash
$EDITOR ~/.jarvis/config.yaml
```

Example:

```yaml
model: gpt-5-mini-2025-08-07
sub_agent_model: gpt-5-mini-2025-08-07

context_window_tokens: 128000
max_history_share: 0.5
compaction_threshold: 0.8

heartbeat_enabled: true
heartbeat_interval_minutes: 30
heartbeat_active_hours_start: "08:00"
heartbeat_active_hours_end: "22:00"

session_idle_expire_minutes: 60
```

Restart the gateway after changing Jarvis config so managed Jarvis processes
pick up the new values.

## Environment Overrides

Every field can be overridden with a `JARVIS_` environment variable.

Examples:

```bash
JARVIS_MODEL=gpt-4o uv run intentframe-gateway-cli
```

```bash
JARVIS_HEARTBEAT_ENABLED=false uv run intentframe-gateway-cli
```

```bash
JARVIS_CONTEXT_WINDOW_TOKENS=64000 uv run intentframe-gateway-cli
```

Environment variables win over `~/.jarvis/config.yaml`.

## Identity

Jarvis has two identity fields:

```yaml
agent_id: jarvis
user_id: jarvis_default
```

For normal usage, do not change `agent_id` in `~/.jarvis/config.yaml`. The
gateway starts Jarvis with `INTENTFRAME_AGENT_ID` so the Actor SDK uses the same
policy slot that bootstrap seeded.

Jarvis user mode uses:

```text
agent_id = jarvis
```

Root-demo mode uses:

```text
agent_id = jarvis_root
```

The owner/user id is resolved by the gateway identity configuration and
environment fallback. Keep Jarvis identity aligned with the gateway, otherwise
the runtime may not find the policy for `(user_id, agent_id)`.

## Model Settings

Default:

```yaml
model: gpt-5-mini-2025-08-07
sub_agent_model: gpt-5-mini-2025-08-07
```

`model` is the main Jarvis model.

`sub_agent_model` is used for Jarvis sub-agent work when Jarvis delegates a
focused task internally.

You can change either in `~/.jarvis/config.yaml`:

```yaml
model: gpt-4o
sub_agent_model: gpt-4o-mini
```

Or temporarily:

```bash
JARVIS_MODEL=gpt-4o JARVIS_SUB_AGENT_MODEL=gpt-4o-mini uv run intentframe-gateway-cli
```

The runtime's Guardian and Analysis Engine model configuration is separate from
Jarvis model configuration. Jarvis can use one model while IntentFrame's review
layers use their own configured models.

## OpenAI API Key

Do not put the OpenAI API key in `~/.jarvis/config.yaml`.

Store it in the IntentFrame credential vault:

```text
intentframe> vault set openai api_key
```

On first launch, the CLI enters setup mode if the key is missing and prints the
same hint.

## Paths

Defaults:

```yaml
workspace_dir: ~/.jarvis
socket_path: ~/.intentframe/run/intentframe.sock
```

`workspace_dir` is Jarvis's local workspace for its own state, memory, and user
skills.

`socket_path` is the IntentFrame runtime socket used by the Actor SDK. Most
users should leave it unchanged.

Example override:

```yaml
workspace_dir: ~/Library/Application Support/Jarvis
```

Paths support `~` expansion.

## Context Window And Compaction

Defaults:

```yaml
context_window_tokens: 128000
max_history_share: 0.5
compaction_threshold: 0.8
```

`context_window_tokens` tells Jarvis how much context the selected model can
handle.

`max_history_share` caps how much of that window can be used by conversation
history.

`compaction_threshold` controls when Jarvis starts compacting history. A value of
`0.8` means compaction can begin around 80 percent of the configured context
window.

For a smaller model:

```yaml
context_window_tokens: 64000
max_history_share: 0.4
compaction_threshold: 0.75
```

## Memory Search

Defaults:

```yaml
chunk_size_tokens: 400
chunk_overlap_tokens: 80
embedding_model: text-embedding-3-small
embedding_dims: 1536
hybrid_vector_weight: 0.7
hybrid_text_weight: 0.3
search_max_results: 6
search_min_score: 0.35
search_candidate_multiplier: 4
```

These settings tune Jarvis's hybrid memory retrieval.

Most users should leave them alone. Consider changing them only if you are
actively tuning recall, precision, latency, or embedding model behavior.

Higher `search_max_results` gives Jarvis more retrieved context but can increase
prompt size. Higher `search_min_score` makes retrieval stricter.

If you change `embedding_model`, make sure `embedding_dims` matches the model's
output dimensionality.

## Auto-Capture

Defaults:

```yaml
auto_capture_min_len: 10
auto_capture_max_len: 500
```

These settings bound the message lengths Jarvis considers for automatic memory
capture.

Lower values capture shorter messages. Higher values allow longer messages to be
captured. Keep these conservative if you want less automatic memory growth.

## Heartbeat

Defaults:

```yaml
heartbeat_enabled: true
heartbeat_interval_minutes: 30
heartbeat_active_hours_start: "08:00"
heartbeat_active_hours_end: "22:00"
heartbeat_ack_max_chars: 50
```

Heartbeat is Jarvis's background check-in behavior.

Disable it:

```yaml
heartbeat_enabled: false
```

Limit it to work hours:

```yaml
heartbeat_enabled: true
heartbeat_interval_minutes: 60
heartbeat_active_hours_start: "09:00"
heartbeat_active_hours_end: "18:00"
```

Use quoted `HH:MM` strings for active hours.

## Server And Session

Defaults:

```yaml
chat_timeout_seconds: 600
session_idle_expire_minutes: 60
```

`chat_timeout_seconds` controls how long Jarvis waits for a chat operation before
timing out.

`session_idle_expire_minutes` controls how long an idle session remains active.

Example:

```yaml
chat_timeout_seconds: 900
session_idle_expire_minutes: 30
```

## Skills

Default behavior:

```yaml
skill_dirs: []
```

If `skill_dirs` is empty, Jarvis uses:

```text
jarvis_pa/jarvis/skills
~/.jarvis/skills
```

To add custom skill directories:

```yaml
skill_dirs:
  - ~/.jarvis/skills
  - ~/my-jarvis-skills
```

Paths support `~` expansion.

## Root Demo Variant

The Jarvis root policy variant is selected by `JARVIS_VARIANT=root` or by the
gateway CLI root profile:

```bash
uv run intentframe-gateway-cli --profile root
```

This selects the `jarvis_root` policy and the root-demo executor config. It does
not mean the entire gateway runs as root.

Root mode is for the crash-test/demo path. Read
`docs/root_demo/executor-root-mode.md` before using it.

## Gateway CLI Config Command

The gateway CLI has a `config` command:

```text
intentframe> config list
intentframe> config get <key>
intentframe> config set <key> <value>
intentframe> config delete <key>
```

That command manages IntentFrame app preferences and system config stored under
the IntentFrame home, including `~/.intentframe/gateway.yaml`.

It is not the same file as `~/.jarvis/config.yaml`. For Jarvis model, heartbeat,
memory, and skills, edit `~/.jarvis/config.yaml` or use `JARVIS_*` environment
variables.

## Example Configs

Quiet local assistant:

```yaml
model: gpt-5-mini-2025-08-07
sub_agent_model: gpt-5-mini-2025-08-07
heartbeat_enabled: false
session_idle_expire_minutes: 30
```

Longer-running background assistant:

```yaml
model: gpt-5-mini-2025-08-07
sub_agent_model: gpt-5-mini-2025-08-07
chat_timeout_seconds: 900
session_idle_expire_minutes: 120
heartbeat_enabled: true
heartbeat_interval_minutes: 60
heartbeat_active_hours_start: "08:00"
heartbeat_active_hours_end: "22:00"
```

Memory-tuning experiment:

```yaml
search_max_results: 10
search_min_score: 0.3
search_candidate_multiplier: 6
hybrid_vector_weight: 0.75
hybrid_text_weight: 0.25
```

## Troubleshooting

If a config value does not seem to apply:

1. Check whether a `JARVIS_*` environment variable is overriding the YAML.
2. Confirm the key name matches the field in `JarvisConfig`.
3. Restart the gateway so managed Jarvis processes reload config.
4. Make sure `~/.jarvis/config.yaml` is valid YAML.

If Jarvis starts but actions are blocked unexpectedly, check policy rather than
config:

```text
intentframe> policies
intentframe> audit
```

Config changes how Jarvis thinks and runs. Policy changes what Jarvis is allowed
to do.

