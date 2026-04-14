# Executor Root Mode

Status: **demo-only note**. Root is not a recommended deployment mode and this document is not a product roadmap.

This document records the narrow intent behind executor root access in IntentFrame: a security/marketing demo that shows the Guardian still constrains the agent even when the executor has maximum local privilege. For normal usage on macOS, root is unnecessary and usually worse.

---

## Current state

Only one executor change is intentionally kept:

- The executor's `/health` endpoint reports `uid`, `euid`, `running_as_root`, and `pid`.

That lets us prove at runtime whether the executor is running as root without adding any new control plane, setup flow, or privilege-specific lifecycle code.

What does **not** exist:

- No supervisor-managed root mode
- No sudoers installer
- No `--root` setup path
- No socket permission fixup
- No launchd integration
- No CLI privilege/status plumbing

---

## Why root exists here at all

Root is only relevant for the demo story.

The point is not that a personal Mac agent needs root for normal work. It usually does not. The point is that IntentFrame can demonstrate a stronger containment claim:

- even if the executor is running as root
- even if the executor has the highest local POSIX privilege
- the Guardian and deterministic gates still remain the real safety boundary

That makes the demo more visceral. It is a proof-of-containment story, not a recommended operating model.

---

## Why root is not the real capability unlock on macOS

On macOS, `uid 0` is not the top meaningful boundary for most user-facing agent tasks.

- TCC sits above root for Mail, Messages, Photos, Contacts, Calendar, Screen Recording, Accessibility, Camera, Mic, and similar protected surfaces.
- SIP protects system locations that root still cannot freely modify from a live running system.
- A user-level agent with the right TCC grants can already do most of the valuable personal-assistant work.

So for day-to-day use, running as root mostly increases blast radius without unlocking much additional capability.

The honest framing is:

- user-level is the right default
- root is mostly negative-value operationally
- root is still useful as a demo stress test and marketing signal

---

## Demo operating model

For the demo, the simplest approach is to run the whole backend stack as root instead of building selective-root orchestration:

```bash
sudo uv run intentframe start
```

That keeps the story simple:

- supervisor, gateway, and executor all come up under the same privilege level
- there is no cross-UID lifecycle complexity to solve
- there is no need for sudoers plumbing
- there is no need for launchd plumbing

If we want to show that the executor is running as root, the existing `/health` endpoint is enough.

Example:

```bash
curl --unix-socket ~/.intentframe/run/executor.sock http://x/health
```

The response includes `uid`, `euid`, `running_as_root`, and `pid`.

---

## Client connectivity in the demo

Tests and the demo dashboard do not need to run as root just because backend services are running as root.

Uvicorn sets Unix domain socket permissions to `0o666` when binding, so local clients can still connect over the socket regardless of UID. This means the demo can run the backend as root while clients remain unprivileged.

This also means socket permissions are not the interesting security boundary here. The meaningful boundary remains IntentFrame's internal policy and execution gates.

---

## What we explicitly are not doing

During exploration, a more complex path was considered and then rejected for this demo:

- supervisor spawning only the executor via `sudo -n`
- installing scoped sudoers entries
- launchd-managed executor lifecycle
- root-specific shutdown protocols
- root-specific socket ownership/perms logic
- productizing executor root mode as a supported feature

Those ideas add complexity to startup, shutdown, configuration, and docs without improving the actual demo outcome we care about.

---

## Technical notes we want to preserve

Even though we are not shipping a full root-mode feature, two findings from the investigation are worth keeping:

1. **Uvicorn already handles Unix socket permissions broadly enough for local connectivity.**
   No `_fix_socket_perms_if_root` logic is needed for this demo path.

2. **The executor already has the right place to expose privilege state.**
   Reporting `uid` / `euid` / `running_as_root` from `/health` is sufficient to verify the demo state cleanly.
