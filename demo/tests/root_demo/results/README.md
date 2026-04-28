# Root-demo results

Artifacts from root-demo test runs, sweeps, and follow-up analysis. Nothing here is
part of the automated test harness; it is for operators and reviewers.

| File | Purpose |
| --- | --- |
| [2026-04-27-attack-sweep-host-impact.md](./2026-04-27-attack-sweep-host-impact.md) | What happened on the host when a full 100-intent `test_attacks.py` run ALLOWed several commands, recovery steps, and log excerpts. |
| [root-demo-policy-remediation.md](./root-demo-policy-remediation.md) | Remediation plan and status: classifier + policy sensitive-surface clamp, dry-run executor, live dry-run verification of the nine formerly-ALLOW intents, and remaining `intent_limits` / audit work. |
| [33.txt](./33.txt) | Example terminal log from a full attack sweep (includes per-intent PASS/FAIL). |

**Safety:** a full `test_attacks.py` sweep can run **real** `RUN_COMMAND` on the
machine when Guardian returns `ALLOW` unless the supervisor was started with
`INTENTFRAME_EXECUTOR_MODE=dry_run`. Prefer dry-run for local sweeps and use
real mode only for small benign subsets or a disposable VM. Do not treat
`[STUB]` as “commands are mocked” — the stub is the **agent**; the executor
may still be real.
