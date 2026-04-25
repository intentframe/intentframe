# `command_shield`

Deterministic inspection for shell commands **and** raw code bodies.

`command_shield` takes a command string (or a standalone code body) and returns a structured, immutable report describing:

- whether the input is immediately catastrophic,
- whether fixed-system patterns suggest it needs review,
- what deterministic capabilities it exposes,
- what language / interpreter shape it appears to use,
- which file paths or inline bodies it would actually execute, and
- what static-analysis findings exist in any reachable code.

It is designed for **focused inspection**, not whole-repository understanding:

- inspect a raw terminal command before execution,
- inspect inline interpreter payloads like `python -c ...`,
- inspect a literal referenced local script when the caller explicitly opts into safe file resolution,
- inspect a raw code blob you already have in memory via `inspect_code(...)`.

It is intentionally a **fact producer**, not a policy engine:

- `command_shield` decides only the 3-way verdict (`CATASTROPHIC`, `NEEDS_REVIEW`, `SAFE`) from fixed-system checks.
- It does **not** allow or deny commands based on user policy.
- It does **not** know about Guardian, AE, runtime context, session state, or root.
- Consumers decide what to do with the emitted facts.

That means `command_shield` is useful for investigating **a command, a resolved script, or an already-loaded code body**.  It is not a repo crawler, dependency graph engine, or semantic codebase explorer.

### Literal inspection, not semantic understanding

`command_shield` exists to answer narrow mechanical questions about a
command string:

- which fixed dangerous primitives literally appear,
- how the shell would structurally decompose the command,
- whether the command contains interpreter indirection or hidden
  payloads,
- what deterministic capability tags the command exposes,
- whether any referenced or inline code body contains static-analysis
  findings.

It does **not** try to answer semantic questions such as:

- "is this command merely quoting documentation text?",
- "is the user explaining a command rather than invoking it?",
- "does the current task justify this action?",
- "what does this command mean in the broader business context?",
- "should this user be allowed to do this right now?"

Those questions belong to the higher layers in IntentFrame:

- `command_shield` performs literal / syntactic / structural inspection,
- the Analysis Engine interprets intent and context,
- Guardian applies policy and authorization,
- the executor only runs what survives the earlier gates.

That division is intentional.  The root-profile demo is specifically
about showing that even when the executor is highly privileged,
IntentFrame's deterministic gate still refuses known catastrophic
primitives *before* semantic reasoning or execution happens.

## Why It Exists

Arbitrary shell commands are the one action class that can hide a lot of behavior inside a single string:

- destructive shell primitives,
- interpreter indirection like `python -c ...`,
- chained / nested subcommands,
- package installs, compilation, listeners, background jobs,
- inline Python or shell code,
- code that touches system paths or spawns processes,
- references to scripts that live on disk.

If every caller had to rediscover those mechanics itself, every downstream policy or AI layer would spend time re-parsing command strings instead of reasoning about user intent and authorization.

`command_shield` centralizes that mechanical inspection into one standalone module with a small, stable contract:

- **cheap checks run first,**
- **deterministic facts are produced once,**
- **verdict semantics stay stable,**
- **higher layers consume a trusted report instead of raw shell trivia.**

## Mental Model: Commands as a Graph of Code Units

A shell command is the *root* of a graph.  The command itself is one code unit (a shell body), and it links — via **containment edges** — to inner code units that the shell may cause to execute:

    inline       python -c "import os; os.system('rm -rf /')"
    referenced   python foo.py                        # literal path
    piped_stdin  cat foo.py | python -
    dynamic      python $SCRIPT  /  python <(curl ...)
    interactive  bash                                 # REPL, no body
    compiled     ./a.out                              # no source available

`command_shield` walks that graph: cheap → expensive checks on the root, extracts the edges, and — when the caller opts in — resolves local referenced scripts and runs the code inspector on each reachable body.  Every edge and every resolver result turns into a structured signal.

## What It Does

### Core verdict

Every inspection returns a `CommandReport` with:

- `verdict`: one of `Verdict.CATASTROPHIC`, `Verdict.NEEDS_REVIEW`, `Verdict.SAFE`
- `signals`: structured `Signal` objects
- `command` and `normalized_command`
- `sub_commands` discovered during structural decomposition

The verdict is intentionally narrow:

- `CATASTROPHIC` means known fixed-system catastrophic patterns were found.
- `NEEDS_REVIEW` means fixed-system non-catastrophic review-worthy signals were found.
- `SAFE` means no fixed-system review-worthy patterns were found.

Config-driven findings like `COMMAND_TOO_LARGE`, `OUT_OF_SCOPE`, `CODE_TOO_LARGE`, `capability:*`, `edge:*`, and `resolved:*` **do not change the verdict**.  They are advisory facts for consumers.

### Extended report fields

As later steps run, `CommandReport` may also include:

- `language`: `LanguageInfo` — detected interpreter / inline-vs-file shape
- `capabilities`: tuple of capability tags
- `code_intel`: `CodeIntel` — mirrors the most informative resolved node
- `reviewer_findings`, `reviewer_summary`, `reviewer_ran` (deep async path only)
- `edges`: tuple of `Edge` — containment edges discovered in the command
- `resolved_nodes`: tuple of `ResolvedNode` — per-edge inspection result
- `script_path_candidate`: first literal referenced path, if any
- `script_resolved`: True when that path was actually read and inspected
- `elapsed_ms`

These fields default cleanly, so callers that only read `verdict` and `signals` keep working unchanged.

## How It Works

All full command inspection flows through a single ordered pipeline in `command_shield.pipeline`:

1.  `max_command_length` check
2.  normalize + tokenize
3.  fixed-system pattern match (verdict-bearing)
4.  structural decomposition + indirection re-check (verdict-bearing)
5.  language / role detection
6.  scope check against `allowed_languages`
7.  capability classification
8.  containment-edge extraction
9.  edge walk → per-node `inspect_code`
10. optional LLM reviewer (async path only)
11. assemble `CommandReport`

