# IntentFrame-Side Command Shield Wiring

> `command_shield` emits rich capability, edge, and code-intel signals. This TODO captured the four sequential gaps that had to close for the consumer side to convert those signals into real LLM-cost reductions and stronger deterministic security.
>
> **Status (post-commit `a9866cc` "update new command shield and deterministic gate in intentframe" + `b7e146e` "update new composition capability" + `e705d57` "refactor pipeline prompt strategy and routing"): all four gaps are CLOSED.** The detailed sections below are preserved as the design record; the "Shipped" summary immediately after this paragraph captures the current state.

---

## Shipped (summary)

| Gap | Shipped in | What landed |
|---|---|---|
| 0   | command_shield v2 | `capability:read_only:*` (10 single-head sub-tags + `composition` aggregate) and `capability:filesystem_write` emitted under strict structural gates, with trusted-path head normalisation. |
| 0.5 | command_shield v2 | `capability:network_probe:*` family (9 sub-tags) emitted under the same structural-bareness predicate as `read_only:*`. |
| 0.6 | command_shield v2 | `capability:read_only:composition` and trusted-path head normalisation — transparent to consumers via prefix match. |
| 1   | pipeline.py | `report.signals` is now forwarded to AE for all non-catastrophic verdicts (not just `NEEDS_REVIEW`). |
| 2   | policy_registry/constraints/terminal.py | `TerminalConstraints` gained `allow_capabilities` and `deny_capabilities`; policy matching supports prefix wildcards on the `:` boundary. |
| 3   | guardian/checkers/terminal.py | `TerminalChecker` evaluates `deny_capabilities` / `allow_capabilities` against `report.capabilities` via a side-channel `CommandIntel` (Option B ended up cleaner in practice than Option A). |
| 4   | guardian/deterministic.py + pipeline.py | `DeterministicGuardian` runs as a pre-AE pass; emits BLOCK / ALLOW / UNDECIDED; ALLOW short-circuit keyed off `capability:read_only:*` with the full disqualifier set (filesystem_write, stdin_exec, network_bind, background_exec, download_and_exec, process_signal, spawns_process, any `network_probe:*`, any deny-capability hit, any `edge:*` signal, any `code_intel` finding). Both `DeterministicGuardian.BLOCK` and `ALLOW` completely skip AE + AI Guardian. |
| 5   | prompt/strategy.py + prompt/library/ + engines | `RUN_COMMAND` AI-path traffic is routed to specialised AE lanes keyed on `capability:network_probe:*` sub-tags (`critical_network_probe` for `{icmp, trace, dns, whois, http_get}`, `critical_network_mutation` for `{http_mutate, http_download, port_scan, file_transfer}`, `critical_generic` otherwise). Guardian similarly routes to a `critical` lane for any action in `CRITICAL_ACTIONS`. Lane **bodies** are neutralised in the initial rollout (overlay content = `""`; see `TODO/AE_Guardian_specialisation_routes.md` — "What shipped"); lane **routing, audit recording, and fail-closed fallback** are live. |

See `intentframe_server/pipeline.py` (`_process_intent_impl`) for the end-to-end sequence and `intentframe_components/guardian/deterministic.py` for the fast-path short-circuit rule in code form. `tests/test_pipeline_shield.py`, `tests/test_deterministic_guardian.py`, `tests/test_prompt_strategy.py`, and `tests/test_audit_prompt_id_reset.py` pin the behaviour.

---

## Original context (preserved as the design record)

---

## Background

`command_shield` is complete. It runs a 12-step pipeline and produces:

- `report.verdict` — `SAFE` / `NEEDS_REVIEW` / `CATASTROPHIC` (pattern-driven only)
- `report.signals` — all signals including `capability:*`, `edge:*`, `resolved:*`, structural findings
- `report.capabilities` — typed capability tuple (`capability:package_install:pip`, `capability:script_execution:python`, `capability:network_bind`, `capability:read_only:*`, `capability:filesystem_write`, etc.)
- `report.code_intel` — deterministic AST / shell-regex findings (dangerous imports, eval calls, etc.)

**Update (read-only fast-path tags — v2):** the classifier now emits a
`capability:read_only:*` family covering ten single-head sub-tags
plus one aggregate `composition` sub-tag:

