# Root Demo Policy Design

Status: design note for `demo/tests/root_demo/test_policy_root_admin_assistant.yaml`.

This document explains the root demo policy shape: what the policy allows, what
it blocks, and why it is written as a device-boundary-first policy rather than a
privacy-first policy.

The root demo exists to show that IntentFrame can constrain an agent even when
`RUN_COMMAND` has effective root capability. The goal is not to make root mode a
normal product default. It is to demonstrate a useful autonomous assistant
operating under owner-defined runtime boundaries.

## Core Principle

The policy protects the Mac's device and authentication boundaries first.

The agent is allowed to work with ordinary user content when that is relevant to
the task. A useful personal assistant may need to read documents, organize
downloads, inspect project files, summarize mail, look at messages, work with
browser history, or process application data. Treating all personal content as
off-limits would make the demo unrealistic and would hide the main point of
IntentFrame: the owner can hand useful work to an agent while still enforcing
hard limits.

The protected boundary is different:

- Do not let the agent gain authentication power.
- Do not let the agent change how the Mac connects, trusts, authenticates, or
  exposes itself.
- Do not let the agent create new access paths or remote-control channels.
- Do not let the agent silently move local data elsewhere.
- Do not let the agent perform broad or irreversible damage as normal autonomous
  work.

In short: user content is usable; credentials, trust boundaries, and device
control are not.

## Agent-Agnostic Policy

The policy is not written as instructions to a specific agent persona. It is the
owner's system policy. Any agent using this root-capable profile is evaluated
against the same boundaries.

That matters because IntentFrame is enforcing policy at runtime. The policy
should describe what is allowed on the system, not who the agent is supposed to
be. This also keeps the root demo useful for different agents and future test
corpora.

## Command Shield And RUN_COMMAND

Most `command_shield` detections and `deny_capabilities` in this root policy are
device-boundary or authentication-boundary capabilities. They are especially
important for `RUN_COMMAND`, because shell commands are the broadest and most
dangerous interface.

They protect against:

- device control: disk erase, raw device writes, boot changes, kernel, MDM, and
  security daemon changes
- trust and network mutation: DNS, hosts files, routes, hostnames, firewalls,
  certificates, browser security, and time sync
- access creation: users, admin rights, sudoers, SSH keys, remote login, and
  tunnels
- authentication power: keychain, cookies, sessions, private keys, cloud tokens,
  password-manager data, and process environment or memory
- irreversible damage: `rm -rf /`, broad deletion, formatting, and destructive
  obfuscation
- hidden control or execution: launchd or cron persistence, curl-pipe-shell,
  reverse shells, and encoded payloads

This matters more for `RUN_COMMAND` than for normal app actions because
`RUN_COMMAND` can express almost any host operation. The policy therefore needs
strong structural protection before the semantic Guardian reasons about intent.

The key design choice is: hard-deny device, authentication, and control surfaces;
semantically judge useful local work. That keeps root command execution useful
for maintenance while preventing the agent from taking over, weakening, or
leaking the machine.

## Hard Denies

Hard denies are used for surfaces that should not be available to autonomous
root execution at all. These are blocked before the semantic Guardian decision.

### Language And Execution Clamp

The root demo keeps the automatic command surface narrow: shell, Python, and
normal POSIX utilities.

Other language runtimes, local binaries, compilation, stdin execution into
non-shell/non-Python runtimes, and non-shell/non-Python package ecosystems are
hard-denied. This reduces the execution surface without preventing normal local
maintenance.

### Authentication-Power Reads

Some local data is not ordinary content. It grants the ability to act as the
user or pivot elsewhere.

Hard-denied examples include:

- browser cookies and live browser sessions
- password and credential material
- private dotfile secrets
- cloud tokens
- password-manager exports
- process environments
- process memory
- SSH known-hosts and similar remote-access trust inventories

The distinction is not whether the data is personal. The distinction is whether
touching it gives the agent authentication power, unlocks accounts, reveals
secrets, or supports remote-access targeting.

### Remote-Control Channels

`ssh_tunnel` remains hard-denied. Even when external transfer can sometimes be
task-relevant, a tunnel creates a new way through or into the machine. That is a
device-boundary change, not normal content handling.

### Trust, Access, Security, And Network Mutations

The policy hard-denies actions that change how the Mac connects, trusts,
authenticates, or exposes itself.

Examples include:

- network configuration, hostnames, time sync, and hosts files
- firewall, security daemon, browser security, privacy, and audit settings
- user accounts, admin rights, sudo access, and remote access
- disk encryption, boot policy, kernel tunables, kernel extensions, and MDM
  profiles
