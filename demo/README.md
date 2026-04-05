# IntentFrame Demo

An end-to-end working demo of IntentFrame's security pipeline: an AI invoice-processing agent operating under policy enforcement, with the Guardian blocking over-limit transactions and a full audit trail.

## What the demo shows

An `invoice_bot` agent processes invoices from `demo_data/`, extracts amounts, detects duplicates, and appends valid entries to an expense tracker. All actions flow through the IntentFrame security pipeline:

```
invoice_bot → Actor SDK → Analysis Engine → Guardian → Executor → real I/O
```

**Policy under test:**
- Maximum $5,000 per transaction (deterministic + AI-evaluated layers)
- Confirm before any deletion
- Only allowed paths: `/invoices/`, `/expense_tracker.md`

**Expected outcomes:**
- Office Depot ($847) → ALLOW
- Acme Corp ($2,500 duplicate) → ASK USER → depends on response
- TechConsult ($12,000) → BLOCK (exceeds $5k limit)

## Prerequisites

- Python workspace installed (`bash intentframe_setup.sh` from repo root)
- `OPENAI_API_KEY` set in your shell
- The gateway CLI **not** running (demo uses its own supervisor and executor config)

## Running the demo

**Terminal 1 — start the supervisor with demo config (from repo root):**

```bash
EXECUTOR_CONFIG=demo/config/executor.yaml python -m supervisor.main start
```

**Terminal 2 — run the demo dashboard (from repo root):**

```bash
export OPENAI_API_KEY=your-key-here
python demo/demo_dashboard.py
```

The dashboard will:
1. Register the `finance_001` user with policies from `demo/config/dashboard.yaml`
2. Register the `invoice_processing` workspace with demo data mounts
3. Install and run the `invoice_bot` agent in an isolated venv
4. Print the audit trail

## Why a separate supervisor?

The demo uses `demo/config/executor.yaml` which configures:
- only `files` and `user_io` adapters (not the full Jarvis adapter set)
- filesystem mounts pointing at `demo/demo_data/`

If the gateway CLI is already running, it uses `jarvis_pa/executor.yaml` — a different profile with many more adapters and a different filesystem layout. Running both at the same time causes socket conflicts.

## Running the tests

The tests in `tests/` exercise different aspects of the pipeline. Run them from the **repo root** with the supervisor running.

```bash
# Full AI pipeline (invoice processing end-to-end)
python -m tests.test_ai_pipeline

# Security: basic prompt injection attacks (01-06)
python -m tests.test_attacks

# Security: advanced attacks (07-14, sourced from JailbreakBench/OWASP/academic research)
python -m tests.test_advanced_attacks

# Specific attack numbers
python -m tests.test_advanced_attacks 7 9 12

# JSON output for CI
python -m tests.test_advanced_attacks --json

# Executor adapter tests
python -m tests.test_adapters

# Domain constraint hardening
python -m tests.test_domain_hardening
```

## Layout

```
demo/
├── demo_dashboard.py          # Entry point — config-driven dashboard run
├── config/
│   ├── dashboard.yaml         # Users, workspaces, tasks
│   └── executor.yaml          # Executor profile for the demo
├── demo_data/
│   ├── acme_corp.md           # Normal invoice (potential duplicate)
│   ├── office_depot.md        # Normal invoice (within limit)
│   ├── techconsult.md         # Over-limit invoice ($12,000)
│   ├── expense_tracker.md     # Written by the agent during the run
│   ├── expense_tracker_original_locked.md   # Clean starting state (reset on each run)
│   └── attacks/               # 14 prompt injection attack test cases
│       └── README.md          # Attack descriptions and expected outcomes
└── tests/
    ├── test_ai_pipeline.py
    ├── test_attacks.py
    ├── test_advanced_attacks.py
    ├── test_adapters.py
    ├── test_domain_hardening.py
    └── test_ai_analysis.py
```

## Attack test cases

`demo_data/attacks/` contains 14 prompt injection scenarios sourced from JailbreakBench, OWASP LLM Top 10, Microsoft Crescendo, and academic research. See [`demo_data/attacks/README.md`](demo_data/attacks/README.md) for the full attack matrix and expected outcomes.