- `filesystem_list` — `ls` / `tree` / `stat` / `file` / `du` / `df` /
  `lsattr` / `getfacl` / `namei` / `pathchk` / `findmnt` /
  `mountpoint` / `lsblk` / `blkid` / `find` (safe flags)
- `filesystem_read` — `cat` / `head` / `tail` / `less` / `more` / `wc`
  / `hexdump` / `xxd` / `od` / `nl` / `tac` / `rev` / `md5sum` /
  `sha*sum` / `b2sum` / `shasum` / `cksum` / `sum`
- `search` — `grep` / `egrep` / `fgrep` / `rg` / `ack` / `jq` / `yq` /
  `xmllint` (no `--output`)
- `process_inspect` — `ps` / `top` / `htop` / `lsof` / `pgrep` /
  `pidof` / `uptime` / `w` / `jobs` / `free` / `vmstat` / `iostat` /
  `mpstat` / `ipcs` / `nproc` / `arch` / `last` / `who` / `users` /
  `getent` / `cal` / `ncal`
- `system_info` — `uname` / `whoami` / `id` / `hostname` / `date` /
  `pwd` / `env` / `which` / `man` / `info` / `apropos` / `tput` /
  `alias` / `clear` / `reset` / `seq` / `factor` / `printf` /
  `sysctl` (no `-w` / `-p` / `--load`) / `ulimit` (no value) /
  `stty` (bare / `-a` / `-g`)
- `vcs_inspect` — `git` / `hg` / `svn` / `fossil` / `bzr` read-only
  sub-commands
- `text_transform` — `sort` / `sdiff` (no `-o`), `uniq` (≤ 1
  positional), `cut` / `paste` / `join` / `tr` / `column` / `fold` /
  `fmt` / `pr` / `expand` / `unexpand` / `comm` / `diff` / `diff3` /
  `cmp` / `colordiff` / `delta`
- `network_inspect` — `netstat` / `ss` / `arp` (no `-s` / `-d`) /
  `ip <obj> show|list|get` / `route` (no `add` / `del` / `flush`) /
  `ifconfig` (inspect-only forms). `ping` / `traceroute` / `dig` /
  `curl` / `wget` are NOT included — they emit outbound traffic and
  belong to a separate `network_probe` family if/when desired.
- `archive_inspect` — `tar -t*f` / `--list` (excludes any
  `c` / `x` / `r` / `A` / `u` mode letters), `unzip -l|-v|-Z|-t|-p|-c`,
  `zipinfo`, `gzip|bzip2|xz|zstd` with `-l` / `-t`, streaming
  decompressors (`zcat` / `bzcat` / `xzcat` / `zstdcat` / `zless` /
  `zmore` / `zgrep` family)
- `container_inspect` — `docker` / `podman` (`ps` / `images` /
  `logs` / `inspect` / `info` / `version` / `history` / `port` /
  `diff` / `top` / `stats` / `events` / `network ls` / `volume ls`) /
  `kubectl` (`get` / `describe` / `logs` / `top` / `version` /
  `api-resources` / `explain` / `config view` / `cluster-info` /
  `auth can-i`)
- `composition` — aggregate tag emitted when the command is a
  multi-segment composition joined only by `|` / `||` / `&&` / `;` /
  `|&`, every segment is independently either a safe literal `cd` or
  a read-only head from the sub-tags above, no segment emits an
  incompatible capability (write, stdin-exec, spawns-process,
  download-and-exec, network-bind, background-exec, package-install,
  script-execution), and no dynamic content / interpreter indirection
  is present.  Covers real-world LLM patterns like `ls -la | head`,
  `cd /tmp && ls`, `ps aux | grep nginx`, `git log --oneline | head`,
  `cat file | wc -l`.  Specific-family sub-tags are NOT emitted for
  compositions — the aggregate tag is load-bearing.