The ordering is deliberate: cheapest and most certain checks run first; expensive checks only run when earlier gates allow them to; I/O (reading a referenced script) happens only when the caller opts in.

### 1. Pattern and structural analysis

The first decisive layer is pattern + structure:

- commands are normalized,
- known catastrophic and review-worthy patterns are matched,
- shell structure is decomposed into subcommands,
- interpreter indirections / payloads are re-scanned.

This is where the verdict comes from.

#### Pattern pack layout

The regex pack lives at `command_shield/patterns/*.json` and is loaded at import time.  Every entry has `{id, regex, verdict, description, source, category}`.  The packs are organized by what they catch, not where they came from:

- `catastrophic.json` — cross-platform catastrophic primitives: `sudo`, destructive `rm` against home / `/`, fork bombs, `chmod 777` on system roots, disk-write primitives (`dd of=/dev/…`, `mkfs`, `wipefs`, `shred`), destructive `git` (force-push, `reset --hard`, `stash clear`), shell-wrapper evasions (`bash -c '…rm -rf…'`, `find -exec rm`, `xargs rm`, …), **non-sudo privilege escalation verbs** (`pkexec`, `doas`, `runuser`, `machinectl shell|login`), and **direct `sandbox-exec` invocation** (which would bypass the executor-managed sandbox).
- `macos.json` — macOS-specific primitives: `diskutil erase*`, keychain dump / password extraction, Time Machine deletion, directory-services account / group mutation (`dscl . -create|passwd|change|merge|append /Users|Groups/…`), Gatekeeper / SIP / boot-arg tampering (`spctl --master-disable`, `csrutil disable|enable|clear`, `nvram` writes, `bless -…`), kernel-extension loading (`kextload`, `kextunload`, `kmutil load|unload|install|…`), TCC database access, and **AppleScript privilege escalation** (`…with administrator privileges`, case-insensitive).
- `persistence.json` — launchd / cron / at persistence: `launchctl load|unload` of specific system paths, the broader modern launchd verbs (`launchctl bootstrap|bootout|kickstart|enable|disable|submit|remove`), plist moves into `/Library/Launch*`, `crontab -e`, `crontab -` (stdin replace), `at now|<digit>|-f …`, `systemctl stop|disable|mask` of critical services, bash-history clearing.
- `credential_access.json` — reads / exfil of `~/.ssh/`, `~/.aws/`, `~/.kube/`, `~/.gnupg/`, `.env`, `~/.git-credentials`, etc.
- `exfiltration.json` — `curl … | sh`, base64-piped exec, reverse shells, `ssh host 'rm -rf /'`, etc.

Every pattern either produces a `CATASTROPHIC` or a `NEEDS_REVIEW` verdict; `SAFE` is the default when nothing matches.  Patterns never look at user policy, privilege level, or session state — they encode fixed-system facts only.

#### Why these families exist (root-demo relevance)

When the executor runs as root (the Jarvis root-profile demo), the kernel-level sandbox floor is intentionally minimal so the demo can showcase `RUN_COMMAND` with broad capability.  `command_shield` is the deterministic pre-gate that holds the line *regardless* of executor privilege.  The privilege-escalation pack in `catastrophic.json` (pkexec, doas, runuser, machinectl shell, sandbox-exec) and the macOS system-security pack in `macos.json` (SIP toggle, NVRAM writes, kext load/unload, `bless`, AppleScript admin prompt, dscl account control) exist specifically so that an agent with maximum executor privilege still cannot reach for a new security domain, a firmware / boot-path mutation, or a persistent local-account backdoor.  They have zero effect on benign legitimate commands — each regex targets a narrow, well-known system primitive.

#### Known false-positive surface

The packs intentionally match **the literal verb or phrase anywhere in the command string**.  `\b…\b` word-boundary anchors prevent substring collisions (`pkexec` inside `my_pkexec_log`) but they do **not** distinguish "the command `pkexec`" from "the word `pkexec` quoted inside an `echo` / `git commit -m` / heredoc / docstring".  So the following are classified `CATASTROPHIC` today even though they execute nothing privileged:

```
echo "use sudo or pkexec for privilege escalation"
git commit -m 'migrate away from doas'
echo "do not invoke sandbox-exec directly"
git commit -m 'script runs with administrator privileges'
echo "use csrutil enable to re-enable SIP"
echo "run nvram -d VarName to delete a variable"
echo "use launchctl bootstrap for new daemons"
echo "run crontab -e to edit your schedule"
echo "lets meet at 3pm today"            # IF-AT-SCHEDULE-001
echo "pointing at now"                   # IF-AT-SCHEDULE-001
```

Every such case is pinned as an `xfail` in
`command_shield/tests/test_patterns.py::TestKnownFalsePositives`
with a reason that names the responsible pattern ID, so the surface
is discoverable in code rather than folklore.  If someone later
tightens a pattern, the xfail flips to XPASS and nudges them to
remove the marker and make the negative real.

This is the clearest consequence of the boundary above: `command_shield`
is intentionally matching **literal command text**, not trying to infer
whether the surrounding prose is documentation, explanation, or benign
quotation.  In IntentFrame terms, that semantic disambiguation belongs
upstream in the AI layers, not in the deterministic regex gate.

**Why we leave these as-is for now.**

1. **Consistency with the existing pack.** The older `rm`-family
   patterns (`DEL-001`…`DEL-007`) carry narrow negative lookbehinds
   like `(?<!echo\s)(?<!echo ')(?<!echo \")` precisely because `rm`
   was the single highest-FP verb.  The remaining hardstop patterns
   (`sudo`, `reboot`, `mkfs`, `dd`, `chmod 777`, `diskutil eraseDisk`,
   `tccutil reset`, `launchctl load /Library/LaunchDaemons/…`, …) do
   **not** carry echo-guards either — an `echo "sudo reboot"` fires
   `IF-SUDO-001` today.  The new root-demo patterns follow the same
   convention so the pack stays uniform.
