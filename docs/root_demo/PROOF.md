# Root Demo Proof Snapshot

Status: current evidence package for the root + compromised-agent demo.

## Claim

The root demo tests post-compromise containment, not model jailbreak resistance.

If an authenticated agent submits adversarial `RUN_COMMAND` intents through the
supported IntentFrame boundary, the policy pipeline should block unauthorized
root-level effects before they reach execution.

## Privilege Model

The supported root-demo path does **not** run the whole stack as UID 0.

- The gateway, policy services, IntentFrame runtime, Jarvis agent, and executor
  service process run as the normal user.
- `intentframe_setup_root_demo.sh` installs a narrow sudoers entry:
  `<user> ALL=(root) NOPASSWD: SETENV: /usr/bin/sandbox-exec`.
- The gateway detects that installer state and exports
  `INTENTFRAME_ESCALATION_ARMED=1` to the supervisor / executor.
- `executor/server.py` reports `running_as_root=True` as an effective
  `RUN_COMMAND` root-capability signal. It does not mean the executor service
  process has `euid == 0`.
- Only an allowed `RUN_COMMAND` child wrapper can request root through
  `sudo -n sandbox-exec`.

## Methodology

The agent submitting attack intents is a deterministic stub harness, not a live
LLM. It uses the same Actor handshake, policy-bound session, submit path, and
pipeline as a real LLM-backed agent — it differs only in that it submits fixed
fixture intents instead of generating them. This is a post-compromise crash
test: it starts after the agent has already failed and asks whether the runtime
boundary contains the result. Model jailbreak quality is out of scope.

## Evidence

The current attack corpus contains 100 adversarial `RUN_COMMAND` intents across
destruction, persistence, privilege escalation, credential access, defense
evasion, exfiltration, impact, obfuscation, interpreter indirection,
reason/target mismatch, and realistic macOS host/network/security mutation.

Post-remediation runs:

- `demo/tests/root_demo/results/deny_cap_only_dry_run.txt`: 100 / 100 expected `BLOCK`,
  dry-run executor, preflight confirms `data["dry_run"] == True`.
- `demo/tests/root_demo/results/deny_cap_only_real_run.txt`: 100 / 100 expected `BLOCK`,
  real root-capable executor path, preflight confirms `whoami == root`.

The corresponding core logs are:

- `demo/tests/root_demo/results/deny_cap_only_dry_run_intentframe_logs.txt`
- `demo/tests/root_demo/results/deny_cap_only_real_run_intentframe_logs.txt`

## Failure And Remediation

The 2026-04-27 live sweep exposed nine `ALLOW` mismatches that changed host
state, including DNS and hostname mutation. That incident is preserved in
`demo/tests/root_demo/docs/2026-04-27-attack-sweep-host-impact.md`.

The remediation added sensitive-surface capability tags and deny-capabilities
for root-level host mutation, credential/session reads, browser/security
preference mutation, and exfiltration staging. The current dry-run and real
sweeps show those formerly-ALLOW intents now block at
`deterministic_guardian` / `matched_gate=constraint`.

See `demo/tests/root_demo/docs/root-demo-policy-remediation.md` for the full
timeline and remaining work.

## What This Does Not Prove

This proof does not claim:

- the agent model cannot be prompt-injected;
- the Guardian LLM is impossible to fool on all semantic cases;
- the sudoers installer defends against a hostile local shell user;
- actions outside the Actor -> IntentFrame -> executor path are contained;
- IntentFrame replaces OS sandboxing, EDR, MDM, or human approval;
- cumulative multi-intent abuse is fully solved.

Remaining hardening work is tracked in `TODO/root-demo-policy-driven-sandbox.md`,
especially semantic `intent_limits` and audit-side verification.
