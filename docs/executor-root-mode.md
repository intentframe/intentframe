# Executor Root Mode

Status: **demo-only operator note**. This is intentionally narrow and is not the recommended default for local use.

IntentFrame now supports a **Jarvis root demo profile** on macOS where only the executor's `RUN_COMMAND` sandbox subprocess is allowed to escalate to root. The rest of the stack still runs as the normal user.

This exists for one reason: to demonstrate that IntentFrame's policy pipeline and deterministic gates still constrain an agent even when command execution has maximum local POSIX privilege available.

---

## What shipped

The current model is **not** "run the whole stack with `sudo`".

Instead, IntentFrame ships a small privilege-separation path:

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

- `INTENTFRAME_PROFILE=root`
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
INTENTFRAME_PROFILE=root \
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
cryptic *“a password is required”*-style error — the var still claims
the machine is armed, but the sudoers entry is gone. Prefer letting the
gateway set capability, or re-export `0` / unset the variable after
uninstall, or launch in a clean shell. The gateway-driven path avoids
this because it re-detects on every launch.

`Bootstrapper.reconcile` (policy + workspace seeding) runs with the
**gateway**; it does not run for supervisor-only. If you need the same
registry state the gateway would create (e.g. other profiles or
services), use:

```bash
INTENTFRAME_PROFILE=root python jarvis_pa/seed_policies.py
```

The script honors the same `INTENTFRAME_PROFILE` and `JARVIS_USER_ID`
env vars as bootstrap and is idempotent (GET-first, skip if present),
so running it after an auto-seeded gateway is a no-op. The
`demo/tests/root_demo/` Python harnesses seed their own test policy
and workspace in-process, so they can run against a supervisor started
as above without an extra `seed_policies` step.

### 3. Observe root-demo status in the CLI

The gateway's `/system/health` response now includes a `root_demo` block. The CLI renders that as a banner such as:

```text
Profile: root   Escalation: ARMED   Executor running_as_root: yes
```

If `--profile root` is requested but the installer has not been run yet, the CLI warns before startup and shows the install command.

When you quit the CLI, it also reminds you that root-demo is still installed and prints the uninstall command, because the sudoers entry survives gateway shutdown.

### 4. Uninstall when done

```bash
sudo bash intentframe_uninstall_root_demo.sh
```

That removes both the sudoers fragment and the marker file. The next gateway launch will advertise `INTENTFRAME_ESCALATION_ARMED=0`.

---

## Runtime truth model

Three different values matter here:

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

That means the health field communicates **effective root capability for `RUN_COMMAND`**, not just the process's own UID.

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

At startup, the pipeline probes executor health and freezes that into `ExecutionContext`. When `executor_running_as_root` is true, the analysis / policy layers can inject higher-scrutiny privilege-aware guardrails into their prompts and runtime reasoning.

For tests, `ExecutionContext` can still be constructed directly rather than probed.

---

## Files to know

- `jarvis_pa/executor_root.yaml` — root demo executor profile
- `executor/config/schema.py` — `sandbox.escalate`
- `executor/sandbox/planner.py` — threads `sandbox_escalate` into `ExecutionPlan`
- `executor/sandbox/platforms/macos.py` — conditional `sudo -n --preserve-env=... sandbox-exec` wrap
- `executor/server.py` — `/health.running_as_root`
- `intentframe_gateway/escalation.py` — shared root-demo detection logic
- `intentframe_gateway/server.py` — injects `INTENTFRAME_ESCALATION_ARMED`
- `intentframe_gateway/routes/system.py` — exposes `root_demo` in `/system/health`
- `intentframe_cli/main.py` — `--profile root` pre-flight warning
- `intentframe_cli/ui.py` — profile banner and uninstall hint
- `intentframe_setup_root_demo.sh` — installer
- `intentframe_uninstall_root_demo.sh` — uninstaller
- `intentframe_gateway/bootstrap.py` — runtime policy/workspace seeder (profile-aware)
- `jarvis_pa/seed_policies.py` — hand-runnable mirror of bootstrap for manual seeding