2. **CATASTROPHIC surfaces the block, doesn't hide it.**  A false
   positive returns a hard rejection with a named pattern ID that the
   caller sees.  A false *negative* on one of these verbs when the
   executor runs as root is the actual security failure.  The
   asymmetry favors over-blocking for the demo narrative.
3. **Echo-of-verb is already a weak signal.**  A plausibly benign
   command that quotes a privileged verb is uncommon in real agent
   usage; an attacker who wants to smuggle a privileged verb into a
   command string has easier paths (interpreter indirection, base64
   decoding, process substitution) that the pipeline's *structural*
   layer catches independently of these regexes.
4. **Downgrading would mask the demo point.**  Moving these to
   `NEEDS_REVIEW` would defer the decision to Guardian / AE on every
   hit, including the real attempts the demo is meant to block.  The
   point of the root-profile demo is that `command_shield` *alone*
   refuses these verbs, regardless of how generous the executor is.

**What could be done when the FP cost becomes real.**

Listed in increasing order of effort / risk:

1. **Echo-guard negative lookbehinds** on the highest-FP patterns.
   Mirror the existing `DEL-001` shape:
   `(?<!echo\s)(?<!echo ')(?<!echo \")<pattern>`.  Cheap, purely
   additive, flips the named xfail cases to PASS.  Does not handle
   `printf`, `git commit -m`, here-documents, or multi-token quoting.
2. **A shared `_prose_guard` prefix** compiled into every pattern
   whose category is `privilege_escalation` / `macos_system_security`
   / `scheduled_persistence` — same idea, one source of truth, easier
   to maintain than per-pattern lookbehinds.
3. **Structural mask of quoted regions** before regex matching.  The
   pipeline already runs `bashlex` for decomposition; a short pass
   could null out the interior of single- and double-quoted word
   tokens that are arguments to a small allowlist of heads (`echo`,
   `printf`, `git commit -m`, `cat <<EOF … EOF`).  Most surgical, but
   changes a shared preprocessing step that every pattern consumes.
4. **Downgrade prose-heavy patterns to `NEEDS_REVIEW`** and let the
   downstream Guardian / AE disambiguate invocation vs quoting.  Only
   worth it for patterns that are pure English phrases
   (`IF-OSASCRIPT-ADMIN-001` is the lone candidate today).  Costs an
   AI round-trip per hit.
5. **Two-pass: match → verify head.**  After a pattern hits, confirm
   the matched span starts a shell *simple command* head (via
   `bashlex`).  Most expensive, highest precision, biggest contract
   change — the module's current promise is "regex against a
   normalized string".

Anyone tightening a pattern should start at option 1, remove the
matching xfail(s), and leave the broader remediation for later.

### 2. Language detection

`command_shield` classifies the command shape using `LanguageInfo`:

- detected language (`python`, `shell`, `javascript`, `ruby`, ...),
- interpreter (`python3`, `bash`, `node`, ...),
- whether code is inline (`-c`, `-e`, `--eval`),
- whether the command appears to execute a file.

### 3. Capability classification

Step 7 emits deterministic capability tags describing what the command can do, not whether it is allowed.

Current capability families:

- package install:
  - `capability:package_install:pip`
  - `capability:package_install:npm`
  - `capability:package_install:brew`
  - `capability:package_install:apt`
  - `capability:package_install:yum`
  - `capability:package_install:dnf`
  - `capability:package_install:pacman`
  - `capability:package_install:apk`
  - `capability:package_install:gem`
  - `capability:package_install:cargo`
  - `capability:package_install:go`
  - `capability:package_install:composer`
- script execution:
  - `capability:script_execution:python`
  - `capability:script_execution:node`
  - `capability:script_execution:ruby`
  - `capability:script_execution:perl`
  - `capability:script_execution:shell`
  - `capability:script_execution:local_binary`
