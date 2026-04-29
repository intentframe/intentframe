# Root-demo results

Artifacts from root-demo test runs, sweeps, and follow-up analysis. Nothing here is
part of the automated test harness; it is for operators and reviewers.

For the public-facing evidence summary, see
[`docs/root_demo/PROOF.md`](../../../../docs/root_demo/PROOF.md).

| File | Purpose |
| --- | --- |
| [deny_cap_only_dry_run.txt](./deny_cap_only_dry_run.txt) | Post-remediation full 100-intent attack sweep in dry-run mode. Preflight confirms `data["dry_run"] == True`; all 100 adversarial intents return expected `BLOCK` without host I/O. |
| [deny_cap_only_dry_run_intentframe_logs.txt](./deny_cap_only_dry_run_intentframe_logs.txt) | Core runtime log for the dry-run sweep. |
| [deny_cap_only_real_run.txt](./deny_cap_only_real_run.txt) | Post-remediation full 100-intent attack sweep against the real root-capable executor path. Preflight confirms `whoami == root`; all 100 adversarial intents return expected `BLOCK`. |
| [deny_cap_only_real_run_intentframe_logs.txt](./deny_cap_only_real_run_intentframe_logs.txt) | Core runtime log for the real-executor sweep. In this mode the executor service process is still normal-user; root is only requested by allowed `RUN_COMMAND` child wrappers. |
| [2026-04-27-attack-sweep-host-impact.md](./2026-04-27-attack-sweep-host-impact.md) | What happened on the host when a full 100-intent `test_attacks.py` run ALLOWed several commands, recovery steps, and log excerpts. |
| [root-demo-policy-remediation.md](./root-demo-policy-remediation.md) | Remediation plan and status: classifier + policy sensitive-surface clamp, dry-run executor, full dry-run and real-executor 100/100 sweeps, and remaining `intent_limits` / audit work. |
| [benign-58-filesystem-write-case-study.md](./benign-58-filesystem-write-case-study.md) | Case study showing why preserving `capability:filesystem_write` while naming the exact `/tmp` maintenance artifact demonstrates IntentFrame's semantic policy value. |
| [33.txt](./33.txt) | Example terminal log from a full attack sweep (includes per-intent PASS/FAIL). |

**Safety:** a full `test_attacks.py` sweep can run **real** `RUN_COMMAND` on the
machine when Guardian returns `ALLOW` unless the supervisor was started with
`INTENTFRAME_EXECUTOR_MODE=dry_run`. Prefer dry-run for local sweeps and use
real mode only for small benign subsets or a disposable VM. Do not treat
`[STUB]` as “commands are mocked” — the stub is the **agent**; the executor
may still be real. In real mode, "root" means the approved `RUN_COMMAND`
subprocess can run through `sudo -n sandbox-exec`; it does not mean the
executor service itself is UID 0.
