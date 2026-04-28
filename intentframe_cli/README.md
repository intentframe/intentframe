# IntentFrame CLI

Interactive terminal frontend for IntentFrame. Talks exclusively to the gateway over `gateway.sock` — the same API surface any frontend uses.

## Usage

```bash
uv run intentframe-gateway-cli
# or, with the venv activated:
intentframe-gateway-cli
```

If the gateway isn't running, the CLI starts it as a background process, waits for it to become healthy, then drops into the interactive REPL. If the gateway is already running, it connects immediately.

### Root demo profile

The CLI also supports a demo-only root profile:

```bash
intentframe-gateway-cli --profile root
```

This does **not** run the whole stack with `sudo`. Instead, it asks the gateway to use the Jarvis root profile and `jarvis_pa/executor_root.yaml`, whose sandbox config opts `RUN_COMMAND` into per-command `sudo -n sandbox-exec` wrapping.

That root capability only becomes active after a one-time machine setup:

```bash
sudo bash intentframe_setup_root_demo.sh
```

When root-demo is installed, the CLI shows a profile banner from gateway health data:

```text
Profile: root   Escalation: ARMED   Executor running_as_root: yes
```

Here `running_as_root` is a capability flag for `RUN_COMMAND`, not a claim that
the executor service process has UID 0. In the supported root-demo flow the
executor process remains a normal-user process; only the child `sandbox-exec`
wrapper for an allowed command requests root through the installer-created
sudoers entry.

If `--profile root` is requested before installation, the CLI warns but still starts normally; commands simply run unprivileged.

When you quit the CLI, it prints an uninstall reminder if root-demo is still installed:

```bash
sudo bash intentframe_uninstall_root_demo.sh
```

## First run

On first launch the credential vault won't have an OpenAI API key, so the gateway enters **partial startup** mode. The CLI detects this and shows a **credential checklist** covering everything IntentFrame needs:

```
  credential-vault         ok
  jarvis                   --
  edi                      --

╭─ Credential & Config Status ──────────────────────────────────────────╮
│                                                                       │
│  LLM API Key (required)     MISSING  vault set openai api_key         │
│  Telegram Bot Token         --       vault set telegram bot_token     │
│  Telegram User ID           --       env set telegram.allowed_user_id │
│  Email Account              --       vault set email.YOU@GMAIL.COM    │
│                                       password                        │
│                                       then:  edi add YOU@GMAIL.COM    │
│                                                                       │
╰──────────── Run the hint command to configure each item ──────────────╯
  Required credentials are missing — IntentFrame cannot fully start.
  Optional credentials unlock Telegram and email features.

intentframe [setup]>
```

Only `vault`, `health`, `status`, `logs`, `help`, and `quit` are available in setup mode. After you store the OpenAI key, the CLI automatically restarts the gateway and transitions to normal mode.

In **normal mode**, any unconfigured optional features are shown as a brief summary:

```
  Optional features not configured:
    -- Telegram Bot Token:  vault set telegram bot_token
    -- Telegram User ID:    env set telegram.allowed_user_id YOUR_ID
    -- Email Account:       vault set email.YOU@GMAIL.COM password
                             then:  edi add YOU@GMAIL.COM

Jarvis is ready. Type a message, or help for commands.
```

### Credential categories

| Category | Required | How to set | What it unlocks |
|----------|----------|-----------|-----------------|
| **LLM API Key** | Yes | `vault set openai api_key` | Core agent functionality |
| **Telegram Bot Token** | No | `vault set telegram bot_token` | Telegram chat with Jarvis |
| **Telegram User ID** | No | `env set telegram.allowed_user_id YOUR_ID` | Restricts bot to your account |
| **Email Account** | No | `vault set email.<addr> password` + `edi add <addr>` | Email read/send/search |

Well-known credentials (`openai/api_key`, `telegram/bot_token`) have smart defaults — the delivery mode and env variable name are set automatically so you only need to paste the value.

## REPL Commands

| Command | Description |
|---------|-------------|
| `status` | Show all service statuses (name, health, PID) |
| `health` | Quick aggregated health check |
| `logs <service> [lines]` | View last N log lines for a service |
| `chat <message>` | Chat with Jarvis |
| `start <service>` | Start a managed service (jarvis, edi, telegram) |
| `stop <service>` | Stop a managed service |
| `restart <service>` | Restart a managed service |
| `vault list [ns]` | List credentials (masked summaries) |
| `vault get <ns> <key>` | Retrieve a credential value |
| `vault set <ns> <key>` | Store a credential (prompts for value & delivery mode) |
| `vault delete <ns> <key>` | Delete a credential |
| `vault check <ns> <key>` | Check if a credential exists |
| `edi status` | EDI daemon status |
| `edi accounts` | List configured email accounts |
| `edi add <email> [name]` | Add an email account (password must be in vault first) |
| `edi remove <email>` | Remove an email account |
| `config list` | List all app preferences |
| `config get <key>` | Get a preference value |
| `config set <key> <value>` | Set a preference |
| `config delete <key>` | Delete a preference |
| `audit` | View the intent audit trail |
| `permissions` | Show macOS TCC permission status |
| `policies` | List active policies |
| `bootstrap` | Re-run policy/workspace seeding |
| `help` | Show command list |
| `quit` | Shut down IntentFrame and exit |

Any unrecognized input is sent to Jarvis as a chat message — just type naturally.

## Architecture

```
intentframe_cli/
├── __init__.py
├── client.py       # GatewayClient: httpx-over-UDS, every method maps to a gateway endpoint
├── lifecycle.py    # Start/stop gateway process
├── repl.py         # REPL loops (setup mode + normal mode) and prompt session factory
├── commands.py     # Command handlers — one async function per REPL command
└── main.py         # Entry point: starts gateway if needed, selects REPL mode
```

The CLI is a pure HTTP client. It never talks to individual services, never reads PID files for anything other than the gateway, and never manages child processes directly. All intelligence lives in the gateway.

### Shutdown flow

```
User types "quit" (or Ctrl+C / EOF)
  → CLI calls POST /system/shutdown on gateway.sock
  → Gateway receives SIGTERM, runs lifespan teardown (stops all managed services + supervisor)
  → CLI polls for PID exit every 0.5s (up to 90s):
      – if CLI started the gateway: os.waitpid reaps the child immediately on exit (no zombie)
      – if CLI connected to an already-running gateway: os.kill(pid, 0) detects exit
  → If gateway doesn't exit in time, force-kill via SIGKILL on the process group
```

The CLI intentionally exercises the same `POST /system/shutdown` API rather than sending a signal directly, so it tests the same shutdown code path as any real frontend.

If the local machine still has root-demo installed (`~/.intentframe/state/root-demo.json` present), the CLI prints a reminder after `Gateway stopped.` so the operator does not forget that the sudoers entry persists across sessions.

## Entry point

```toml
[project.scripts]
intentframe-gateway-cli = "intentframe_cli.main:main"
```