- read-only (positive family — emitted in two shapes: a bare
  single-head invocation gets a precise sub-tag; a composition of
  read-only sub-commands joined by `|` / `||` / `&&` / `;` / `|&`
  gets the aggregate `composition` sub-tag; see below):
  - `capability:read_only:filesystem_list`   (`ls`, `tree`, `stat`, `file`, `du`, `df`, `lsattr`, `getfacl`, `namei`, `pathchk`, `findmnt`, `mountpoint`, `lsblk`, `blkid`, `find` with safe flags)
  - `capability:read_only:filesystem_read`   (`cat`, `head`, `tail`, `less`, `more`, `wc`, `hexdump`, `xxd`, `od`, `nl`, `tac`, `rev`, `md5sum` / `sha*sum` / `b2sum` / `shasum` / `cksum` / `sum`)
  - `capability:read_only:search`            (`grep`, `egrep`, `fgrep`, `rg`, `ack`, `jq`, `yq`, `xmllint` excluding `--output`)
  - `capability:read_only:process_inspect`   (`ps`, `top`, `htop`, `lsof`, `pgrep`, `pidof`, `uptime`, `w`, `jobs`, `free`, `vmstat`, `iostat`, `mpstat`, `ipcs`, `nproc`, `arch`, `last`, `who`, `users`, `finger`, `getent`, `cal`, `ncal`)
  - `capability:read_only:system_info`       (`uname`, `whoami`, `id`, `hostname`, `date`, `pwd`, `env`, `which`, `man`, `info`, `apropos`, `whatis`, `tldr`, `tput`, `alias`, `clear`, `reset`, `seq`, `factor`, `printf`, `sysctl` without `-w` / `-p`, `ulimit` without a value, `stty` / `stty -a` / `stty -g`, …)
  - `capability:read_only:vcs_inspect`       (`git`, `hg`, `svn`, `fossil`, `bzr` — read-only sub-commands only; e.g. `git status` / `log` / `diff` / `show`, `hg status` / `log`, `svn info` / `log`, …)
  - `capability:read_only:text_transform`    (`sort` excluding `-o` / `--output`, `sdiff` excluding `-o`, `uniq` with at most one positional, `cut`, `paste`, `join`, `tr`, `column`, `fold`, `fmt`, `pr`, `expand`, `unexpand`, `comm`, `diff`, `diff3`, `cmp`, `colordiff`, `delta`)
  - `capability:read_only:network_inspect`   (`netstat`, `ss`, `arp` excluding `-s` / `-d`, `ip <obj> show|list|get`, `route` excluding `add` / `del` / `flush`, `ifconfig` in inspect-only form)
  - `capability:read_only:archive_inspect`   (`tar -tf` / `--list` (mode letters excluding `c`/`x`/`r`/`A`/`u`), `unzip -l|-v|-Z|-t|-p|-c`, `zipinfo`, `gzip|bzip2|xz|zstd` with `-l` / `-t`, streaming decompressors: `zcat`, `bzcat`, `xzcat`, `zstdcat`, `zless`, `zmore`, `zgrep` family)
  - `capability:read_only:container_inspect` (`docker` / `podman` `ps` / `images` / `logs` / `inspect` / `info` / `version` / `history` / `port` / `diff` / `top` / `stats` / `events` / `network ls` / `volume ls`, `kubectl` `get` / `describe` / `logs` / `top` / `version` / `api-resources` / `explain` / `config view` / `cluster-info` / `auth can-i`)
  - `capability:read_only:composition`       (aggregate tag for a
    multi-segment composition — `ls -la | head`, `cd /tmp && ls`,
    `ps aux | grep nginx`, `git log --oneline | head -50` — where
    every segment is independently either a safe `cd <literal>` or
    a read-only head from the sub-tags above.  The specific-family
    sub-tags are *not* emitted for compositions; a consumer that
    prefix-matches `capability:read_only:` picks `composition` up
    automatically.)
- network probe (positive family — emitted when the command is a
  structurally bare single-head invocation; **not** a fast-path license,
  see below):
  - `capability:network_probe:icmp`          (`ping`, `ping6`)
  - `capability:network_probe:trace`         (`traceroute`, `traceroute6`, `tracepath`, `tracepath6`, `mtr`)
  - `capability:network_probe:dns`           (`dig`, `nslookup`, `host`, `drill`, `kdig`)
  - `capability:network_probe:whois`         (`whois`)
  - `capability:network_probe:http_get`      (`curl` / `xh` without mutate / download flags, `wget -O -`, HTTPie `http` / `https` without body or POST/PUT/DELETE/PATCH verb)
  - `capability:network_probe:http_mutate`   (`curl` / `xh` / HTTPie / `wget` with `-X POST` / `--request PUT` / `-d` / `--data` / `-F` / `--form` / `-T` / `--upload-file` / `--post-data` / `--method=POST` / HTTPie body tokens `=@` / `:=`)
  - `capability:network_probe:http_download` (`curl -o` / `-O` / `--output` / `--remote-name`, `wget` in default (non-`-O -`) mode — response persisted to disk; does NOT imply `capability:filesystem_write` which is reserved for shell redirects / `tee`)
  - `capability:network_probe:port_scan`     (`nmap`, `masscan`, `zmap`, `nc` / `ncat` / `netcat` in connect mode — `-l` / `-k` listen forms stay under `network_bind`)
  - `capability:network_probe:file_transfer` (`scp`, `sftp`, `rsync` with a `[user@]host:` endpoint, `rclone` `copy` / `sync` / `move` / `mount` / `serve` / `ls` / `cat` / `md5sum` / `check` / etc.)
- `capability:compilation`
- `capability:filesystem_write`
- `capability:network_bind`
- `capability:background_exec`
- `capability:download_and_exec`
- `capability:binary_download`
- `capability:process_signal`
- `capability:spawns_process`
- `capability:stdin_exec`

Callers can match exact tags or prefixes like `capability:package_install:*`
or `capability:read_only:*`.

#### The read-only fast-path family

`capability:read_only:*` is a *positive* capability — it describes
what the command is, not just what it can do.  Unlike the other
capability rules (which run per-haystack `regex.search`), a read-only
tag is only emitted after a strict structural gate passes.  There are
two emission shapes — **single-head** (precise family sub-tag) and
**composition** (aggregate sub-tag).  Both share the same
incompatibility and dynamic-content rejections; they differ only in
how many segments the command has.

**Single-head shape.**  A precise family sub-tag
(`filesystem_list`, `filesystem_read`, `search`, …) is emitted only
when **all** of the following hold:

1. bashlex reports exactly one sub-command (no `|` / `;` / `&&` / `||`).
2. No interpreter indirection payload (`bash -c "..."`, `python -c ...`).
3. No dynamic structural signal (command substitution, process
   substitution, variable expansion, parse failure).
4. No bare shell-composition or redirect token when the normalized
   command is re-tokenised (`|`, `;`, `>`, `>>`, `&`, `<`, `<<`, …).
5. No incompatible capability already emitted on the same command —
   `stdin_exec`, `filesystem_write`, `spawns_process`, `network_bind`,
   `background_exec`, `download_and_exec`, `binary_download`,
   `process_signal`, `compilation`, `package_install:*`, `script_execution:*`.
6. The normalized command (with trusted-path head normalisation
   applied — see below) fully matches one of the per-family head
   regexes (which themselves exclude destructive flag modes like
   `find -delete` / `find -exec` / `sed -i`).

**Composition shape.**  When the command is a multi-segment
composition, the aggregate `capability:read_only:composition`
sub-tag is emitted iff **all** of the following hold:

