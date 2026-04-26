# Current Terminal Policy Rationale

This document captures the current product and security thinking for
Jarvis terminal use in IntentFrame. It describes how the system behaves
today, why it behaves that way, and which trade-offs are intentional for
the current general-purpose release.

## Product Position

Jarvis today is not trying to be a developer-first coding agent like
Claude Code or a full terminal copilot. It is a general-purpose personal
assistant that can use the terminal when that helps with daily work.

That means the terminal should be useful for:

- inspecting local state,
- reading files and folders,
- transforming text,
- fetching public information,
- summarizing command output,
- using common POSIX tools,
- using Python for small data-processing tasks.

It does not yet need to support every heavy developer or administrator
workflow. If a developer needs to run destructive git commands, install
toolchains, execute local binaries, edit cron, reboot machines, or
perform root/admin maintenance, it is acceptable for the current Jarvis
release to say no or require the user to do that work themselves.

The current goal is balance: Jarvis should not feel useless when it uses
the terminal for normal assistant work, but IntentFrame should remain
cautious enough that a general-purpose assistant cannot easily turn into
an unsafe shell operator.

## Core Design Principle

The terminal surface is currently:

```text
shell + POSIX utilities + Python
```

The seeded Jarvis policy intentionally denies most other language and
toolchain surfaces:

- Node, Ruby, Perl, Java, Go, .NET, PHP, Lua, R, Julia, Swift, Deno/Bun
- local compiled binaries such as `./tool`
- compilation and build toolchains
- non-python/non-shell package ecosystems such as npm, gem, cargo, go,
  and composer

This is not because those tools are always bad. It is because the
current system is scoped to the language surfaces IntentFrame is ready
to reason about deterministically and semantically: shell/POSIX and
Python.

## Pipeline Model

For `RUN_COMMAND`, IntentFrame uses layered checks:

1. `command_shield` parses the command and emits deterministic facts:
   verdict, signals, capabilities, edges, and code-intel findings.
2. Deterministic Guardian applies seeded policy constraints:
   blocklisted substrings and denied capabilities.
3. Analysis Engine and Guardian review anything not deterministically
   allowed or blocked.
4. The executor runs only commands that survive the previous layers.

`command_shield` is intentionally a fact producer, not a full policy
engine. It does not know what the user asked for, whether the current
task justifies the action, or whether the user is operating in a root
demo. It gives downstream layers stable facts.

The most important consequence: `CATASTROPHIC` should be reserved for
commands that are unacceptable under the current product stance before
any semantic review is worth spending on.

## What Is Fast-Allowed

Jarvis can fast-allow only narrow, structurally read-only terminal
commands.

The Deterministic Guardian fast-path requires:

- shield verdict is `SAFE`,
- at least one `capability:read_only:*` tag is present,
- no incompatible capabilities are present,
- no network-probe capability is present,
- no edge/code-intel warning disqualifies the command,
- policy deny-capabilities do not match.

Examples that fit the spirit:

```sh
ls -la
cat README.md
df -h /
ps aux | grep nginx
git status
git log --oneline | head -50
```

This keeps common inspection work cheap while avoiding fast-paths for
network, writes, interpreter indirection, process spawning, and dynamic
shell behavior.

## What Is Reviewable

Some terminal use is useful and allowed in principle, but should not be
fast-allowed. These commands route through AE/Guardian.

Examples:

```sh
python3 -c "print(1)"
echo hello | python3 -c "import sys; print(sys.stdin.read().upper())"
curl -s https://api.github.com/repos/python/cpython
curl -s https://api.github.com/repos/python/cpython | jq .stargazers_count
curl -s https://api.github.com/repos/python/cpython | python3 -c "import json,sys; ..."
```

This is the right behavior for current Jarvis. Python and network are
useful for a personal assistant, but they are powerful enough that the
system should review them before execution.

## What Remains Hard-Blocked

The current release remains deliberately strict on several families.

Hard-blocked examples include:

- `curl ... | sh` and `wget ... | sh`
- reverse shells and `/dev/tcp` shell access
- destructive disk operations such as `mkfs`, `dd of=/dev/...`,
  `wipefs`, and destructive `diskutil erase*`
- `rm -rf /` and other root/home destructive patterns
- direct writes to device files
- `sudo`, `pkexec`, `doas`, `runuser`, and other privilege-escalation
  entry points
- SIP/Gatekeeper/NVRAM/kernel-extension/TCC mutations on macOS
- credential reads and exfiltration shapes
- cron/at/launchd persistence primitives
- destructive git operations such as `reset --hard`, `clean -fd`,
  `push -f`, and `stash clear`
