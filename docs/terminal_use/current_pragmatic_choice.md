This document records the pragmatic decisions made in the recent review
of LLM-native terminal use in Jarvis. `curl | python` was not the only
surface affecting that use case, but it was the only one with a strong
product-level reason to demote, and that demotion has been made:
`RCE-003` is now `NEEDS_REVIEW`, not `CATASTROPHIC`.

The current path:

- `command_shield` gives verdicts early from fixed patterns / structural signals before capabilities or code inspection matter.
- Bootstrap seeds `RUN_COMMAND` with only this policy blocklist: `sudo`, `rm -rf /`, `mkfs`, `dd if=`, `> /dev/`, `chmod 777`.
- Bootstrap also denies non-python/shell capabilities: node/ruby/perl/java/go/etc, local binaries, compilation, npm/gem/cargo/go/composer installs.
- Deterministic Guardian only fast-allows `RUN_COMMAND` when shield verdict is `SAFE`, capability is `read_only:*`, and there are no edge/code findings.

Key references:
- `command_shield/pipeline.py`
- `intentframe_gateway/bootstrap.py`
- `intentframe_components/guardian/checkers/terminal.py`
- `intentframe_components/guardian/deterministic.py`

## What Actually Affects Jarvis Today

### 1. `curl | python` was the real hard contradiction

The bootstrap policy allows `stdin_exec:python`. Before the `RCE-003`
demotion, shield blocked this before policy could evaluate it:

```sh
curl -s https://api.github.com/repos/python/cpython | python3 -c "import json,sys; ..."
```

Current result:
- Shield: `NEEDS_REVIEW` via `RCE-003`
- Bootstrap policy: would otherwise pass
- Pure-python equivalent: `NEEDS_REVIEW`, not blocked

This is now consistent: shell-to-Python data plumbing is not
fast-allowed, but it is reviewable. The pattern still produces an
audit signal, while AE/Guardian retain the final decision.

### 2. Every `python3 -c` becomes `NEEDS_REVIEW`

Examples:

```sh
echo hello | python3 -c "import sys; print(sys.stdin.read().upper())"
cat notes.txt | python3 -c "import sys; print(len(sys.stdin.read().split()))"
python3 -c "import urllib.request,json; ..."
```

These are not blocked, but they always trigger review because of `interpreter-indirection`.

This is acceptable for current Jarvis: it imposes cost/latency, not a wall. The cautious posture is intentional.

### 3. Public web/API fetches are allowed, but not fast-allowed

```sh
curl -s https://api.github.com/repos/python/cpython
curl -s https://api.github.com/repos/python/cpython | jq .stargazers_count
```

These pass shield and policy.

But because `network_probe:*` is deliberately not a read-only fast path, they still go through AE/Guardian. This is consistent with the current release: Jarvis can use network, but network is reviewed.

### 4. Word false positives can block normal research

These are the other real product-facing false positives:

```sh
grep -r "sudo" ~/Documents
grep -r "reboot" ~/Documents
grep -r "shutdown" ~/Documents
echo "sudo means admin"
```

Results:
- `sudo` hits both command-shield `IF-SUDO-001` and bootstrap substring blocklist.
- `reboot` / `shutdown` hit command-shield catastrophic patterns.

This can affect a general Jarvis task like “search my notes/logs for why my Mac rebooted” or “explain what sudo means.” But compared to `curl | python`, it’s less central to LLM terminal operation.

### 5. Local binaries are blocked by policy

```sh
./script --help
./tool --version
```

Blocked by:

```text
capability:script_execution:local_binary
```

This is intentional in the python+shell-only scope. It can affect “run this downloaded CLI” or “run project script,” but that is more developer/power-user territory. Should remain blocked for now.

### 6. Non-python runtimes and package managers are blocked

```sh
node -e "console.log(1)"
npm install left-pad
go run main.go
cargo install ...
```

Blocked by bootstrap `deny_capabilities`.

This is consistent with the current design. Unblocking is deferred until Jarvis takes on more developer-agent scope.

## Outcome

The only change made in this review is:

1. **Demote `RCE-003` from `CATASTROPHIC` to `NEEDS_REVIEW`.**  
   This directly supports LLM-native terminal data processing while still letting AE/Guardian inspect the command.

Still optional, not part of this change:

2. **Fix keyword false positives for grep/echo/search contexts.**  
   `grep "reboot"`, `grep "shutdown"`, `grep "sudo"`, and `echo "sudo..."` should not be catastrophic just because the word appears as data.

Everything else can stay cautious:
- `curl | sh`
- package installers
- reboot/shutdown execution
- cron/at
- local binaries
- npm/node/go/ruby/etc
- destructive git
- chmod/rm/disk/root patterns

Net result: **the must-fix for the stated product goal has shipped — `curl | python` now routes to review.** The second-tier issue is keyword false positives in research/search commands. The remaining categories are aligned with the cautious, non-dev-copilot Jarvis posture.