1. bashlex reports at least two sub-commands joined only by
   `|` / `||` / `&&` / `;` / `|&`.  The re-tokenised command contains
   no redirect token, no trailing background `&`, and no case-fallthrough `;;`.
2. No interpreter indirection, no dynamic structural signal — same
   rejections as (2) and (3) for single-head.
3. No incompatible capability is emitted anywhere in the command.
   This is the broadest gate: a single segment that emits
   `filesystem_write` (redirect, `tee`), `spawns_process` (`xargs`,
   `sudo`, `ssh`, `docker run`), `stdin_exec` (`| sh`, `| python -`),
   `download_and_exec` (`curl … | sh`), `background_exec` (trailing
   `&`), `package_install:*`, or `script_execution:*` disqualifies
   the whole composition automatically.
4. Every sub-command is independently either (a) a safe literal `cd`
   — `cd`, `cd -`, or `cd <arg>` with no shell metacharacters in the
   arg — or (b) a head that matches one of the single-head read-only
   rules (with the same trusted-path normalisation applied per
   segment).  A narrow fallback accepts bare pipe-consumer heads
   (`head`, `cat`, `wc`, `grep`, hashers, …) with flag-only tokens —
   in a pipeline these tools read from stdin so the single-head
   regex's "≥1 positional" requirement is deliberately relaxed.

The composition tag does NOT emit any of the specific-family
sub-tags — those stay a single-head-only contract.  Consumers that
prefix-match `capability:read_only:` get composition for free;
consumers that enumerate specific sub-tags stay unaffected.

**Trusted-path head normalisation.**  Both shapes apply the same
head rewrite before the regex match: when the head is an absolute
path whose parent directory lives in

    /bin, /usr/bin, /sbin, /usr/sbin,
    /usr/local/bin, /usr/local/sbin,
    /opt/homebrew/bin, /opt/homebrew/sbin,
    /opt/local/bin, /opt/local/sbin

the head is rewritten to its basename.  `/bin/ls -la` is matched as
`ls -la`, `/opt/homebrew/bin/rg foo src/` as `rg foo src/`, etc.  Any
other absolute or relative path (e.g. `/tmp/ls`, `./ls`, `~/bin/ls`,
`/usr/bin/subdir/ls`) is left strict — spoofing is credible in
user-writable locations, so the classifier deliberately refuses to
bless them.  The `Signal.evidence` field always records the
original, un-normalised command string so audit logs stay faithful.

Because every gate above is a structural invariant derived from
earlier pipeline steps, a single-haystack regex hit is never enough
to emit read-only on its own.  This keeps the family trustworthy as a
fast-path signal.

The tag still does **not** change the verdict.  It exists so that
consumers (notably the intentframe-side deterministic Guardian) can
use the combination

    report.verdict == Verdict.SAFE
    and any(c.startswith("capability:read_only:") for c in report.capabilities)
    and "capability:filesystem_write" not in report.capabilities
    and "capability:stdin_exec"        not in report.capabilities
    and not any(c.startswith("capability:network_probe:") for c in report.capabilities)
    and not any(s.signal_id.startswith("edge:") for s in report.signals)
    and (report.code_intel is None or not report.code_intel.findings)

as an ALLOW short-circuit that skips the AE LLM call for obviously
passive reads — `ls`, `cat README.md`, `ps aux`, `grep foo src/`,
`git status`, **and now also** `ls -la | head`, `cd /tmp && ls`,
`ps aux | grep nginx`, `git log --oneline | head -50`, etc.  The
explicit `not …network_probe` exclusion is defensive — the structural
gate already prevents a single command from carrying both a
`read_only:*` and a `network_probe:*` tag, but the belt-and-braces
check keeps the fast-path honest if either family expands.

#### The network-probe family

`capability:network_probe:*` is a **positive fact family**, emitted
under the *same* structural-bareness predicate as the single-head
shape of `read_only:*`: one sub-command, no indirection, no dynamic
content, no shell composition.  Trusted-path head normalisation
applies here too — `/bin/ping 8.8.8.8` is recognised as `ping`,
`/usr/bin/curl https://…` as `curl`, and so on, under the same
`_TRUSTED_BIN_DIRS` allow-list.  There is no `network_probe:composition`
analogue: a pipeline that emits outbound traffic always needs a
specialised policy lane, not a fast-path.  Unlike `read_only:*`, the
check does **not** include the incompatible-prior-capability clause
— `network_probe:http_download` is deliberately allowed to co-exist
with other capabilities so the consumer can observe "network + disk"
simultaneously.

The critical difference from `read_only:*`:

> `network_probe:*` is NEVER a fast-path license.

Every tag here means the command emits outbound traffic, which is a
policy-relevant side effect regardless of tool (a `ping` on a corp
VPN, a `curl` carrying a bearer token, an `rsync` copying source to
an external host).  Consumers MUST treat these tags as a signal to
apply network policy, not as evidence of safety.  Recommended consumer
routing:

- `network_probe:icmp` / `trace` / `whois` / `dns` / `http_get` →
  cheap deterministic check (e.g. domain allow-list) → ALLOW or
  NEEDS_REVIEW
- `network_probe:http_mutate` / `http_download` / `port_scan` /
  `file_transfer` → always a specialised AE route with a prompt that
  knows the command is network-side-effecting

Within a single command only one HTTP sub-tag is emitted: the rule
table is ordered `http_mutate` → `http_download` → `http_get` so the
strictest applicable tag wins.  A POST `curl` is never downgraded to
`http_get` and a `curl -o file` is never masqueraded as idempotent.

### 4. Containment-edge extraction and walk

Step 8 builds the graph.  Each `Edge` carries:

- `kind` — `inline` / `referenced` / `piped_stdin` / `dynamic` / `interactive` / `compiled`
- `language` — best-effort language for the inner body
- `body` — inline payload (when available)
- `path_arg` — literal file path (for `referenced`)
- `resolvable` — whether the body can be obtained without executing the shell
- `unresolvable_reason` — e.g. `"command-substitution"`, `"variable-expansion"`, `"glob-pattern"`
- `depth` — 0 for the outermost command, 1 for one nested-interpreter layer, …