It also emits `capability:filesystem_write` for shell-redirect / `tee`
writes.  Single-head read-only tags fire only for a structurally bare
single-head invocation; the `composition` sub-tag fires only under the
strict per-segment gate above — see `command_shield/README.md` for the
full rules.  Both shapes additionally apply **trusted-path head
normalisation** before the regex match: an absolute path whose parent
is in `{/bin, /usr/bin, /sbin, /usr/sbin, /usr/local/bin,
/usr/local/sbin, /opt/homebrew/{bin,sbin}, /opt/local/{bin,sbin}}` is
rewritten to its basename (`/bin/ls -la` is matched as `ls -la`,
`/opt/homebrew/bin/rg foo src/` as `rg foo src/`, etc.).  Paths
outside the allow-list (`/tmp/ls`, `./ls`, `~/bin/ls`) stay strict to
avoid spoofing.  These are the signals Gap 4's ALLOW short-circuit
should key off for `RUN_COMMAND` traffic.

**Consumer matching rule:** any tag starting with
`capability:read_only:` qualifies for the fast-path — the consumer
does NOT need to enumerate individual sub-tags, so adding new
sub-tags in `command_shield` later is transparent to the consumer.
In particular the new `capability:read_only:composition` tag and the
trusted-path head normalisation are picked up automatically by any
consumer that uses the prefix-match rule: the deterministic Guardian
on `intentframe_components/guardian/deterministic.py` already does,
so pipelines like `ls -la | head` and `cd /tmp && ls` now land on the
RUN_COMMAND fast-path with no consumer-side code changes.

**Update (network-probe family):** the classifier also emits a
sibling positive-fact family `capability:network_probe:*` with nine
sub-tags:

- `icmp` — `ping` / `ping6`
- `trace` — `traceroute` / `traceroute6` / `tracepath` / `tracepath6` / `mtr`
- `dns` — `dig` / `nslookup` / `host` / `drill` / `kdig`
- `whois` — `whois`
- `http_get` — `curl` / `xh` / `http`(ie) / `https`(ie) / `wget -O -` in idempotent form (no body, no `-o` / `-O`)
- `http_mutate` — same tools with `-X POST` / `--request PUT` / `-d` / `--data` / `-F` / `--form` / `-T` / `--upload-file` / `--post-data` / `--method=POST` / HTTPie body tokens (`name=value`, `:=`, `=@`)
- `http_download` — `curl -o` / `-O` / `--output` / `--remote-name`; `wget` default (non-`-O -`) mode (response persisted to disk)
- `port_scan` — `nmap` / `masscan` / `zmap` / `nc` / `ncat` / `netcat` in connect mode (listen-mode — `-l`, `-lk`, `--listen` — stays in `capability:network_bind`)
- `file_transfer` — `scp` / `sftp` / `rsync` with a `[user@]host:` endpoint / `rclone` (`copy` / `sync` / `move` / `mount` / `serve` / `ls` / `cat` / …)

`network_probe:*` fires under the **same** structural-bareness
predicate as `read_only:*` (one sub-command, no indirection, no
dynamic content, no composition).  Unlike `read_only:*`, however,
**it is NOT a fast-path license.**  Every tag signals outbound
network traffic, which is policy-relevant regardless of tool.
Consumers should route these to a specialised AE lane or apply a
domain-allowlist policy — command_shield itself takes no position.

The Gap 4 ALLOW short-circuit below therefore includes a defensive
`not any(c.startswith("capability:network_probe:"))` clause; the
structural gate already keeps `read_only:*` and `network_probe:*`
mutually exclusive on the same command, and this belt-and-braces
check guards against a future family interaction silently licensing
a network-emitting command.

`capability:network_probe:http_download` does NOT imply
`capability:filesystem_write` — the latter is reserved for shell
redirects and `tee`.  Consumers that care about "does this command
write a file?" should check both tags independently.

Today the pipeline only acts on two of those:

```python
# pipeline.py — current state
if report.verdict == Verdict.CATASTROPHIC:
    return BLOCK                          # gate 1: works
if report.verdict == Verdict.NEEDS_REVIEW:
    terminal_command_signals = report.signals   # gate 2: partial
# SAFE verdict → capabilities, edges, code_intel all silently discarded
# AE is ALWAYS called regardless of verdict or signals
```

