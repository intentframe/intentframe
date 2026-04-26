## Current Deterministic Gate Mapping

This snapshot reflects the current pragmatic choice: **`curl | python`
is no longer a hard-stop pattern**. It still emits `RCE-003`, but the
verdict is now `NEEDS_REVIEW` so AE/Guardian can inspect the command
context and the Python body. `curl | sh` / `wget | sh` remain
`CATASTROPHIC`.

### 1. Official package installers

Most industry-standard installer one-liners are still hard-blocked.
The one intentional exception is Python stdin execution, because the
same shape is also useful for LLM-native JSON/data plumbing.

| Tool | Command | Block |
|---|---|---|
| rustup | `curl -sSf https://sh.rustup.rs \| sh` | `RCE-001` |
| uv (Astral) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | `RCE-001` |
| Docker | `wget -qO- https://get.docker.com \| sh` | `RCE-002` |
| pnpm | `curl -fsSL https://get.pnpm.io/install.sh \| sh -` | `RCE-001` |
| Bun | `curl -fsSL https://bun.sh/install \| bash` | `RCE-001` |
| Poetry | `curl -sSL https://install.python-poetry.org \| python3 -` | `RCE-003` → `NEEDS_REVIEW` |
| NodeSource | `curl ... \| sudo -E bash -` | `IF-SUDO-001` |

Homebrew's `/bin/bash -c "$(curl ...)"` still gets `NEEDS_REVIEW`
through interpreter indirection. The current stance is not to broaden
installer support yet; most installer pipes remain cautious hard stops.

### 2. Core git workflow — all CATASTROPHIC

```
git reset --hard HEAD               → DCG-GIT-RESET-HARD
git reset --hard origin/main        → DCG-GIT-RESET-HARD
git clean -fd                       → DCG-GIT-CLEAN-FORCE
git clean -fdx                      → DCG-GIT-CLEAN-FORCE
git push --force                    → DCG-GIT-PUSH-FORCE
git push -f origin my-branch        → DCG-GIT-PUSH-FORCE-SHORT
git stash clear                     → DCG-GIT-STASH-CLEAR
```

Every feature-branch developer does these dozens of times a day. `--force-with-lease` passes, but nobody types that; the blanket `-f` block catches the muscle-memory form.

### 3. Home-directory `rm -rf` — the most common cleanup idiom

```
rm -rf ~/node_modules        → DEL-001
rm -rf ~/.cache/pip          → DEL-001
rm -rf ~/Downloads/tmp-build → DEL-001
rm -rf ~/my-project/.venv    → DEL-001
```

`rm -rf node_modules` (same effect, cwd-relative) is `SAFE`. So the pattern is not blocking the action, it's blocking the *syntax* of `~`. The workaround is `cd ~ && rm -rf node_modules`, which is **less** auditable, not more.

### 4. Standard `find`/`xargs` cleanup idioms

```
find . -name "__pycache__" -type d -exec rm -rf {} +   → WRAP-010 🚫
find . -name "*.tmp" | xargs rm -rf                     → WRAP-009 🚫
find . -name "*.tmp" | xargs rm -f                      → SAFE ✅
find . -name "*.pyc" -delete                            → SAFE ✅
```

These are in every Makefile, every CI cleanup script, every "how to clean Python projects" tutorial. The `-r`/`-rf` flag flips it from SAFE to CATASTROPHIC even on `./` scope.

### 5. `grep`/`cat` on log files — intent-blind keyword hits

```
git log --oneline | grep reboot     → DCG-REBOOT 🚫
cat server.log | grep -i "reboot"   → DCG-REBOOT 🚫
grep -r "shutdown" .                → DCG-SHUTDOWN 🚫
grep -r sudo /etc/sudoers.d/        → IF-SUDO-001 🚫
```

The `\breboot\b` / `\bshutdown\b` / `\bsudo\b` patterns match the literal word anywhere — including inside a grep *pattern argument*. This breaks log analysis entirely. An SRE agent that can't search logs for "reboot" or "shutdown" events is useless for incident response.

### 6. Basic sysadmin primitives

```
reboot               → DCG-REBOOT
shutdown -h now      → DCG-SHUTDOWN
crontab -e           → IF-CRONTAB-EDIT-001
echo "..." | crontab - → IF-CRONTAB-STDIN-001
at 3pm -f ~/task.sh  → IF-AT-SCHEDULE-001
```

Cron/at are the **only** POSIX way to schedule work. Blocking `crontab -e` means an operations agent can't manage scheduled jobs at all.