When `config.detect_file_path` is on (default) one `edge:<kind>` signal is emitted per edge — cheap, no I/O.

When `config.auto_resolve_local` is on **and** the caller passed a `ResolveSession`, the pipeline resolves each literal referenced path (respecting symlink rules, allow-roots, size caps), sniffs the on-disk language from extension → shebang → content, and runs the code inspector on the result.  Outcomes surface as `resolved:*` signals (`auto-read`, `truncated`, `binary`, `language-mismatch`, `outside-allow-roots`, `too-large`, `not-found`, …).

### 5. Deterministic code analysis

For every resolved node (and every inline body), the pipeline calls `inspect_code` and folds its `CodeReport` back into the parent `CommandReport`.  The analysers are:

- Python via AST walk
- Shell via regex heuristics

#### Python findings

Examples of Python findings emitted on `CodeIntel.findings`:

- `DANGEROUS_IMPORT_subprocess`
- `DANGEROUS_IMPORT_socket`
- `DANGEROUS_IMPORT_flask`
- `DANGEROUS_CALL_eval`
- `DANGEROUS_CALL_exec`
- `DANGEROUS_CALL_os_system`
- `DANGEROUS_CALL_os_kill`
- `DANGEROUS_CALL_signal_signal`
- `NETWORK_SERVER_BIND`
- `FILE_SYSTEM_ESCAPE_OPEN`
- `REFERENCES_INTENTFRAME`
- `PYTHON_SYNTAX_ERROR`

#### Shell findings

Examples of shell findings:

- `SHELL_EVAL`
- `SHELL_SOURCE_REMOTE`
- `SHELL_NESTED_BACKTICKS`
- `SHELL_CHMOD_NUMERIC`
- `SHELL_CHOWN`
- `SHELL_SYSTEM_REDIRECT`
- `SHELL_LONG_PIPE_CHAIN`
- `REFERENCES_INTENTFRAME`

These findings are structured, severity-bearing facts.  They still do not make policy decisions.

## Detected Script File Validation

This section explains how `command_shield` deals with script files — written for anyone who wants to understand the behaviour without reading the implementation.

### The default: nothing is ever read from disk

By default, `command_shield` **never opens a file**.  Even if a command like `python foo.py` clearly references a script on disk, the shield only notes "there is a path here" and stops.  No file is read, no disk is touched.

This is intentional.  The shield's primary job is inspecting what you *wrote in the command string*, not what is *stored on disk*.  Filesystem access is an explicit opt-in — something the caller chooses to enable, not something the shield assumes is safe.

### When does file reading happen?

Only when you enable it.  Two things must be true **at the same time**:

1. You set `auto_resolve_local=True` in a `ShieldConfig`.
2. You pass a `ResolveSession` that tells the shield which directory to work from and what it is allowed to read.

Without both, no file is ever opened.  If you set `auto_resolve_local=True` but forget the session, the report will contain a `resolved:no-session` signal and `script_resolved` stays `False`.  The feature simply does nothing rather than guessing.

### What is a ResolveSession?

Think of `ResolveSession` as a permission slip you hand to the shield.  It has three fields:

- **`cwd`** — "treat relative paths as relative to this directory".  So `foo.py` in the command becomes `/your/cwd/foo.py` on disk.
- **`allow_roots`** — "only read files inside these folders".  If you set `allow_roots=("/srv/work",)`, a path like `/etc/passwd` will be refused immediately with `resolved:outside-allow-roots`, before any read attempt.  Leave it empty to allow any path under `cwd`.
- **`follow_symlinks`** — "whether symlinks are okay".  Default is `False`: any symlink anywhere in the resolved path causes the read to fail with `resolved:symlink`.  Turn it on only if you fully trust the environment.

The session is never inferred from the running process — the caller always supplies it explicitly.  This means the shield's behaviour around files is fully predictable from the call site.

### What happens once a file is located?

The shield runs through a layered set of checks before touching the code inside.  Every check that fails produces a `resolved:*` signal and stops further processing of that file:

1. **Null byte in path** → refused immediately (`resolved:unsafe-path`).
2. **Outside allow roots** → refused (`resolved:outside-allow-roots`).
3. **File does not exist / stat error** → `resolved:stat-failed`.
4. **Is a symlink** → refused by default (`resolved:symlink`); allowed only if `follow_symlinks=True`.
5. **Not a regular file** → directories, devices, and sockets are all refused (`resolved:not-regular-file`).
6. **File is too large** → files over `max_resolved_bytes` (default **1 MB / 1,000,000 bytes**) are read only up to that limit.  The analysis continues on the prefix but you also get a `resolved:truncated` signal so you know the result covers only part of the file.
7. **Looks like a binary** → magic-byte / NUL-density check.  If the content looks like a compiled binary or other non-text format, code analysis is skipped entirely (`resolved:binary`).
8. **Language detection** → sniffed from file extension, then shebang line, then content heuristics.  If the sniffed language conflicts with what the command implied — e.g. `python mystery` where the file has `#!/bin/bash` — you get `resolved:language-mismatch` alongside the actual findings.
9. **Decoded text is too long** → code text longer than `max_code_length` (default **50,000 characters**) skips AST / regex analysis and emits `CODE_TOO_LARGE`.
10. **Static analysis** → Python files go through an AST walk; shell files go through regex heuristics.  Findings like `DANGEROUS_IMPORT_subprocess`, `SHELL_EVAL`, `NETWORK_SERVER_BIND`, etc. are emitted as structured facts.

All of these are signals — facts reported to the caller.  None of them change the `SAFE / NEEDS_REVIEW / CATASTROPHIC` verdict.

### Does any of this block the command?

