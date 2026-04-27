# Root-demo results

Artifacts from root-demo test runs, sweeps, and follow-up analysis. Nothing here is
part of the automated test harness; it is for operators and reviewers.

| File | Purpose |
| --- | --- |
| [2026-04-27-attack-sweep-host-impact.md](./2026-04-27-attack-sweep-host-impact.md) | What happened on the host when a full 100-intent `test_attacks.py` run ALLOWed several commands, recovery steps, and log excerpts. |
| [root-demo-policy-remediation.md](./root-demo-policy-remediation.md) | Plan: fix policy + classifier, add dry-run safety, and optional trace improvements. |
| [33.txt](./33.txt) | Example terminal log from a full attack sweep (includes per-intent PASS/FAIL). |

**Safety:** a full `test_attacks.py` sweep can run **real** `RUN_COMMAND` on the
machine when Guardian returns `ALLOW`. Prefer per-tactic subsets, a VM, or a
**dry-run executor** (see remediation doc) for repeated runs. Do not treat
`[STUB]` as “commands are mocked” — the stub is the **agent**; the executor
may still be real.
