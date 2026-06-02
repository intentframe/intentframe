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
INTENTFRAME_CORE_CONFIG=intentframe_native_kit/core.yaml \
EXECUTOR_CONFIG=demo/config/executor.yaml \
python -m supervisor.main start \
  --config intentframe_native_kit/supervisor_profile.yaml
```

The kit profile starts `resource-registry` so the dashboard can register workspaces.
The packaged supervisor default omits it; use the profile for all demo/test runs.

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

See [`tests/README.md`](tests/README.md) for the full test guide — threat model, attack matrix, how to run, and current results.

Quick start (from **repo root**, with the attack supervisor running):

```bash
# Start the supervisor with the attack executor profile + kit profile (workspaces)
INTENTFRAME_CORE_CONFIG=intentframe_native_kit/core.yaml \
EXECUTOR_CONFIG=demo/config/executor_attacks.yaml \
python -m supervisor.main start \
  --config intentframe_native_kit/supervisor_profile.yaml

# Foundation attacks (1-6)
python demo/tests/test_attacks.py

# Advanced attacks (7-14: encoding, many-shot, crescendo, unicode, etc.)
python demo/tests/test_advanced_attacks.py

# Red-team attacks (15-24: expert-level, payloads in data/target fields)
python demo/tests/test_redteam_attacks.py

# Specific attacks
python demo/tests/test_attacks.py 2
python demo/tests/test_redteam_attacks.py 15 17

# Full AI pipeline (invoice processing end-to-end)
python demo/tests/test_ai_pipeline.py

# Executor adapter tests
python demo/tests/test_adapters.py
```

## Layout

```
demo/
├── demo_dashboard.py              # Entry point — config-driven dashboard run
├── config/
│   ├── dashboard.yaml             # Users, workspaces, tasks
│   ├── executor.yaml              # Executor profile for the demo
│   ├── executor_attacks.yaml      # Executor profile for attack tests
│   └── test_policy.yaml           # Shared test policy (all attack suites)
├── demo_data/
│   ├── acme_corp.md               # Normal invoice (potential duplicate)
│   ├── office_depot.md            # Normal invoice (within limit)
│   ├── techconsult.md             # Over-limit invoice ($12,000)
│   ├── expense_tracker.md         # Written by the agent during the run
│   ├── expense_tracker_original_locked.md
│   ├── attacks/                   # 14 malicious invoice files (attacks 1-14)
│   │   └── README.md
│   └── attack_intents/            # 24 pre-built attack intent JSONs
│       ├── attack_01_*.json ... attack_14_*.json
│       └── redteam/
│           └── attack_15_*.json ... attack_24_*.json
└── tests/
    ├── README.md                  # Test guide, attack matrix, results
    ├── security_analysis.md       # Deep security analysis & OWASP coverage
    ├── test_attacks.py            # Attacks 1-6 (foundation)
    ├── test_advanced_attacks.py   # Attacks 7-14 (advanced evasion)
    ├── test_redteam_attacks.py    # Attacks 15-24 (expert red-team)
    ├── stub_pipeline_agent.py     # Agent-agnostic test harness
    ├── invoice_attack_pipeline.py # Test orchestration
    ├── policy_loader.py           # Shared YAML → UserPolicy loader
    ├── test_ai_pipeline.py        # Full pipeline integration
    ├── test_ai_analysis.py        # AE unit tests
    ├── test_adapters.py           # Executor adapter tests
    ├── test_domain_hardening.py   # Domain constraint tests
    ├── test_executor.py           # Executor service tests
    └── test_transitive_injection_live.py  # AE → Guardian boundary (live LLM)
```

## Attack test cases

24 attacks across three suites, mapped to OWASP LLM Top 10 and OWASP Agentic Top 10 categories. Current results: **23/24 defended, 1 known gap** (salami slicing — cumulative spending detection is planned). See [`tests/README.md`](tests/README.md) for the full attack matrix, reproducibility data, and detailed results.