No.  All `resolved:*` and size signals are **advisory**.  They flow downstream to the Analysis Engine and Guardian, which make the actual allow / block decision.  The only things that can produce `CATASTROPHIC` or `NEEDS_REVIEW` are the pattern and structural passes, which run on the *command string itself* before any file is ever touched.

### How deep does it go into nested commands?

Controlled by `resolve_max_depth` (default **2**).

- Depth 1: only the outermost command's edges are followed.
- Depth 2: one level of nested interpreter indirection is also resolved — so `bash -c "python inner.py"` will also read and inspect `inner.py`.
- Beyond the limit: edges are recorded but not walked, and the pipeline moves on silently.

### Quick reference

| Question | Answer |
|---|---|
| Does `command_shield` read files by default? | No. Never. |
| What enables file reading? | `auto_resolve_local=True` + a `ResolveSession` |
| What if I set the flag but forget the session? | `resolved:no-session` signal, nothing is read |
| Max file size read from disk? | 1 MB (default `max_resolved_bytes`) |
| What happens to files larger than that? | Truncated to 1 MB prefix + `resolved:truncated` signal |
| Max code length analysed? | 50,000 chars (default `max_code_length`) |
| Are symlinks followed? | No by default; opt in with `follow_symlinks=True` |
| Can it read files outside a directory root? | No, if `allow_roots` is set |
| Do file findings block the command? | No — signals only, never verdict-bearing |
| How deep does nested-interpreter resolution go? | 2 levels by default (`resolve_max_depth`) |

## Public API

`command_shield` intentionally exposes a small surface.

### Command inspection

#### `inspect_command(command, *, session=None, config=None) -> CommandReport`

Synchronous, deterministic full command inspection.  No LLM, no network, no policy decisions.  This is the primary entry point for runtime / policy / pre-execution callers.

- `session` — pass a `ResolveSession(cwd=..., allow_roots=..., follow_symlinks=...)` when you want `auto_resolve_local` to read referenced files.  Omit it for pure in-memory inspection.
- `config` — a `ShieldConfig`; defaults to `DEFAULT_CONFIG`.

#### `inspect_command_deep(command, *, session=None, config=None) -> CommandReport`  *(async)*

Runs the sync pipeline, then conditionally fires the LLM reviewer over the first in-scope code body when:

- LLM review is enabled,
- language is in scope,
- code body is present and within `max_code_length`,
- and deterministic findings or non-trivial capabilities justify the extra step.

If the LLM is unavailable or declined by the gate, the caller still gets the full deterministic report.

### Code inspection

#### `inspect_code(code, *, language=None, source_path=None, config=None) -> CodeReport`

Synchronous inspection of a raw code body.  Use this when you already have the content (a notebook cell, a file you read yourself, an LLM-generated script) and want structured findings without any shell parsing.

Pipeline inside `inspect_code`:

1. size gate (`CODE_TOO_LARGE`)
2. binary guard (magic bytes / NUL density → `resolved:binary`)
3. language selection: explicit > extension > shebang > content sniff
4. scope check (`resolved:unsupported-language` when out of scope)
5. deterministic analyser dispatch (Python AST / shell regex)

Returns a `CodeReport` with `language`, `source_path`, `code_intel`, `signals`, `reviewer_*` fields, and `elapsed_ms`.

#### `inspect_code_deep(code, *, ...) -> CodeReport`  *(async)*

Same deterministic pipeline, then conditional LLM review gated by findings.

### Executor floor

#### `quick_check(command, *, config=None) -> CommandReport`

Fast, last-resort check for an executor adapter right before subprocess launch.  A deliberately small subset of the full pipeline:

- size check,
- normalize,
- pattern match,
- inline interpreter indirection re-check.

Use this as a final floor, **not** as a replacement for full inspection.

### Utility

#### `clean_env() -> dict[str, str]`

Filtered `os.environ` safe to pass to subprocesses.

## Configuration

`ShieldConfig` controls operational analysis bounds, not user policy:

```python
from command_shield import ShieldConfig, ResolveSession, inspect_command

config = ShieldConfig(
    max_command_length=10_000,
    max_code_length=50_000,
    allowed_languages=frozenset({"python", "shell"}),
    enable_llm_review=True,
    detect_file_path=True,
    auto_resolve_local=False,
    max_resolved_bytes=1_000_000,
    resolve_max_depth=2,
    sniff_language_from_content=True,
)

report = inspect_command("python /srv/jobs/clean.py", config=config)
```

Meaning of each field:

- `max_command_length` — oversized commands emit `COMMAND_TOO_LARGE` and skip deeper analysis.
- `max_code_length` — oversized code emits `CODE_TOO_LARGE` and skips code analysis.
- `allowed_languages` — only these languages get deep code analysis.
- `enable_llm_review` — disables the deep reviewer even on the async path.
- `detect_file_path` — emit an `edge:*` signal per discovered containment edge.  Cheap, on by default; no I/O.
- `auto_resolve_local` — read literal referenced scripts and run the code inspector on them.  Off by default: caller must also supply a `ResolveSession`.
- `max_resolved_bytes` — hard cap per auto-resolved file.  Files larger than this emit `resolved:too-large` and are not read.
- `resolve_max_depth` — maximum edge-walk depth (e.g. 1 = outermost command only; 2 allows `bash -c "python foo.py"` to also resolve `foo.py`).
- `sniff_language_from_content` — fall back to content heuristics when extension/shebang are inconclusive.

Again: this is **inspection scope**, not authorization policy.

### `ResolveSession`

When you want `auto_resolve_local` to actually read files, pass a session that declares the environment and the safety envelope:

```python
from command_shield import ResolveSession

session = ResolveSession(
    cwd="/srv/work",
    allow_roots=("/srv/work",),      # only resolve inside these roots
    follow_symlinks=False,
)
```