That means:
- `pip install requests` → `capability:package_install:pip` emitted → **discarded** → AE called anyway
- `nc -l 8080` → `capability:network_bind` emitted → **discarded** → AE called anyway
- 80–90% LLM-cost reduction projected → **not yet happening**

---

## The Four Gaps

### Gap 1 — Always forward signals, not only on `NEEDS_REVIEW`

**File:** `intentframe_server/pipeline.py`

**Problem:** `terminal_command_signals` is set only when `verdict == NEEDS_REVIEW`. SAFE commands with meaningful capability tags produce zero signal context for AE. This also means Guardian's AI path evaluates `pip install requests` without knowing the shield already classified it as `package_install:pip`.

**Fix:** Forward `report.signals` always. Optionally also expose `report.capabilities` as a separate field passed to AE and Guardian for structured consumption.

**What to change:**
- Remove the `if report.verdict == Verdict.NEEDS_REVIEW:` guard around `terminal_command_signals = report.signals`
- Forward signals for all non-catastrophic verdicts so AE always has structured context

---

### Gap 2 — Add capability fields to `TerminalConstraints`

**File:** `policy_registry/constraints/terminal.py`

**Problem:** `TerminalConstraints` only has `blocked_patterns` (substring) and `allowed_commands` (glob). There is no way for policy to express "allow `capability:package_install:pip` but deny `capability:package_install:apt`" or "deny `capability:network_bind` outright."

**Current schema:**
```python
class TerminalConstraints(BaseModel):
    blocked_patterns: list[str] = []
    allowed_commands: list[str] = []
    # ← no capability fields
```

**Fix:** Add two optional sets:
```python
class TerminalConstraints(BaseModel):
    blocked_patterns: list[str] = []
    allowed_commands: list[str] = []
    allow_capabilities: set[str] = set()   # e.g. {"capability:package_install:pip", "capability:script_execution:python"}
    deny_capabilities: set[str] = set()    # e.g. {"capability:network_bind", "capability:background_exec"}
```

Policy matching should support prefix wildcards on the `:` boundary (e.g. `capability:package_install:*` denies all package managers, not just one).

---

### Gap 3 — Teach `TerminalChecker` to consume capability signals

**File:** `intentframe_components/guardian/checkers/terminal.py`

**Problem:** `TerminalChecker.check()` only sees `IntentFrame` and `TerminalConstraints`. It has no access to the `CommandReport` produced by command_shield, so even after Gap 2 adds the fields, the checker cannot evaluate them.

**Current logic:**
```python
def check(self, intent, constraints):
    command = intent.target or ...
    for pattern in constraints.blocked_patterns:
        if pattern in command:
            return False, ...
    if constraints.allowed_commands:
        ...  # glob match
    return True, ""
    # ← never reads report.capabilities
```

**Fix options:**
- **Option A:** Pass the `CommandReport` as an optional third argument to `check(intent, constraints, report=None)` and evaluate `deny_capabilities` / `allow_capabilities` against `report.capabilities` when present.
- **Option B:** Resolve the capabilities in `pipeline.py` before calling Guardian and embed them into the intent or a side-channel context object.

Option A is cleaner — it extends the checker contract minimally and keeps the evaluation logic inside `TerminalChecker`.

**Evaluation order inside the checker (proposed):**
1. `blocked_patterns` — substring match on raw command (existing, unchanged)
2. `deny_capabilities` — if any capability in `report.capabilities` is in the deny set → BLOCK
3. `allow_capabilities` — if non-empty and no capability in `report.capabilities` matches the allow set → BLOCK
4. `allowed_commands` — glob match on raw command (existing, unchanged, runs last)

Deny always wins over allow at each level.

---

### Gap 4 — Extract deterministic Guardian into a pre-AE pass

**Files:** `intentframe_server/pipeline.py`, `intentframe_components/guardian/engine.py`

**Problem:** Guardian's deterministic steps (permission check, constraint check, domain module check) currently live inside `AIGuardian.validate()` and run only **after** `analysis_engine.analyze()` has already paid its LLM cost. This means:

- Every `RUN_COMMAND` blocked by a `blocked_patterns` entry still triggers an AE call first
- Every `READ_FILE` to a disallowed path still triggers an AE call first
- Every action not in `allowed_actions` still triggers an AE call first
- Passive reads (20+ action types) already have an AE-internal fast-path, but AE is still invoked

