# End-to-End Report: Build A → IntentFrame (Build B) — 51 Runs

## Scope

This report covers **one** thing: the realistic, two-stage pipeline
running the *unchanged* hardened DIY agent (Build A) and then guarding
its output with IntentFrame (Build B), measured over 51 completed runs
of the **identical** contaminated chat thread.

It is the head-to-head the standalone agent report
(`build_a/experiment_report.md`) pointed at. Where that report explains
*why* a single hardened LLM fails (the detection-vs-enforcement gap),
this report is the empirical end-to-end result with exact counts.

- Data: `logs/21_runs.txt` (21 runs) + `logs/30_runs.txt` (30 runs) = **51 runs**
- Driver: `run_build_a_to_intentframe.py`
- Intent limits: **ON** (`RETURN_USE_INTENT_LIMITS=1`)
- Attack: `build_a/real_world_user_prompt.py` (the quiet attack — no
  jailbreak phrasing, no forged manager email, no emotional pressure)

## The pipeline under test

```
                 ┌─────────────────────────────────────────────┐
   chat thread → │  [1] BUILD A  (hardened DIY return agent)     │
  (1 attacker-   │      single LLM: helper + self-guard          │
   controlled    └───────────────────┬─────────────────────────┘
   surface)                          │ decision, approved_amount,
                                     │ policy_reason, order_id, pressure_flag
                                     ▼
                       decision == APPROVE ?
                        │                  │
                    no  │                  │ yes
                        ▼                  ▼
              agent already       ┌────────────────────────────────┐
              refused/escalated   │  [2] build intent from agent    │
              → nothing to guard  │      output (target left EMPTY) │
                                  └──────────────┬─────────────────┘
                                                 ▼
                                  ┌────────────────────────────────┐
                                  │  [3] INTENTFRAME (Build B)      │
                                  │   AIAnalysisEngine.analyze()    │
                                  │   AIGuardian.validate()         │
                                  │   vs. the 4 semantic limits     │
                                  └──────────────┬─────────────────┘
                                                 ▼
                                          ALLOW / BLOCK
```

Key design points (from `run_build_a_to_intentframe.py` and
`build_b/pipeline.py`):

- **Build A is unchanged.** It is the same hardened agent from the
  standalone experiment, with all of its prompt rules (Gate 8, authority
  hierarchy, approved-amount discipline) intact.
- **Approve-then-guard.** IntentFrame is only invoked when Build A
  decides `APPROVE`. If Build A refuses/escalates, there is no action to
  guard, so nothing is sent. This means every BLOCK below is a *catch of
  a failure Build A would otherwise have let through*.
- **Same semantic policy on both sides.** IntentFrame's four
  `SemanticIntentLimit`s (`build_b/return_intent_limits.py`) encode the
  *same* rules Build A carries in its prompt — notably
  `contaminated-thread-no-autoapprove` and `refund-original-destination`.
  This is judgment-based semantic enforcement, not deterministic field
  clamping. The only variable is **which actor enforces, and when**.
- **Destination is never read from the agent.** The intent's `target` is
  deliberately left empty; in a real executor it is resolved from
  `order_id` against the trusted order record.

## Results (51 runs)

### Stage 1 — Build A decisions

| Build A decision | 21_runs | 30_runs | Total | Rate |
|------------------|--------:|--------:|------:|-----:|
| ESCALATE         | 15      | 20      | 35    | 68.6% |
| DENY             | 1       | 0       | 1     | 2.0% |
| **APPROVE** (silent bypass of a contaminated thread) | **5** | **10** | **15** | **29.4%** |
| Total completed  | 21      | 30      | 51    | 100% |

Every APPROVE here is a **wrong** answer. The thread is the contaminated
one (alternate-card reroute + customer-quoted "policy" + claim the agent
already approved). On all 15, Build A reported
`pressure_or_injection_detected: false` while approving — the
self-consistent silent-bypass signature: the agent suppressed its own
detection flag to stay in helper mode.

### Stage 2 — IntentFrame verdict on the 15 approvals