The resolver enforces these constraints *before* reading anything.  Violations surface as `resolved:outside-allow-roots`, `resolved:symlink`, `resolved:not-found`, etc.

## Consumer Usage

### 1. Runtime / policy caller (pure in-memory)

```python
from command_shield import inspect_command

report = inspect_command(command)

if report.is_catastrophic:
    reject(report)

capabilities   = report.capabilities
signals        = report.signals
findings       = report.code_intel.findings if report.code_intel else ()
script_target  = report.script_path_candidate   # literal path, if any
```

Typical consumer behaviour:

- block immediately on `CATASTROPHIC`,
- use `capabilities` for deterministic policy,
- use `code_intel.findings` for deterministic policy or AI context,
- use `signals` as the stable cross-cutting summary.

### 2. Runtime / policy caller (with auto-resolve)

When you trust a local filesystem root and want the shield to read referenced scripts for you:

```python
from command_shield import inspect_command, ShieldConfig, ResolveSession

config = ShieldConfig(auto_resolve_local=True)
session = ResolveSession(cwd="/srv/work", allow_roots=("/srv/work",))

report = inspect_command("python jobs/clean.py", session=session, config=config)

for node in report.resolved_nodes:
    if node.code_report:
        print(node.path, node.code_report.code_intel)
```

### 3. Direct code-string inspection

No shell parsing, no I/O — just analyse a body you already have:

```python
from command_shield import inspect_code

report = inspect_code(open("my_script.py").read(), language="python", source_path="my_script.py")

if report.code_intel:
    for finding in report.code_intel.findings:
        print(finding.finding_id, finding.severity, finding.evidence)
```

This is the right entry point when:

- you want to inspect an LLM-generated snippet,
- you already read a file yourself and just want the findings,
- you are processing notebook cells or templated scripts.

### 4. Executor caller

```python
from command_shield import quick_check

report = quick_check(command)
if report.is_catastrophic:
    raise RuntimeError("blocked catastrophic command")
```

Final floor only — not a replacement for full inspection.

### 5. Deep inspection caller

```python
from command_shield import inspect_command_deep

report = await inspect_command_deep(command)
if report.reviewer_ran:
    use_reviewer_findings(report.reviewer_findings)
```

Useful for offline triage or explicit deep-review flows.

### 6. Policy examples

`command_shield` does not implement policy, but is designed to make policy easy.

- Does this command install packages? → match `capability:package_install:*`
- Allow `pip` but deny `apt`? → allow `capability:package_install:pip`, deny `capability:package_install:apt`
- Allow Python scripts but deny Node? → allow `capability:script_execution:python`, deny `capability:script_execution:node`
- Fast-path obviously read-only commands (no AE call)? → allow on `capability:read_only:*` when no deny capabilities fire
- Deny all listeners? → deny `capability:network_bind`
- Deny any file writes via shell redirection? → deny `capability:filesystem_write`
- Deny any code touching system paths? → deny `FILE_SYSTEM_ESCAPE_OPEN`
- Flag any code that references runtime internals? → deny `REFERENCES_INTENTFRAME`
- Deny commands that stream code into an interpreter? → deny `capability:stdin_exec` or `edge:piped_stdin`

### 7. Investigation examples

`command_shield` is often enough when the question is narrow and mechanical:

- "What would this terminal command execute?"
- "Does this command reference a local script or inline code?"
- "If I allow local resolution, what findings exist in that Python or shell script?"
- "I already read this notebook cell / generated script; what deterministic findings does it contain?"

It is **not** the right tool when the question is broader:

- "How does this repository work overall?"
- "Where is this symbol used across the codebase?"
- "What data flow reaches this function across multiple files?"
- "Is this application behavior safe in context of business logic and user intent?"

For those questions, use repo search, semantic navigation, or a higher-level analysis layer on top of the facts `command_shield` emits.

## Design Principles

### Deterministic first

Known dangerous command structures should be classified without spending LLM tokens.

### Facts, not policy

`command_shield` answers:

- what is this command structurally,
- what did it match,
- what capabilities does it expose,
- what code units does it reach,
- what static-analysis findings exist.

It does not answer:

- should this user be allowed to do it,
- is root acceptable here,
- does the current task justify the behavior,
- what does session history imply.

Those are consumer responsibilities.

### Stable contract

The most important contract is small and durable:

- `CommandReport.verdict`
- `CommandReport.signals`
- `CommandReport.sub_commands`

Everything else is additive.

### Standalone module

`command_shield` deliberately does not import `intentframe_components`, `policy_registry`, or `executor`.  It stays reusable as a pure inspection library.

### Explicit opt-in for I/O

The shield does not touch the filesystem by default.  Reading a referenced script requires `auto_resolve_local=True` **and** a `ResolveSession` whose `allow_roots` the caller explicitly chose.  This keeps the module safe to call in any environment.

## What `command_shield` Does Not Do

- It does not apply user policy.
- It does not know execution privilege or root context.
- It does not track session write history on its own.
- It does not prove code is safe.
- It does not replace downstream semantic analysis.
- It does not crawl or index an entire repository.
- It does not build cross-file call graphs or usage graphs.
- It does not mutate commands.
- It does not resolve filesystem paths unless the caller explicitly opts in.

It is a deterministic inspection module whose job is to turn a raw command string (or a raw code body) into structured facts.

## Recommended Consumer Pattern

For most consumers:

1. call `inspect_command(...)` (add `session=` + `auto_resolve_local=True` only if you trust the local fs root),
2. hard-block `CATASTROPHIC`,
3. consume `capabilities`, `signals`, `resolved_nodes`, and `code_intel`,
4. apply policy,
5. only call deeper AI reasoning when deterministic gates do not already decide the outcome.

When you already have the content and don't need shell parsing, call `inspect_code(...)` directly.

That keeps mechanical inspection centralized in one place and reserves expensive semantic reasoning for the cases where it is actually needed.