**Proposed pipeline reorder:**
```
command_shield (CATASTROPHIC gate, as today)
    ↓
DeterministicGuardian.decide(intent, user_context, report?)
    → BLOCK  → return immediately, no AE
    → ALLOW  → execute directly, no AE (passive reads, policy-safe + clean signals)
    → UNDECIDED → proceed to AE + AI Guardian
    ↓ (UNDECIDED only)
Analysis Engine (LLM)
    ↓
AI Guardian (LLM)
    ↓
Executor
```

**What `DeterministicGuardian.decide()` runs (in order):**
1. Permission check — action in `allowed_actions`? → BLOCK if not
2. Constraint check — per-category checkers (file path, terminal patterns + capabilities, email recipient, etc.) → BLOCK if violated
3. Domain module check — finance hard gate, deletion hard gate → BLOCK if violated
4. Passive-read short-circuit — if action in `_PASSIVE_READ_ACTIONS` and no risk signals → ALLOW
5. RUN_COMMAND read-only short-circuit — if `report.verdict == SAFE`
   AND any `capability:read_only:*` is present
   AND none of `{capability:filesystem_write, capability:stdin_exec, capability:network_bind, capability:background_exec, capability:download_and_exec, capability:process_signal, capability:spawns_process}` are present
   AND no `capability:network_probe:*` tag is present (defensive — the
       structural gate already prevents co-occurrence)
   AND none of `deny_capabilities` (Gap 2) are present
   AND no `edge:*` signal is present
   AND `report.code_intel` has no findings
   → ALLOW (skip AE)
6. Policy-safe short-circuit — if `permission.safe` AND no capability signals in the deny set AND no structural signals → ALLOW
7. Otherwise → UNDECIDED (AE + AI Guardian handle it)

Step 5 is the direct consumer of the new `capability:read_only:*`
family.  Because `command_shield` emits those tags only after a strict
structural gate (single sub-command, no indirection, no composition,
no write redirects, no incompatible capability already emitted), the
consumer side can trust the combination above without repeating any
parsing.  The equivalent rule as a code skeleton:

```python
_READ_ONLY_INCOMPATIBLE = {
    "capability:filesystem_write",
    "capability:stdin_exec",
    "capability:network_bind",
    "capability:background_exec",
    "capability:download_and_exec",
    "capability:process_signal",
    "capability:spawns_process",
}

def _is_read_only_fast_path(report, deny_caps):
    if report.verdict is not Verdict.SAFE:
        return False
    caps = set(report.capabilities)
    if not any(c.startswith("capability:read_only:") for c in caps):
        return False
    if caps & _READ_ONLY_INCOMPATIBLE:
        return False
    # Defensive: never fast-path a command that emits outbound traffic,
    # even if it somehow also picked up a read_only:* tag.  The
    # structural gate already keeps these families disjoint.
    if any(c.startswith("capability:network_probe:") for c in caps):
        return False
    if deny_caps and caps & deny_caps:
        return False
    if any(s.signal_id.startswith("edge:") for s in report.signals):
        return False
    if report.code_intel and report.code_intel.findings:
        return False
    return True
```

**Implementation note:** Steps 1–3 already exist as code inside `AIGuardian.validate()` (lines 275–318 of `engine.py`). This is primarily a **lift-and-rearrange**, not new logic. The main addition is the ALLOW fast-path at steps 4–5.

**Expected impact once all four gaps are closed:**

