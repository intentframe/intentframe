# Executor Root Mode

Status: **demo-only operator note**. This is intentionally narrow and is not the recommended default for local use.

IntentFrame now supports a **Jarvis root demo profile** on macOS where only the executor's `RUN_COMMAND` sandbox subprocess is allowed to escalate to root. The rest of the stack still runs as the normal user.

This exists for one reason: to demonstrate that IntentFrame's policy pipeline and deterministic gates still constrain an agent even when command execution has maximum local POSIX privilege available.

The root demo is not a benchmark of the agent's LLM, model provider, refusal
behavior, or prompt-injection resistance. It assumes the agent may already be
compromised and tests IntentFrame's runtime boundary instead: policy,
deterministic gates, command inspection, and the Analysis Engine / Guardian
layers that are hardened and tested against prompt-injection-style inputs.

---

## What shipped

The current model is **not** "run the whole stack with `sudo`". In the normal
root-demo path, the executor service process is still a normal-user process; the
root transition happens only for the child `sandbox-exec` argv that actually
runs an allowed `RUN_COMMAND`.

There are now two supported root-demo execution modes:

- **Dry-run decision mode** (recommended for local development and corpus sweeps):
  the runtime uses `DryRunExecutor`, so Analysis Engine and Guardian see a
  root-capable execution context but no command is ever shelled out on the host.
- **Real root-capable executor mode** (operator demo / end-to-end validation):
  IntentFrame uses the Jarvis root profile and per-command `sudo -n sandbox-exec`
  wrapping for allowed `RUN_COMMAND` actions.

The real executor path is a small privilege-separation path:

1. The CLI can start the gateway with `--profile root`.
2. The root profile uses `jarvis_pa/executor_root.yaml`.
3. That YAML sets `sandbox.escalate: sudo`.
4. A one-time installer writes a narrow sudoers entry for `sandbox-exec` and a user-space marker file.
5. On gateway startup, the gateway detects whether that root-demo capability is armed and exports `INTENTFRAME_ESCALATION_ARMED=0|1` to the supervisor / executor.
6. The executor only prepends `sudo -n` when **both** of these are true:
   - the machine capability is armed (`INTENTFRAME_ESCALATION_ARMED=1`)
   - the loaded executor config explicitly asks for it (`sandbox.escalate: sudo`)

So the root decision is split cleanly into:

- **machine capability**: can this Mac do root-demo right now?
- **session intent**: does this executor profile want to use that capability?

---

## Why this shape exists

The original idea of launching the whole IntentFrame stack as root was rejected because Unix privilege is process-wide:

- if the gateway runs as root, every child it starts inherits that privilege unless deliberately separated
- root-owned runtime files and logs then leak into normal development flow
- switching back and forth requires file ownership cleanup and creates unnecessary operational friction

The actual goal was narrower: let **`RUN_COMMAND`** execute under root for the demo, without making the whole product behave like a root-owned application.

This shipped model preserves that boundary.

