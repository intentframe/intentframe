# IntentFrame

> **Delegatable autonomy for AI agents and Automating the human oversight.**

When you let an AI agent work for you, YOU are currently the safety system - reviewing every action, making 
judgment calls, clicking approve/reject. IntentFrame automates that supervision.

An AI agent is useful in proportion to the actions it can take on your behalf.
Today, you have two options. You can give the agent the keys and hope — most
agent frameworks do this, and the news stories write themselves. Or you can
sit in the loop, approving every action — which works for demos and stops
working the moment "autonomous" matters.

IntentFrame is the third option. **It is the structural supervision layer
that makes AI agents delegatable** — the same way medical licensing,
scope-of-practice rules, and malpractice law make human surgeons delegatable.
The agent stays operationally autonomous: it decides, plans, and acts on its
own. The structural supervision — pre-declared policy, deterministic gates,
semantic review, executor isolation, audit trail — runs in the background.
You don't watch the agent. You set the boundaries once, and the boundaries
do the watching.

That is what "autonomous AI agent" should mean, and currently doesn't.

**The agent does the work. IntentFrame automates the oversight.**

See [docs/autonomy.md](docs/autonomy.md) for the full thesis. If a concrete
analogy lands better for you, [docs/mental-models.md](docs/mental-models.md)
walks through seven of them — pharmacy, contractor, accountant/CFO, financial
advisor, licensed professional, fire, OS kernel — each with what it gets
right and where it breaks down.

---

## Why IntentFrame

Today, when you connect an AI agent to your email, calendar, or terminal, **you**
become the safety system — reading every action, making judgment calls, clicking
approve or reject. That doesn't scale.

Every consequential profession humans have ever built — surgery, aviation,
finance, law, structural engineering — solved the same problem: how do you
let someone act on your behalf without watching them do it? The answer was
never "remove their autonomy." The answer was always *structural supervision*:
licenses, scope rules, audits, malpractice. The professional decides
operationally; the system bounds them structurally.

AI agents are stuck before that step. They have operational autonomy (they
can act), but no structural supervision (no licensing-shape boundary). So
users are forced into one of two unscalable choices: trust by faith, or
manual approval of every action. Neither is delegatable autonomy. One is
gambling, the other is just you with extra steps.

IntentFrame separates the work from the oversight. Every agent action flows
through a policy pipeline — Analysis Engine, Guardian, Executor — so no single
component can think, judge, and act on its own.
IntentFrame builds the missing structural supervision. Every agent action
flows through a policy pipeline — Analysis Engine, Guardian, Executor — so
no single component can think, judge, and act on its own. The agent retains
full operational autonomy. The system holds the boundaries.

