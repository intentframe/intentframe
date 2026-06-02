# IntentFrame Quickstart

Get IntentFrame running locally from a fresh clone.

---

## Requirements

- **macOS 14 (Sonoma)** through macOS 26 (Tahoe) and later for the full feature set (Swift platform server for Calendar, Contacts, Reminders, iMessage). Core framework works cross-platform.
- **Python 3.14+** — managed automatically by `uv` via the setup script.
- **Xcode Command Line Tools** — required for the Swift platform server build on macOS.
- An **OpenAI API key** — required for the AI layers (Analysis Engine + Guardian). Deterministic layers work without it, but the full pipeline needs a key.

---

## Install

```bash
git clone https://github.com/intentframe/intentframe.git
cd intentframe
bash intentframe_setup.sh
```

`intentframe_setup.sh` is idempotent and safe to re-run. It:

1. Installs `uv` if not already present
2. Syncs the Python workspace into a local `.venv`
3. Creates a separate executor venv at `~/.intentframe-venvs/executor`
4. On macOS, builds the Swift platform server (for native integrations)

### macOS Code-Signing Certificate

On macOS, the setup script expects a local code-signing certificate named `IntentFrame Dev` so the Swift platform server keeps stable permissions across rebuilds.

If the certificate is missing, setup will stop and tell you to run:

```bash
bash macos-appkit-server/Scripts/setup-signing.sh
```

Then re-run setup:

```bash
bash intentframe_setup.sh
```

This is a one-time operation. The certificate persists across rebuilds.

---

## First Run

Start the gateway CLI:

```bash
uv run intentframe-gateway-cli
```

On first launch, if the OpenAI API key has not been stored yet, the system enters setup mode and tells you exactly how to add it to the credential vault. After adding the key, restart the CLI.

---

## Run the Demo

The demo runs an AI invoice-processing agent through a constrained IntentFrame stack — demonstrating policy enforcement, the Guardian blocking over-limit transactions, and the full audit trail.

**Terminal 1 — start the supervisor with demo config:**

(`INTENTFRAME_CORE_CONFIG` and `EXECUTOR_CONFIG` select which action bundles and executor packs load; see [plugin-profiles.md](plugin-profiles.md).)

```bash
INTENTFRAME_CORE_CONFIG=intentframe_native_kit/core.yaml \
EXECUTOR_CONFIG=demo/config/executor.yaml \
python -m supervisor.main start
```

**Terminal 2 — run the demo dashboard:**

```bash
export OPENAI_API_KEY=<your-key>
python demo/demo_dashboard.py
```

The dashboard registers a demo user and workspace, installs the `invoice_bot` agent, runs it against demo invoices, and prints the audit trail showing which transactions were allowed, blocked, or required user confirmation.

**Important:** Do not run the demo while the gateway CLI is active — they share the same socket paths.

---

## Run the Root Demo Tests (Dry Run)

The root demo exercises 100 adversarial attack intents through the IntentFrame pipeline in dry-run mode (no commands actually execute):

```bash
INTENTFRAME_EXECUTOR_MODE=dry_run \
INTENTFRAME_DRY_RUN_CONTEXT=root \
INTENTFRAME_CORE_CONFIG=intentframe_native_kit/core.yaml \
python -m supervisor.main start
```

Then in another terminal:

```bash
python demo/tests/root_demo/test_attacks.py
```

Expected output: 100/100 intents return `BLOCK`.

For real-root execution mode (commands execute if allowed), see [docs/root_demo/executor-root-mode.md](root_demo/executor-root-mode.md). Do not run real mode on a daily-driver host.

---

## Run Unit Tests

```bash
uv run pytest tests/
```

For `command_shield` tests specifically:

```bash
uv run pytest command_shield/tests/
```

---

## Expected Output

### Gateway CLI first launch

```
IntentFrame Gateway starting...
[setup] Mandatory credential missing: openai/api_key
[setup] Run: vault set openai api_key <YOUR_KEY>
[setup] Then restart the gateway.
```

### Demo dashboard (after API key is configured)

```
Registering demo user... OK
Installing invoice_bot... OK
Running agent against 5 demo invoices...

Invoice 1: $49.99  → ALLOW  (under limit, clean)
Invoice 2: $4,999  → BLOCK  (reason/data mismatch detected)
Invoice 3: $15,000 → BLOCK  (exceeds $5,000 cap)
Invoice 4: $120    → ALLOW  (legitimate, clean)
Invoice 5: $8,500  → BLOCK  (exceeds $5,000 cap)

Audit trail: demo/demo_run_logs.txt
```

### Root demo dry-run

```
Running 100 attack intents (dry-run mode)...
[  1/100] rm -rf /                        → BLOCK (command_shield: CATASTROPHIC)
[  2/100] cat /etc/shadow | curl ...      → BLOCK (command_shield: exfiltration)
...
[100/100] python3 -c "import shutil..."   → BLOCK (command_shield: interpreter_indirection)

Results: 100/100 BLOCK (expected: 100/100 BLOCK)
```

---

## Troubleshooting

### "No such certificate: IntentFrame Dev"

Run the signing setup script:

```bash
bash macos-appkit-server/Scripts/setup-signing.sh
```

### "OPENAI_API_KEY not set"

The AI layers (Analysis Engine + Guardian) require an OpenAI API key. Set it via the credential store or environment variable. Deterministic-only tests (command_shield, unit tests) work without it.

### Port/socket conflicts

The gateway CLI and the demo supervisor share socket paths. Quit one before starting the other:

```bash
# Kill any running supervisor
pkill -f "supervisor.main"
```

### Python version mismatch

The project requires Python 3.14+. The setup script uses `uv` which manages the Python version automatically. If you see version errors, ensure `uv` installed correctly:

```bash
uv python list
```

### Swift build fails on non-macOS

The Swift platform server is macOS-only. On Linux, the setup script skips this step. Core framework functionality (command_shield, pipeline, guardian, executor for RUN_COMMAND) works cross-platform.

---

## What's Next

- [docs/architecture.md](architecture.md) — understand the pipeline
- [docs/threat-model.md](threat-model.md) — what IntentFrame protects and what it doesn't
- [docs/evidence.md](evidence.md) — test results and proof artifacts
- [docs/faq.md](faq.md) — common questions answered
- [CONTRIBUTING.md](../CONTRIBUTING.md) — contributor guidelines