### 7. Keychain reads (macOS)

```
security find-generic-password -s "my-service" -w   → MAC-KEY-003 🚫
```

`-w` is the only way to retrieve a secret programmatically. The rule assumes any use of `-w` is exfiltration, but it's also how legitimate tooling (CLI creds, password managers) reads secrets the user stored.

### 8. Scoped `chmod`

```
chmod -R 777 ./playground    → SYSD-002 🚫
chmod -R 755 ./my-project    → SAFE ✅
```

`777` recursive on a local subdirectory is unwise but not catastrophic — the scope is a single project folder. Blanket-blocking `-R 777` regardless of scope is the same class of mistake as the `~/` rm block: it's pattern-matching without reading the target.

### 9. `sh -c` inside container isolation

```
docker run --rm -it alpine sh -c "rm -rf /tmp/foo"   → WRAP-001 🚫
```

The `rm -rf` happens inside an ephemeral container that will be deleted on exit. The pipeline reads the inner `sh -c "...rm -r..."` and blocks at the wrapper layer, ignoring that `docker run --rm` establishes full isolation. Same pattern would block `ssh remote "rm -rf /tmp"` for remote ops where the command is evaluated elsewhere.

### 10. Every `python3 -c` invocation — latency tax

Not catastrophic, but every single one goes to `NEEDS_REVIEW` due to
`interpreter-indirection`. This includes `curl | python`, which also
emits the `RCE-003` signal:

```
cat data.csv | python3 -c "print(sum(1 for _ in sys.stdin))"   → NEEDS_REVIEW
echo hi | python3 -c "print(sys.stdin.read().upper())"          → NEEDS_REVIEW
python3 -c "print(base64.b64decode('aGVsbG8=').decode())"       → NEEDS_REVIEW
curl -s https://api.github.com/repos/python/cpython | python3 -c "import json,sys; ..." → NEEDS_REVIEW (RCE-003)
```

That's an LLM roundtrip on every trivial Python one-liner. For the
current Jarvis release this is acceptable: Python remains available for
LLM-native terminal data processing, but it is not fast-allowed.

## Summary by workflow category

| Category | Current result | Rate | Notes |
|---|---|---|---|
| Package installers | 7/10 hard-blocked, 1/10 review | 70% hard-blocked | Python stdin installer shape now reviews via `RCE-003` |
| Git daily ops | 7/9 hard-blocked | 78% | Developer-heavy; intentionally cautious for current Jarvis |
| Home-scoped cleanup | 4/7 hard-blocked | 57% | Cwd equivalents pass; syntax-only difference remains |
| `find`/`xargs` idioms | 2/5 hard-blocked | 40% | Developer/build-cleanup heavy; left strict |
| `reboot`/`cron`/`at` | 5/7 hard-blocked | 71% | Admin-heavy; left strict |
| Log grep with keywords | 4/5 hard-blocked | 80% | Known keyword false-positive surface |
| macOS keychain | 1/3 hard-blocked | 33% | Secret extraction remains strict |
| Scoped chmod | 1/4 hard-blocked | 25% | Recursive 777 remains strict |
| Docker/container | 1/4 hard-blocked | 25% | Container/dev-heavy; left strict |

## The structural pattern

Most CATASTROPHIC false-positives above share one shape:

**a regex matching a _syntactic shape_ (word, flag, pipe target, path prefix) that your policy layer would otherwise evaluate correctly.**

The pipeline you built has:
- `deterministic_guardian` that knows read-only vs write
- `code_inspector` that reads Python bodies for real danger
- `capability` tagging that separates `network_probe` from `download_and_exec`
- `terminal_constraints` at the policy layer that users can tune

For true CATASTROPHIC matches, step 3 of the pipeline still
short-circuits before the nuanced layers run. `RCE-003` is now the
exception: it remains visible as a named pattern signal but no longer
short-circuits to hard block.

The non-negotiables (`rm -rf /`, `mkfs /dev/disk1`, `dd of=/dev/`,
`chmod 777 /`, `:(){ :|:& };:`, kernel-ext loading, SIP disable, TCC
db edits, NVRAM writes, bless, dscl user-create) are genuinely
irreversible and deserve catastrophic status. Most remaining blockers
are developer- or admin-heavy and are intentionally cautious for the
current general-purpose Jarvis release. The narrow change made now is
only `RCE-003`: LLM-native `curl | python` data plumbing routes to
review instead of hard block.