- browser extensions, certificate trust, screen sharing, radio power, and print
  configuration
- history tampering

Some of these can be legitimate admin tasks in rare cases. They are still poor
defaults for unattended root autonomy because they change trust boundaries rather
than perform routine maintenance.

## Semantic Boundaries

The semantic `intent_limits` cover dual-use areas where the action surface alone
is not enough to decide. Guardian receives these limits as trusted policy
context and evaluates whether the action's purpose and scope fit the owner's
boundaries.

### Local Maintenance Is Allowed

The policy explicitly permits autonomous local maintenance:

- inspecting system state
- reading non-secret configuration
- listing files and checking disk usage
- reading logs
- cleaning named temporary files, caches, old logs, and test artifacts
- creating local backups
- organizing files in named local paths
- managing named local services
- running shell or Python maintenance scripts

The action should name what it changes: path, file, service, or setting. This
gives Guardian positive context for benign work and makes vague broad changes
easier to block.

### User Content Is Allowed When Task-Relevant

Ordinary user content is not blocked by default. Documents, downloads, project
files, notes, mail, messages, browser history, application data, logs, and shell
history may be used when relevant to the requested task.

The policy still blocks hidden collection, staging, summarization, or searching
for unrelated reasons. This is where IntentFrame's semantic layer matters: the
same file read can be benign when it serves the task and suspicious when it is
secretly collecting context for another purpose.

### Visible Maintenance Automation Is Allowed

Backups, service changes, scheduled jobs, shell aliases, PATH entries, and other
persistent maintenance can be useful. The policy allows them only when they are:

- visible
- clearly named
- local to the machine
- reversible
- directly related to maintenance, backups, cleanup, rotation, health checks, or
  user productivity

Hidden jobs, disguised names, credential-gathering scripts, network beacons,
remote-control behavior, or unrelated persistence are blocked.

This is why some deterministic-only capabilities are not hard-denied in the
admin-assistant profile: `backup`, `service_mgmt`, `launchd_mutation`,
`cron_mutation`, `shell_init`, and broad `persistence` are useful only when
Guardian has semantic context.

### External Transfer Is Intent-Based

Downloading public resources is normal. Sending local content out is different.

The policy allows external transfer only when the task clearly requires that
exact transfer, destination, and purpose. Silent uploads, bulk collection, hidden
staging, credential transfer, unrelated posting, or unexplained destinations are
blocked.

This keeps user-requested sharing possible without treating root shell exfil as
normal behavior.

### Broad Or Irreversible Changes Are Blocked

The policy blocks broad or irreversible changes for autonomous root execution:

- deleting personal files
- removing backups or archives
- wiping storage
- formatting devices
- modifying broad areas of the filesystem
- making irreversible changes as normal work

Scoped cleanup of clearly named temporary files, caches, logs, and test artifacts
is allowed when the affected path and purpose are clear.

This uses `effect: block` because the current Guardian runtime has only binary
decisions: `ALLOW` and `BLOCK`. A separate `require_confirmation` effect would
read well in policy, but there is no first-class confirmation state today. Until
that exists, broad destructive actions should be represented as blocks.

## Why Not Preserve The Deterministic-Only Policy Exactly?

`test_policy_root_determinstic_only.yaml` proves that root can be contained with
hard gates. The admin-assistant policy has a different job: prove that root can
remain useful while bounded.

Keeping every deterministic-only mutation deny would make the profile much less
useful. It would block backups, service management, scheduled maintenance,
shell convenience changes, and visible maintenance persistence. Those are normal
assistant tasks, and they are exactly where semantic policy adds value.

The admin-assistant policy therefore keeps hard denies for device and
authentication boundaries, while leaving useful local maintenance to Guardian's
semantic judgment.

## Practical Summary

Allowed by design:

- task-relevant user content work
- local maintenance
- scoped backups
- named service management
- visible scheduled maintenance
- shell/Python maintenance scripts
- named cleanup of temp files, caches, logs, and test artifacts
- explicit, task-required external transfers

Blocked by design:

- credential, token, session, keychain, and process-secret access
- remote-access trust inventories such as SSH known-hosts
- hidden or disguised persistence
- network, hosts, DNS, routing, proxy, VPN, hostname, and time changes
- security, privacy, firewall, certificate, boot, kernel, MDM, audit, and
  browser trust changes
- new users, admin rights, sudo access, SSH keys, screen sharing, tunnels, or
  remote login
- broad or irreversible destructive work

This policy demonstrates the intended IntentFrame story: the owner can let an
agent operate freely enough to be useful on a real Mac, while runtime policy
prevents the agent from taking control of the device, weakening it, extracting
authentication power, or doing irreversible damage.