- local binaries and unsupported language runtimes via policy

Many of these are legitimate in expert hands. That is not enough reason
to unblock them in the current general-purpose Jarvis. The current
product stance values a conservative default over supporting every
developer/admin workflow.

## Why Bash/Shell Stays

Shell is not the problem. Shell is the natural interface for many real
computer tasks:

- list files,
- inspect disk usage,
- count lines,
- search text,
- pipe data,
- combine small POSIX tools,
- use Python for small transformations.

The root demo also depends on `RUN_COMMAND` because real root/admin work
on a computer is often shell work. Removing shell would make the system
less useful and would not solve the core safety problem.

The right boundary is not "no shell." The current boundary is:

```text
allow shell/POSIX/Python as the reasoning surface;
hard-block known catastrophic effects;
review powerful-but-useful shapes;
deny unsupported runtimes/toolchains for now.
```

## The RCE-003 Decision

The main decision from this review was to demote:

```text
RCE-003: curl ... | python
```

from:

```text
CATASTROPHIC
```

to:

```text
NEEDS_REVIEW
```

### Why This Changed

`curl | python` is different from `curl | sh`.

`curl | sh` is a classic install/remote-code-execution shape. It remains
`CATASTROPHIC`.

`curl | python` can also be risky, but it is also a natural LLM-native
data-plumbing pattern:

```sh
curl -s https://api.github.com/repos/python/cpython \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['full_name'])"
```

Jarvis naturally writes commands like this to:

- fetch public JSON,
- parse API responses,
- summarize structured output,
- format terminal data into a human-readable answer.

Before the change, the same work could be expressed as pure Python and
would route to review, while the shell-pipe form was hard-blocked. That
was a syntax boundary, not a real safety boundary.

The current behavior is now:

- `RCE-003` still emits as a named signal,
- the command verdict becomes `NEEDS_REVIEW`,
- code inspection and AE/Guardian review still happen downstream,
- benign data-plumbing can proceed through review,
- `curl | sh` / `wget | sh` remain catastrophic.

This is the only unblock/demotion made from the broader discussion.

## Why We Did Not Unblock More

Several other false-positive or over-strict areas are known:

- grep/echo/search commands that mention words like `sudo`, `reboot`,
  or `shutdown`,
- home-scoped `rm -rf` cleanup,
- `find -exec rm -rf` and `xargs rm -rf`,
- destructive git commands,
- local binaries,
- package installers,
- cron/at scheduling,
- keychain reads,
- reboot/shutdown/admin operations.

These can be annoying for developers or administrators, but most are not
central to the current Jarvis product. They can remain blocked until
real users or community demand justifies more flexibility.

This is an intentional decision. The current Jarvis should be useful for
daily assistant work, not maximally permissive for every expert terminal
workflow.

## Root Demo Interpretation

The root demo is a stress test, not the default product experience.

It should demonstrate that:

- `RUN_COMMAND` can operate in a high-privilege environment,
- benign root-relevant inspection can work,
- known catastrophic primitives are still refused,
- the safety boundary does not disappear just because the executor is
  powerful.

The root demo does not require every possible admin workflow to be
available today. It is acceptable for some rare or expert root/admin
tasks to remain blocked while the product is still focused on general
Jarvis use.

## Current Decisions

Current decisions are:

1. Keep shell/POSIX/Python as the terminal reasoning surface.
2. Keep non-python/non-shell runtimes denied by policy.
3. Keep local binaries and compilation denied by policy.
4. Keep network use available but reviewed, not fast-allowed.
5. Keep ordinary `python3 -c` and shell-to-Python transformations
   reviewable, not fast-allowed.
6. Demote only `RCE-003` (`curl | python`) from `CATASTROPHIC` to
   `NEEDS_REVIEW`.
7. Keep `curl | sh` / `wget | sh` catastrophic.
8. Keep destructive/admin/persistence/credential patterns strict.
9. Defer developer-heavy flexibility until real usage shows it is worth
   the added risk and implementation complexity.

## Future Work

Possible future improvements, intentionally deferred:

- suppress keyword false positives inside obvious data positions, such
  as `grep "reboot"` or `echo "sudo means admin"`;
- add more precise path-aware handling for home-scoped cleanup;
- add trust/approval flows for official installer hosts;
- add richer policy knobs for users who explicitly want developer-agent
  behavior;
- add structured confirmation flows for expert admin tasks.

None of those are required for the current Jarvis release. The current
pragmatic fix is narrow: make LLM-native `curl | python` data plumbing
reviewable while keeping the rest of the conservative terminal boundary
intact.