**Prevention, not containment.** IntentFrame blocks dangerous AI-decided
actions *before* they execute, instead of letting them through and trying to
restrict their consequences. That is why agents using IntentFrame can have
full capability — including effective root-level execution — without the
usual sandboxing tradeoffs. Everything that reaches the executor has already
been judged safe; the kernel sandbox is a safety net, not the primary
boundary. See
[Principle 2: Prevention before containment](docs/principles.md#2-prevention-before-containment).

---

## Getting Started

### Fresh Clone

```bash
git clone https://github.com/intentframe/intentframe.git
cd intentframe
bash intentframe_setup.sh
uv run intentframe-gateway-cli
```

`intentframe_setup.sh` is the bootstrap script for local development. It:

- installs `uv` if needed
- syncs the Python workspace into a local `.venv`
- on macOS, builds the Swift platform server used for native integrations

### macOS Note

On macOS, the setup script expects a local code-signing certificate named
`IntentFrame Dev` so the Swift platform server keeps stable permissions for
Calendar, Contacts, and Reminders across rebuilds.

If the certificate is missing, the setup script will stop and tell you to run:

```bash
bash macos-appkit-server/Scripts/setup-signing.sh
```

Then rerun:

```bash
bash intentframe_setup.sh
```

### First Run

On first launch, the gateway CLI starts the gateway stack. If the OpenAI API key
has not been stored yet, the system enters setup mode and tells you exactly how
to add it to the credential vault. After that, restart the CLI and continue.

For the demo-only root command-execution profile on macOS, see
[`docs/executor-root-mode.md`](docs/executor-root-mode.md). That flow uses
`intentframe-gateway-cli --profile root` plus a one-time
`intentframe_setup_root_demo.sh` installer; it is intentionally separate from
normal setup and is not the default operating mode.

### Re-running Setup

`intentframe_setup.sh` is safe to rerun after dependency changes or after
pulling updates. If you already had the gateway CLI running, quit it and start
it again after setup so the running system picks up rebuilt artifacts.

---

## Demo

The demo runs an AI invoice-processing agent through a constrained IntentFrame
stack — demonstrating policy enforcement, the Guardian blocking over-limit
transactions, and the full audit trail.

The demo uses its own isolated executor config. **Do not run it while the
gateway CLI is active** — they share the same socket paths.

**Terminal 1 — start the supervisor with demo config:**

```bash
EXECUTOR_CONFIG=demo/config/executor.yaml python -m supervisor.main start
```

**Terminal 2 — run the demo dashboard:**

```bash
export OPENAI_API_KEY=...
python demo/demo_dashboard.py
```

The dashboard registers a demo user and workspace, installs the `invoice_bot`
agent, runs it against the demo invoices, and prints the audit trail showing
which transactions were allowed, blocked, or required user confirmation.

---

## The Architecture

The agent thinks, plans, and acts on its own. The pipeline judges each action
at the boundary where it would touch your world.

```
AI Agent: "I want to do X"        ← operationally autonomous: decides everything
    ↓
[Analysis Engine] → "What will this REALLY do?"     ← independent peer-review analog
    ↓
[Guardian] → "Is this allowed by user's policies?"  ← credentialing-committee analog
    ↓
[Executor] → Does it (if approved)                  ← the credentialed pharmacy
```

**No single entity can THINK + UNDERSTAND + JUDGE + ACT.** The agent thinks.
Each layer of the pipeline does exactly one thing. That separation is what
makes the agent's autonomy structurally delegatable rather than just
operationally hopeful.

---

## Jarvis Policies

Jarvis (the local personal-assistant stack) ships with a default set of allowed and blocked actions, path constraints, and intent limits. The runtime default is seeded at gateway startup from hardcoded values in `intentframe_gateway/bootstrap.py`. `jarvis_pa/seed_policies.py` is kept as a manual mirror of the same defaults for dev workflows — profile-aware (`INTENTFRAME_PROFILE=user|root`) and idempotent, so reruns are safe and the root-profile shape is seeded identically to bootstrap.

There is currently no file-based or CLI-based way to customise policies without editing those source files directly and re-running bootstrap. The gateway exposes a read-only `/policies` endpoint; writes are not routed through it.

A full policy-editing surface — via a web app, the CLI, or a macOS app — is planned for a future release.

IntentFrame also supports two filesystem tool families: workspace/VFS
tools (`READ_FILE`, `WRITE_FILE`, etc.) and host file tools
(`READ_HOST_FILE`, `WRITE_HOST_FILE`, etc.). The runtime can enforce
either family, but real product profiles should usually expose only one
family to a given LLM tool list. See
[`docs/vfs-vs-host-tools.md`](docs/vfs-vs-host-tools.md) for the design
guidance, tradeoffs, and test harness modes.

---

## Requirements

- Python 3.14+
- macOS 14 (Sonoma) through macOS 26 (Tahoe) and later for the Swift platform server (optional — core framework works on any OS). On Tahoe, iMessage reading uses a typedstream decoder to handle Apple's `chat.db` schema-behavior change; see [`macos-appkit-server/docs/imessage-attributedbody.md`](macos-appkit-server/docs/imessage-attributedbody.md) for the technical details.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions and guidelines.

## Security

Found a vulnerability? See [SECURITY.md](SECURITY.md) — **do not open a public issue.**

## License

Copyright (c) 2026 IntentFrame Contributors.

IntentFrame is licensed under the GNU Affero General Public License v3.0 only
(AGPL-3.0-only). See [LICENSE](LICENSE) for the full license text.

Commercial licensing is available for organizations that want to use
IntentFrame without releasing their modifications under the AGPL.

