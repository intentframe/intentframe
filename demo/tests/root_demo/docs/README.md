# Root-demo: write-ups and analysis

Narrative documents, case studies, and experiment write-ups for the root demo.
For raw run logs, see [`results/`](../results/).
For the public evidence summary, see [`docs/root_demo/PROOF.md`](../../../../docs/root_demo/PROOF.md).

## Write-ups

| File | Purpose |
| --- | --- |
| [2026-04-27-attack-sweep-host-impact.md](./2026-04-27-attack-sweep-host-impact.md) | Incident report: 9 ALLOWs on a live 100-intent sweep before remediation. What ran, what changed on the host, and recovery steps. |
| [root-demo-policy-remediation.md](./root-demo-policy-remediation.md) | Remediation plan and status after the April 27 incident: classifier clamp, sensitive-surface deny-caps, dry-run executor, and remaining work. |
| [gray-area-case-study.md](./gray-area-case-study.md) | Interpretation of the 20-intent gray-area dev-workflow suite: which fixtures passed, which blocked, and why the suite matters for policy judgment. |
| [benign-intents-tests-case-study.md](./benign-intents-tests-case-study.md) | Case study on the 100-intent benign suite, focusing on benign_58 (filesystem write semantics) as the clearest illustration of semantic policy value. |
| [intent_limits_only.md](./intent_limits_only.md) | Experiment: running the 100-intent attack corpus under semantic-only policy (intent_limits, no deny_capabilities). Shows 100/100 block through the AI layer alone. |
| [empty_deny_cap_and_intent_limits.md](./empty_deny_cap_and_intent_limits.md) | Experiment: minimal policy (no deny_capabilities, no intent_limits). Baseline for understanding which attacks the deterministic gates catch without policy configuration. |
| [combined_policy_discussion.md](./combined_policy_discussion.md) | Discussion of stacking deterministic and semantic layers: evaluation order, failure modes, and why both layers are load-bearing. |
| [why_llm_guarding_llm.md](./why_llm_guarding_llm.md) | Essay on the asymmetric-context argument: why an LLM Guardian with policy, structured output, and constrained scope can validly guard a general-purpose agent. |

## Raw run logs

Logs live under [`results/`](../results/), organized by suite.

### attacks

| File | What it captured |
| --- | --- |
| [deny_cap_only_dry_run.txt](../results/attacks/deny_cap_only_dry_run.txt) | 100/100 attack intents blocked — dry-run, deny-capabilities-only policy. Preflight confirms `data["dry_run"] == True`. Primary post-remediation proof. |
| [deny_cap_only_dry_run_intentframe_logs.txt](../results/attacks/deny_cap_only_dry_run_intentframe_logs.txt) | Core runtime log for the above (Command Shield, Analysis Engine, Guardian rationale per intent). |
| [deny_cap_only_real_run.txt](../results/attacks/deny_cap_only_real_run.txt) | 100/100 attack intents blocked — real root-capable executor, deny-capabilities-only policy. Preflight confirms `whoami == root`. |
| [deny_cap_only_real_run_intentframe_logs.txt](../results/attacks/deny_cap_only_real_run_intentframe_logs.txt) | Core runtime log for the real-executor sweep. |
| [attacks_assistant_policy_dry_run.txt](../results/attacks/attacks_assistant_policy_dry_run.txt) | 100/100 blocked — dry-run, full admin-assistant policy (`test_policy_root_admin_assistant.yaml`). Most recent full-stack sweep. |
| [attacks_assistant_policy_dry_run_IF_logs.txt](../results/attacks/attacks_assistant_policy_dry_run_IF_logs.txt) | Core runtime log for the above. |
| [attacks_assistant_policy_real_run.txt](../results/attacks/attacks_assistant_policy_real_run.txt) | 100/100 blocked — real executor, full admin-assistant policy. |
| [attacks_assistant_policy_real_run_IF_logs.txt](../results/attacks/attacks_assistant_policy_real_run_IF_logs.txt) | Core runtime log for the real-executor full-stack sweep. |
| [intent_limits_only_dry_run.txt](../results/attacks/intent_limits_only_dry_run.txt) | 100/100 blocked — dry-run, intent-limits-only policy (no deny_capabilities). |
| [intent_limits_only_dry_run_IF_logs.txt](../results/attacks/intent_limits_only_dry_run_IF_logs.txt) | Core runtime log for the above. |
| [intent_limits_only_real_run.txt](../results/attacks/intent_limits_only_real_run.txt) | 100/100 blocked — real executor, intent-limits-only policy. |
| [intent_limits_only_real_run_IF_logs.txt](../results/attacks/intent_limits_only_real_run_IF_logs.txt) | Core runtime log for the real-executor intent-limits-only sweep. |
| [minimal_policy_dry_run.txt](../results/attacks/minimal_policy_dry_run.txt) | Dry-run sweep under minimal policy (no deny_capabilities, no intent_limits). Baseline showing deterministic-gate coverage without policy configuration. |
| [minimal_policy_dry_run_IF_logs.txt](../results/attacks/minimal_policy_dry_run_IF_logs.txt) | Core runtime log for the minimal-policy sweep. |

### benign

| File | What it captured |
| --- | --- |
| [benign_dry_run.txt](../results/benign/benign_dry_run.txt) | 100-intent benign suite dry-run under the admin-assistant policy. Shows which useful admin workflows are permitted. |
| [benign_dry_run_IF_logs.txt](../results/benign/benign_dry_run_IF_logs.txt) | Core runtime log for the benign sweep (Command Shield, AE, Guardian rationale per intent). |

### gray_area

| File | What it captured |
| --- | --- |
| [gray_area_dry_run.txt](../results/gray_area/gray_area_dry_run.txt) | 20-intent gray-area dev-workflow suite dry-run. All fixtures expect ALLOW; log shows which sensitive-but-useful workflows Guardian permits in root context. |
| [gray_area_dry_run_IF_logs.txt](../results/gray_area/gray_area_dry_run_IF_logs.txt) | Core runtime log for the gray-area sweep. |

---

**Safety note:** a full `test_attacks.py` sweep can run **real** `RUN_COMMAND` on the
machine when Guardian returns `ALLOW` unless the supervisor was started with
`INTENTFRAME_EXECUTOR_MODE=dry_run`. In real mode, "root" means the approved `RUN_COMMAND`
subprocess runs through `sudo -n sandbox-exec`; the executor service itself is not UID 0.
Do not treat `[STUB]` as "commands are mocked" — the stub is the agent; the executor may still be real.