Root operations on a computer are shell operations — `cat /etc/sudoers`, `tee /var/root/...`, `ls /var/db/sudo`. The root demo grants only `RUN_COMMAND` for that reason. Host-file, mail, calendar, and the other adapters target ordinary user-space workflows and are not part of the root surface; pairing them with the root profile would be a category mismatch (and they wouldn't escalate even if you tried, since `sandbox.escalate: sudo` only flows through the sandbox engine, which only wraps `RUN_COMMAND`).

---

## Why root is still mostly a demo story

On macOS, `uid 0` is not the highest practical boundary for many user-facing integrations:

- TCC still gates Mail, Messages, Photos, Contacts, Calendar, Screen Recording, Accessibility, Camera, and Mic
- SIP still protects important system locations
- many useful assistant workflows already work fine from a user-level process with the right TCC grants

So root is not the normal product value proposition. It is mainly useful as:

- a containment stress test
- a security demo
- a marketing proof point

---

## Operator flow

### 0. Recommended local test mode: dry-run

For most root-demo development, start the supervisor with a synthetic executor:

```bash
INTENTFRAME_EXECUTOR_MODE=dry_run \
INTENTFRAME_DRY_RUN_CONTEXT=root \
python -m supervisor.main start
```

This does **not** require `sudo bash intentframe_setup_root_demo.sh`, does not
load `jarvis_pa/executor_root.yaml`, and does not require
`INTENTFRAME_ESCALATION_ARMED`. The supervisor omits the real executor service
from its service graph, and the server wires `DryRunExecutor` into
`IntentFrameRuntime`; every allowed execution returns an `ExecutionResult` with
`data["dry_run"] == True`.

The root-demo test runner confirms this during preflight and then fails closed
if any later ALLOW result is missing the dry-run tag. This keeps the policy /
Guardian test surface real while preventing accidental host mutation.

Use real root-capable executor mode only when you explicitly need to validate the final
executor/sandbox/sudo path.

### 1. Install the root-demo capability once

```bash
sudo bash intentframe_setup_root_demo.sh
```

That installer writes two artifacts:

- `/etc/sudoers.d/intentframe-run`
- `~/.intentframe/state/root-demo.json`

The sudoers entry is intentionally narrow:

```text
<user> ALL=(root) NOPASSWD: SETENV: /usr/bin/sandbox-exec
```

`SETENV:` is required because the executor preserves a small allow-list of env vars across `sudo`:

- `PATH`
- `VIRTUAL_ENV`
- `PYTHONNOUSERSITE`
- `TMPDIR`

Without that preserve-list, macOS sudo's default `env_reset` behavior would strip the executor venv wiring and the sandboxed shell would silently fall back to system `python3`.

### 2. Launch the CLI with the root profile

```bash
intentframe-gateway-cli --profile root
```

The CLI translates that into:

- `JARVIS_VARIANT=root`
- `EXECUTOR_CONFIG=jarvis_pa/executor_root.yaml` (only if the operator did not already set `EXECUTOR_CONFIG`)

### 2a. (Alternative) Launch supervisor directly (faster dev loop)

If you are running the supervisor **without** `intentframe-gateway-cli`,
you must supply the same **three** pieces the gateway would otherwise
set: profile, executor YAML, and machine capability for root-demo.

**Faster dev loop** (no gateway process, no credential-vault checks, no
CLI/gateway teardown cycle). This is only appropriate when
`sudo bash intentframe_setup_root_demo.sh` has already been run
successfully on this machine — otherwise `sandbox.escalate: sudo` in
`executor_root.yaml` will not have a working `sudo -n` path.

```bash
JARVIS_VARIANT=root \
EXECUTOR_CONFIG=jarvis_pa/executor_root.yaml \
INTENTFRAME_ESCALATION_ARMED=1 \
python -m supervisor.main start
```

The gateway normally injects `INTENTFRAME_ESCALATION_ARMED=0|1` on **each
launch** after re-reading `~/.intentframe/state/root-demo.json` and
`/etc/sudoers.d/intentframe-run` (`intentframe_gateway/escalation.py`).
A bare supervisor has no such step: nothing sets this variable unless
you do, so the executor will not enable `sudo -n` wrapping unless
`INTENTFRAME_ESCALATION_ARMED=1` is present when the executor starts.

**Footgun (manual `INTENTFRAME_ESCALATION_ARMED=1`)**: if you **uninstall**
root-demo (sudoers + marker removed) but leave `INTENTFRAME_ESCALATION_ARMED=1`
in your shell profile or a script, `sudo -n` can fail at runtime with a
cryptic *"a password is required"*-style error — the var still claims
the machine is armed, but the sudoers entry is gone. Prefer letting the
gateway set capability, or re-export `0` / unset the variable after
uninstall, or launch in a clean shell. The gateway-driven path avoids
this because it re-detects on every launch.

`Bootstrapper.reconcile` (policy + workspace seeding) runs with the
**gateway**; it does not run for supervisor-only. If you need the same
registry state the gateway would create (e.g. other profiles or
services), use:

```bash
JARVIS_VARIANT=root python jarvis_pa/seed_policies.py
```

The script honors the same `JARVIS_VARIANT`, `INTENTFRAME_USER_ID`
(and the back-compat `JARVIS_USER_ID`) env vars as bootstrap and is
idempotent (GET-first, skip if present),
so running it after an auto-seeded gateway is a no-op. The
`demo/tests/root_demo/` Python harnesses seed their own test policy
and workspace in-process, so they can run against a supervisor started
as above without an extra `seed_policies` step.

### 2b. Verify with the root-demo test harness

The Python harnesses under `demo/tests/root_demo/` are black-box pipeline
tests: each fixture submits an intent, receives an `ExecutionResult`, and
asserts the observed decision matches the fixture's `expected_decision`.
They do not assert which internal gate made the decision.

Every suite starts with a preflight before evaluating fixtures:

```text
RUN_COMMAND whoami
```

That preflight goes through the same Actor → IntentFrame → executor path as
the fixtures. It accepts one of two outcomes:

- dry-run mode: `ExecutionResult.data["dry_run"] == True`
- real mode: command output is exactly `root`

If neither is true, the suite exits non-zero instead of letting root-only
commands fail later with misleading permission errors.

```bash
python demo/tests/root_demo/test_normal.py
python demo/tests/root_demo/test_general.py
python demo/tests/root_demo/test_attacks.py
```

Current full-sweep proof artifacts (policy: `test_policy_root_admin_assistant.yaml`):

- `demo/tests/root_demo/results/attacks/attacks_assistant_policy_dry_run.txt` — 100 / 100 attack intents blocked
  in dry-run mode.
- `demo/tests/root_demo/results/attacks/attacks_assistant_policy_real_run.txt` — 100 / 100 attack intents blocked
  against the real root-capable executor path, with preflight `whoami == root`.

Exit status is part of the contract:

- `0`: preflight passed and every selected intent matched `expected_decision`
- `1`: preflight failed or at least one selected intent failed
- `2`: invalid CLI argument or unknown intent number

### 3. Observe root-demo status in the CLI

The gateway's `/system/health` response now includes a `root_demo` block. The CLI renders that as a banner such as:

```text
Profile: root   Escalation: ARMED   Executor running_as_root: yes
```

The final field is intentionally a capability signal, not a literal statement
that the executor service process has `euid == 0`. In the supported root-demo
path, `/health` will usually report a normal-user `uid` / `euid` while
`running_as_root` is true because `INTENTFRAME_ESCALATION_ARMED=1` tells the
executor that its internal `RUN_COMMAND` sandbox path can wrap with
`sudo -n sandbox-exec`.

If `--profile root` is requested but the installer has not been run yet, the CLI warns before startup and shows the install command.

When you quit the CLI, it also reminds you that root-demo is still installed and prints the uninstall command, because the sudoers entry survives gateway shutdown.

### 4. Uninstall when done

```bash
sudo bash intentframe_uninstall_root_demo.sh
```

That removes both the sudoers fragment and the marker file. The next gateway launch will advertise `INTENTFRAME_ESCALATION_ARMED=0`.

---

## Runtime truth model

Five different values matter here:

### `INTENTFRAME_EXECUTOR_MODE`

This is read by `intentframe_server/server.py` at runtime startup:

- unset / `"real"`: the runtime uses `ExecutorHTTPClient` and talks to the
  executor service over UDS (normal production path)
- `"dry_run"`: the runtime uses `DryRunExecutor`; no real I/O is performed

The supervisor also reads this value. In dry-run mode it does not start the
standalone executor service and removes `executor` from
`intentframe-core.depends_on`. Unknown values raise at startup. This is
deliberate: typos must never silently fall back to a less-safe mode.

### `INTENTFRAME_DRY_RUN_CONTEXT`

Only meaningful when `INTENTFRAME_EXECUTOR_MODE=dry_run`.

- `"user"` (default): reports the current process uid/euid
- `"root"`: reports `uid=0`, `euid=0`, `running_as_root=True`

The root-demo suite uses `root` so Guardian evaluates the same privilege
posture it would see from the real root-capable executor path, without
executing commands.

### `sandbox.escalate`

This lives in executor config and captures **intent**.

- `"none"`: run sandboxed commands under the executor's own UID
- `"sudo"`: ask the macOS sandbox engine to prepend `sudo -n`

This value alone does **not** prove root capability.

### `INTENTFRAME_ESCALATION_ARMED`

This is the gateway-injected environment variable and captures **machine capability**.

It is set from shared detection logic in `intentframe_gateway/escalation.py`, which checks:

- whether the marker file exists and parses
- whether the referenced sudoers file still exists

The executor uses this env var as its single runtime source of truth for "is root-demo actually armed on this machine right now?"

### `running_as_root`

The executor's `/health` endpoint reports:

- `uid`
- `euid`
- `running_as_root`
- `pid`

`running_as_root` is true when either:

- the executor process really is running as UID 0
- `INTENTFRAME_ESCALATION_ARMED=1`

In normal root-demo operation the second case is the important one. The
executor's process `uid` / `euid` remain the invoking user, but allowed
`RUN_COMMAND` children can be launched through the root-capable
`sudo -n sandbox-exec` path. That means the health field communicates
**effective root capability for `RUN_COMMAND`**, not the executor process's own
UID.

This was deliberate: the health signal should describe what the machine can do, while the YAML decides whether a given session chooses to use it.

---

## Command execution path

When `RUN_COMMAND` is sandboxed on macOS:

1. `SandboxPlanner` builds an `ExecutionPlan`.
2. The plan carries `sandbox_escalate`.
3. `MacOSSandboxEngine.wrap()` builds the `sandbox-exec` argv.
4. If `sandbox_escalate == "sudo"` and `INTENTFRAME_ESCALATION_ARMED == "1"`, the engine wraps with:

```bash
sudo -n --preserve-env=PATH,VIRTUAL_ENV,PYTHONNOUSERSITE,TMPDIR sandbox-exec ...
```

5. If the machine is disarmed, the command runs unprivileged.
6. If sudoers is revoked mid-session, `sudo -n` fails and that error is surfaced rather than silently retrying unprivileged.

This keeps failures honest: when the operator asked for root, the operator should hear if root is no longer available.

---

## Security boundary and caveats

The sudoers line is intentionally narrow, but it is **not** itself the hardening layer.

A hostile local user could still try to invoke `sandbox-exec` directly with a permissive profile. The actual protection in the intended demo threat model is:

- upstream Guardian / Analysis Engine review
- `command_shield` catastrophic-command blocking
- internal argv construction inside the executor

In other words:

- this is safe enough for the demo threat model
- it is not designed to defend against a fully hostile local shell user

That distinction is important and should not be blurred in product messaging.

---

## What did not ship

The following still do **not** exist:

- a general-purpose supported "run IntentFrame as root" product mode
- launchd-specific root orchestration
- root-specific socket ownership hacks
- a broad `sudoers` grant like `NOPASSWD: ALL`
- agent-authored `sudo` as an allowed command path

The design stayed intentionally small: one installer, one marker, one gateway detection helper, one executor config bit, one CLI surface.

---

## Pipeline / prompt implications

The IntentFrame runtime still treats executor privilege as a real risk signal.

At startup, the pipeline probes executor health and freezes that into
`ExecutionContext`. In real mode the probe comes from the executor service. In
dry-run mode it comes from `DryRunExecutor.health()`. When
`executor_running_as_root` is true, the analysis / policy layers can inject
higher-scrutiny privilege-aware guardrails into their prompts and runtime
reasoning.

For tests, `ExecutionContext` can still be constructed directly rather than probed.