| Traffic class | Today | After |
|---|---|---|
| Passive reads (ls, pwd, cat, git status, …) | AE called (fast-path internal) | No AE, no Guardian AI (keyed on `capability:read_only:*`) |
| Passive reads via absolute path (`/bin/ls -la`, `/usr/bin/cat file`, `/opt/homebrew/bin/rg …`) | AE called | No AE, no Guardian AI — trusted-path head normalisation lands them on the same fast-path |
| Passive read compositions (`ls -la \| head`, `cd /tmp && ls`, `ps aux \| grep nginx`, `git log \| head -50`) | AE called | No AE, no Guardian AI — `capability:read_only:composition` lands on the same fast-path via prefix match |
| Package installs (pip install, npm install) if policy allows | AE called | No AE, no Guardian AI |
| Network bind / background exec if policy denies | AE called, then Guardian blocks | Blocked in deterministic pass, no AE |
| Any write redirect (`cmd > file`, `cmd \| tee`) | AE called | AE called (read-only fast-path refuses to fire because `capability:filesystem_write` is present) |
| Cheap network probes (ping, dig, whois, curl/wget read) if policy allows outbound | AE called | Routed to a dedicated AE lane with a specialised prompt that knows it's network-side-effecting (keyed on `capability:network_probe:{icmp,trace,dns,whois,http_get}`). Deterministic ALLOW still possible if policy allows the specific family for the destination. |
| HTTP mutate / download / port_scan / file_transfer | AE called | Always goes to the specialised AE network-probe lane — never to the read-only fast-path (keyed on `capability:network_probe:{http_mutate,http_download,port_scan,file_transfer}`) |
| Novel commands, obfuscated, unknown tools | AE called | AE called (unchanged) |
| Content-bearing outbound (email body, ASK_USER) | AE called | AE called (unchanged) |

Rough aggregate: **70–85% of total intent traffic** avoids an AE LLM call. For `RUN_COMMAND` specifically, **80–90% avoidance** once capability constraints are in policy.

---

## Suggested Implementation Order (historical)

| Step | Change | Risk | Status |
|---|---|---|---|
| 0 | Add `capability:read_only:*` + `capability:filesystem_write` tags to `command_shield.classifier` | — | **Done** |
| 0.5 | Add `capability:network_probe:*` family to `command_shield.classifier` (9 sub-tags, same structural gate as read_only) | — | **Done** |
| 0.6 | Add `capability:read_only:composition` + trusted-path head normalisation to `command_shield.classifier` | — | **Done** |
| 1 | Always forward `report.signals` to AE (Gap 1) | Low — AE already handles extra signals gracefully | **Done** |
| 2 | Add `allow_capabilities`/`deny_capabilities` to `TerminalConstraints` (Gap 2) | Low — additive fields, existing policy unaffected | **Done** |
| 3 | Extend `TerminalChecker` to evaluate capabilities (Gap 3) | Low — pure addition to checker logic | **Done** |
| 4 | Wire capability deny-check to per-agent policy (e.g. Jarvis) for immediate wins | Low — just populate the new fields in user policy | **Done** (policy files shipped) |
| 5 | Extract and run deterministic Guardian pre-pass before AE (Gap 4) — includes the read-only ALLOW short-circuit above | Medium — pipeline reorder, needs careful testing of UNDECIDED boundary | **Done** |
| 6 | Author per-lane bodies for `critical_network_probe` / `critical_network_mutation` sub-lanes | Medium — prompt edits need red-team coverage | **Plumbing done** (commit `e705d57`); `critical_run_command` and `critical_write_file` full-body forks shipped; probe / mutation aliased to `critical_run_command` pending per-lane forks — see `TODO/AE_Guardian_specialisation_routes.md` |

All structural work is shipped. The remaining content work is authoring full-body forks for `critical_network_probe` and `critical_network_mutation` — a pure library-file edit in `intentframe_components/prompt/library/analysis.py` and deletion of the aliasing assertions in `tests/test_prompt_library.py::TestInitialRolloutAliasing`.

---

## What Does NOT Need to Change

- `command_shield` itself — complete and stable
- AE's prompt format — it already handles `terminal_command_signals` gracefully; richer signals are additive
- AI Guardian's validation logic — it already runs deterministic steps first internally; those just move earlier
- All other constraint checkers (FileChecker, EmailChecker, BrowserChecker, etc.) — unchanged; they plug into the deterministic pass as-is
- `quick_check` in the executor adapter — unchanged; last-resort floor stays where it is

---

## Related TODOs

- `AE_Guardian_specialisation_routes.md` — separate AE/Guardian instances per action criticality; complements this work (the pre-AE deterministic pass is the first step toward that routing)
- `jarvis-write-file-policy-and-python-env.md` — uses `inspect_code` for WRITE_FILE payload inspection; same signal vocabulary as here