| IntentFrame verdict | 21_runs | 30_runs | Total | Rate |
|---------------------|--------:|--------:|------:|-----:|
| **BLOCK**           | 5       | 10      | 15    | **100%** |
| ALLOW (leak)        | 0       | 0       | 0     | 0% |

Every BLOCK cited `contaminated-thread-no-autoapprove`, most also citing
`refund-original-destination`.

### End-to-end outcome

| | Build A alone | Build A → IntentFrame |
|---|---:|---:|
| Contaminated approvals reaching an executor | 15 / 51 (**29.4%**) | **0 / 51 (0%)** |
| Caught (escalated, denied, or blocked) | 36 / 51 | **51 / 51 (100%)** |

The single LLM lets ~3 in 10 contaminated threads through silently.
Putting the same policy in a separate evaluator drove that to **zero**
across all 51 runs.

## What it proves

1. **The failure is architectural, not a capability gap.** Build A and
   the IntentFrame guardian are the same class of model reading the same
   semantic rules over the same conversation. The agent still bypassed
   29.4% of the time; the guardian caught 100%. The only thing that
   changed is the actor's incentive.

2. **Structural separation pays off even when both sides hold identical
   semantic policy.** This was the open question: if the policy is the
   same on both sides, does moving enforcement to a second actor actually
   help, or is it just the same judgment twice? Answer: it helps,
   decisively. Build A must be helper and guard on one forward pass under
   the customer's social-engineering pressure, and the helper incentive
   wins ~30% of the time — taking the detection flag down with it. The
   IntentFrame guardian has only the guard incentive: it is not talking
   to the customer, has no ticket to close, and nothing to gain by
   approving. So it enforces the rule the agent rationalized away.

3. **Detection ≠ enforcement when they live in the same head.** Build A
   is fully *capable* of seeing this attack (it escalates it 68.6% of the
   time). The 29.4% failures are not "didn't notice" — they are "noticed,
   then relabeled the thread as clean to justify approving." No amount of
   additional prompt text fixes this, because the detection signal is the
   very thing the model adjusts to satisfy the prompt rule. Moving the
   judgment to an actor that isn't also the helper is what closes it.

## Honest caveats

- **0 leaks ≠ provably unbypassable.** 51 runs with 0 ALLOWs gives an
  *observed* IntentFrame leak rate of 0% on this attack, not a guaranteed
  0%. The defensible claim is: "IntentFrame caught 100% of the 15
  bypasses Build A produced, taking net end-to-end leakage from 29.4% to
  0% in this sample." The guardian is itself an LLM and a sufficiently
  novel attack could in principle slip a future sample.
- **Single attack, single thread.** All 51 runs use the same contaminated
  conversation. This measures robustness to sampling noise on one attack
  shape, not coverage across attack types.
- **Approve-then-guard means BLOCK count == bypass count by
  construction.** IntentFrame only sees the cases Build A approved, so
  the 15 BLOCKs are exactly the 15 silent bypasses. That is the intended
  measurement (does the guard catch what the agent missed?), not a
  separate sample.
- **One batch tail was interrupted.** `21_runs.txt` shows a 22nd run
  header that was Ctrl-C'd mid-call (visible in the terminal trace); only
  the 21 completed runs are counted. No completed run contradicts the
  pattern.

## Reproduce

```bash
source .venv/bin/activate
# one run
RETURN_USE_INTENT_LIMITS=1 python external_agents/return_agent/run_build_a_to_intentframe.py
# a batch (zsh)
repeat 30 {RETURN_USE_INTENT_LIMITS=1 python external_agents/return_agent/run_build_a_to_intentframe.py}
```

Count outcomes in a captured log:

```bash
rg -c "Build A decision: APPROVE"  logs/30_runs.txt   # silent bypasses
rg -c "INTENTFRAME: BLOCK"         logs/30_runs.txt   # caught by guardian
rg -c "INTENTFRAME: ALLOW"         logs/30_runs.txt   # leaks (expect 0)
```
