"""Capability classification — deterministic regex/structural tags.

Step 7 of the inspection pipeline.  Works on any command string
regardless of language support; tags describe *what the command can
do*, not *whether it is allowed*.  Consumer (Guardian/AE) decides what
to do with each capability.

Emitted capability IDs (stable contract).  Tags marked `:<suffix>` are
refined so that policy can allow/deny at the tool grain (e.g. allow
`capability:package_install:pip` but deny `capability:package_install:apt`):

    capability:package_install:pip       — pip / pip3 / pipx / uv / poetry / conda / mamba
    capability:package_install:npm       — npm / pnpm / yarn
    capability:package_install:brew      — Homebrew
    capability:package_install:apt       — apt / apt-get (Debian / Ubuntu)
    capability:package_install:yum       — yum (RHEL / CentOS)
    capability:package_install:dnf       — dnf (Fedora)
    capability:package_install:pacman    — pacman (Arch)
    capability:package_install:apk       — apk (Alpine)
    capability:package_install:gem       — gem (Ruby)
    capability:package_install:cargo     — cargo install (Rust)
    capability:package_install:go        — go install (Go)
    capability:package_install:composer  — composer install / require (PHP)

    capability:script_execution:python       — `python foo.py` / `python3 foo.py`
    capability:script_execution:node         — `node app.js` / `.mjs` / `.cjs`
    capability:script_execution:ruby         — `ruby foo.rb`
    capability:script_execution:perl         — `perl foo.pl`
    capability:script_execution:shell        — `bash foo.sh` / `sh` / `zsh` / `ksh` / `dash`
    capability:script_execution:local_binary — `./foo` / `./bin/tool`

    capability:read_only:filesystem_list   — ls / tree / stat / file / du / df / lsattr / getfacl
                                               / namei / pathchk / findmnt / mountpoint / lsblk
                                               / blkid / find (safe flags)
    capability:read_only:filesystem_read   — cat / head / tail / less / more / wc / hexdump / xxd
                                               / od / nl / tac / rev / md5sum / sha*sum / b2sum
                                               / shasum / cksum / sum
    capability:read_only:search            — grep / egrep / fgrep / rg / ack / jq / yq / xmllint
                                               (no --output)
    capability:read_only:process_inspect   — ps / top / htop / lsof / pgrep / pidof / uptime / w
                                               / free / vmstat / iostat / mpstat / ipcs / nproc
                                               / arch / last / who / users / getent / cal / ncal
    capability:read_only:system_info       — uname / whoami / id / hostname / date / pwd / env
                                               / which / man / info / apropos / tput / alias
                                               / clear / reset / seq / factor / printf
                                               / sysctl (no -w / -p) / ulimit (no value) / stty
                                               (bare / -a / -g)
    capability:read_only:vcs_inspect       — git / hg / svn / fossil / bzr read-only sub-commands
    capability:read_only:text_transform    — sort (no -o) / sdiff (no -o) / uniq (≤1 positional)
                                               / cut / paste / join / tr / column / fold / fmt
                                               / pr / expand / unexpand / comm / diff / diff3
                                               / cmp / colordiff / delta
    capability:read_only:network_inspect   — netstat / ss / arp (no -s / -d) / ip <obj> show|list
                                               / route (no add / del / flush) / ifconfig (inspect)
    capability:read_only:archive_inspect   — tar -t*f / --list / unzip -l|-v|-Z|-t|-p|-c
                                               / zipinfo / (gzip|bzip2|xz|zstd) -l|-t / zcat
                                               / bzcat / xzcat / zstdcat / z-less|more|grep
                                               family
    capability:read_only:container_inspect — docker / podman (ps|images|logs|inspect|info|version
                                               |history|port|diff|top|stats|events|network ls
                                               |volume ls) / kubectl (get|describe|logs|top
                                               |version|api-resources|explain|config view
                                               |cluster-info|auth can-i)

    capability:network_probe:icmp          — ping / ping6
    capability:network_probe:trace         — traceroute / traceroute6 / tracepath / tracepath6 / mtr
    capability:network_probe:dns           — dig / nslookup / host / drill / kdig
    capability:network_probe:whois         — whois
    capability:network_probe:http_get      — curl / wget (-O -) / http / https / xh — idempotent GET
                                               to stdout (no body, no -o/-O)
    capability:network_probe:http_mutate   — curl / wget / http / xh with POST|PUT|DELETE|PATCH
                                               or any body/form/upload flag
    capability:network_probe:http_download — curl -o|-O|--output|--remote-name; wget default mode
                                               (response persisted to disk)
    capability:network_probe:port_scan     — nmap / masscan / zmap / nc | ncat | netcat in connect
                                               mode (no -l / -k)
    capability:network_probe:file_transfer — scp / sftp / rsync with [user@]host: endpoint /
                                               rclone (copy|sync|move|mount|serve|ls|cat|…)

    capability:compilation       — compiles/links code (gcc/clang/make/...)
    capability:filesystem_write  — writes to a file via shell redirection or tee
    capability:network_bind      — binds a local network port/listener
    capability:background_exec   — backgrounds a process (nohup/&/screen)
    capability:download_and_exec — fetches a remote payload and pipes to a shell
    capability:binary_download   — fetches a remote payload to disk (no shell pipe)
    capability:process_signal    — sends signals to processes (kill/pkill/killall)
    capability:spawns_process    — shells out / spawns a child process
    capability:stdin_exec        — pipes data into an interpreter (`… | python -`)

Each hit produces a Signal with check="capability" and signal_id set to
the capability tag.  Multiple capabilities per command are expected;
they are not mutually exclusive.  Policy can match exact tags or use
prefix matching on the `:` boundary (e.g. `capability:package_install:*`).

`capability:read_only:*` is a positive fact family: it fires only when
the command is structurally a bare single-head invocation (bashlex
reports exactly one sub-command, no interpreter indirection, and no
shell composition / redirect tokens).  Consumers — notably the
intentframe-side deterministic Guardian — use the combination
``verdict == SAFE`` + at least one ``capability:read_only:*`` + no
deny-listed capabilities + no edge/code-intel signals as a fast-path
ALLOW rule that skips the AE LLM call.  The tag still does not change
the verdict — that stability guarantee is preserved.

`capability:network_probe:*` is ALSO a positive fact family that fires
only under the same structural-bareness predicate, but unlike
``read_only:*`` it is NOT a fast-path license.  Every tag here says
"this command emits outbound traffic", which is a policy-relevant side
effect regardless of tool (ping on a corp VPN, curl with a secret-
containing header, rsync to a remote host, etc.).  Consumers should
route these tags to a specialized AE lane with domain-allowlist logic
or a conservative ALLOW policy they own — ``command_shield`` itself
takes no position.  The consumer-side fast-path check SHOULD include
a defensive ``not any(c.startswith("capability:network_probe:"))``
clause so an unanticipated interaction between families cannot upgrade
a network-emitting command to ALLOW.
"""

from __future__ import annotations

import re
import shlex

from command_shield.verdict import Signal

# ── Capability IDs ───────────────────────────────────────────────────

CAPABILITY_PACKAGE_INSTALL = "capability:package_install"
CAPABILITY_COMPILATION = "capability:compilation"
CAPABILITY_SCRIPT_EXECUTION = "capability:script_execution"
CAPABILITY_NETWORK_BIND = "capability:network_bind"
CAPABILITY_BACKGROUND_EXEC = "capability:background_exec"
CAPABILITY_DOWNLOAD_AND_EXEC = "capability:download_and_exec"
CAPABILITY_BINARY_DOWNLOAD = "capability:binary_download"
CAPABILITY_PROCESS_SIGNAL = "capability:process_signal"
CAPABILITY_SPAWNS_PROCESS = "capability:spawns_process"
CAPABILITY_STDIN_EXEC = "capability:stdin_exec"
CAPABILITY_FILESYSTEM_WRITE = "capability:filesystem_write"
CAPABILITY_READ_ONLY = "capability:read_only"
CAPABILITY_NETWORK_PROBE = "capability:network_probe"


# ── Detection rules ─────────────────────────────────────────────────
#
# Each rule is (regex, capability_id, description).
# Regexes run against the normalized command string and against each
# indirection payload.  Rules are intentionally conservative — false
# negatives are preferable to false positives, since the verdict comes
# from step 3 patterns and these signals are advisory.

# Refined rules: one per manager so policy can allow/deny at tool grain.
# Order matters only within a capability family (first match wins per tag
# in `seen`); across capabilities all independent rules are evaluated.
_PACKAGE_INSTALL_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:pip3?|pipx|uv|poetry|conda|mamba)\s+install\b"), "pip"),
    (re.compile(r"\b(?:npm|pnpm)\s+(?:i|install|add)\b|\byarn\s+(?:add|install)\b"), "npm"),
    (re.compile(r"\bbrew\s+(?:install|reinstall|upgrade)\b"), "brew"),
    (re.compile(r"\bapt(?:-get)?\s+(?:install|upgrade)\b"), "apt"),
    (re.compile(r"\byum\s+(?:install|update)\b"), "yum"),
    (re.compile(r"\bdnf\s+(?:install|upgrade)\b"), "dnf"),
    (re.compile(r"\bpacman\s+-S\b"), "pacman"),
    (re.compile(r"\bapk\s+add\b"), "apk"),
    (re.compile(r"\bgem\s+install\b"), "gem"),
    (re.compile(r"\bcargo\s+install\b"), "cargo"),
    (re.compile(r"\bgo\s+install\b"), "go"),
    (re.compile(r"\bcomposer\s+(?:install|require)\b"), "composer"),
)

# Refined rules: one per interpreter.  Excludes inline `-c` / `-e` /
# `--eval` forms (those are classified as inline code by the language
# detector, not as script-file execution).
_SCRIPT_EXECUTION_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bpython3?\s+[^|;&]*\.py\b"), "python"),
    (re.compile(r"\bnode\s+[^|;&]*\.(?:js|mjs|cjs)\b"), "node"),
    (re.compile(r"\bruby\s+[^|;&]*\.rb\b"), "ruby"),
    (re.compile(r"\bperl\s+[^|;&]*\.pl\b"), "perl"),
    (re.compile(r"\b(?:bash|sh|zsh|ksh|dash)\s+[^|;&]*\.(?:sh|bash|zsh)\b"), "shell"),
    (re.compile(r"(?:^|[\s;&|])\./[\w.][\w./-]*"), "local_binary"),
)


def _expand_refined(
    rules: tuple[tuple[re.Pattern[str], str], ...],
    base: str,
    desc_template: str,
) -> tuple[tuple[re.Pattern[str], str, str], ...]:
    return tuple(
        (rx, f"{base}:{suffix}", desc_template.format(suffix=suffix))
        for rx, suffix in rules
    )


_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    # Refined: package installation (one rule per manager).
    *_expand_refined(
        _PACKAGE_INSTALL_RULES,
        CAPABILITY_PACKAGE_INSTALL,
        "Command installs packages via {suffix}",
    ),
    # Refined: script execution (one rule per interpreter).
    *_expand_refined(
        _SCRIPT_EXECUTION_RULES,
        CAPABILITY_SCRIPT_EXECUTION,
        "Command executes a {suffix} script or local binary",
    ),
    # Compilation / build — compilers and build drivers.
    (
        re.compile(
            r"(?:^|[\s;&|])(?:gcc|g\+\+|clang|clang\+\+|cc|ld)\b"
            r"|\bmake\b"
            r"|\bcmake\b"
            r"|\bcargo\s+build\b"
            r"|\bgo\s+build\b"
            r"|\brustc\b"
            r"|\bjavac\b"
            r"|\bswiftc\b"
            r"|\btsc\b"
        ),
        CAPABILITY_COMPILATION,
        "Command compiles or links code",
    ),
    # Network bind — opening a listener on a local port.  Accepts
    # both the short `-l` (possibly inside a combined flag bundle like
    # `-lk`) and the long `--listen` form.
    (
        re.compile(
            r"\bnc\b(?=[^|]*(?:\s-[a-zA-Z]*l|\s--listen\b))"
            r"|\bncat\b(?=[^|]*(?:\s-[a-zA-Z]*l|\s--listen\b))"
            r"|\bsocat\b[^|]*\bLISTEN\b"
            r"|\bpython3?\s+-m\s+http\.server\b"
            r"|\bpython3?\s+-m\s+SimpleHTTPServer\b"
            r"|\bphp\s+-S\b"
            r"|\bruby\s+-run\s+-e\s+httpd\b"
        ),
        CAPABILITY_NETWORK_BIND,
        "Command binds a local network listener",
    ),
    # Background execution — persists beyond the current shell.
    (
        re.compile(
            r"\bnohup\b"
            r"|\bdisown\b"
            r"|\bsetsid\b"
            r"|\bscreen\s+-d(?:m)?\b"
            r"|\btmux\s+new-session\s+-d\b"
            r"|[^&|]&\s*(?:$|[;\n])"
        ),
        CAPABILITY_BACKGROUND_EXEC,
        "Command runs a process in the background",
    ),
    # Download-and-execute — fetch remote payload piped into a shell.
    # (Note: catastrophic subset of this is already caught by step 3.
    # Here we tag the capability for any remote-fetch-then-execute shape.)
    (
        re.compile(
            r"\b(?:curl|wget|fetch|aria2c)\b[^|]*\|\s*"
            r"(?:sh|bash|zsh|dash|python3?|perl|ruby|node)\b"
        ),
        CAPABILITY_DOWNLOAD_AND_EXEC,
        "Command downloads a remote payload and pipes it to an interpreter",
    ),
    # Binary download — fetches a remote payload to disk without piping
    # it straight to a shell.  The pipe-to-shell variant is already tagged
    # as download_and_exec above; both may fire together for
    # `curl -O url | sh` shapes, which is intentional.
    (
        re.compile(
            r"\bcurl\b[^|]*\s-[OoLJ]\b"
            r"|\bwget\b(?![^|]*\|\s*(?:sh|bash|zsh|dash|python3?|perl|ruby|node))"
            r"|\baria2c\b"
        ),
        CAPABILITY_BINARY_DOWNLOAD,
        "Command downloads a remote payload to disk",
    ),
    # Stdin-piped interpreter execution — `… | python -`, `… | bash`.
    # Distinct from download_and_exec (no network fetch component) and
    # from script_execution (no literal file path).  Treated as a
    # capability rather than a verdict-bearing pattern because benign
    # uses exist (`echo 'print(1)' | python`), but the edge body is
    # unresolvable so policy layers may want to deny it outright.
    (
        re.compile(
            r"\|\s*(?:python3?|python2|node|nodejs|ruby|perl|"
            r"bash|sh|zsh|dash|ksh|ash)(?:\s+-)?(?=\s|$|\||;|&)"
        ),
        CAPABILITY_STDIN_EXEC,
        "Command pipes input into an interpreter (stdin exec)",
    ),
    # Process signaling — kill/pkill/killall family.
    (
        re.compile(
            r"\bkill\s+-\w*\b"
            r"|\bkill\s+-?\d+\b"
            r"|\bkillall\b"
            r"|\bpkill\b"
            r"|\bskill\b"
        ),
        CAPABILITY_PROCESS_SIGNAL,
        "Command sends signals to processes",
    ),
    # Generic spawn — shells out via common indirection verbs.
    (
        re.compile(
            r"\bxargs\b"
            r"|\bfind\b[^|]*-exec\b"
            r"|\bsudo\b"
            r"|\bsu\b(?=\s+-)"
            r"|\bssh\b"
            r"|\bdocker\s+(?:run|exec)\b"
            r"|\bkubectl\s+exec\b"
        ),
        CAPABILITY_SPAWNS_PROCESS,
        "Command spawns or delegates to another process",
    ),
    # Filesystem write via shell redirection or `tee`.  The leading
    # boundary `(?:^|[\s;&|])` ensures a literal `>` in a quoted arg
    # (e.g. `grep "a>b" f`) does NOT match after shlex has stripped
    # the quotes — the `>` would be preceded by a word character.
    # Writes to `/dev/null`, `/dev/stdout`, `/dev/stderr`, `/dev/fd/*`
    # are excluded as benign sinks; writes to other `/dev/*` paths are
    # already caught by catastrophic patterns.
    (
        re.compile(
            r"(?:^|[\s;&|])(?:>>?|&>|2>>?)\s*"
            r"(?!/dev/(?:null|stdout|stderr|fd/\d+)(?:\s|$))\S"
            r"|\|\s*tee\b"
        ),
        CAPABILITY_FILESYSTEM_WRITE,
        "Command writes to a file via shell redirection or tee",
    ),
)


# ── Read-only family ─────────────────────────────────────────────────
#
# These rules are only evaluated when the command is structurally a
# bare single-head invocation — see `_safe_for_read_only` for the full
# gate.  Each regex is anchored with ``\A…\Z`` and matches the entire
# normalized command, so the presence of any shell composition or
# write redirect already disqualifies the command at the gate.
#
# Rules that accept arguments are deliberately permissive about what
# positional arguments look like (paths, globs, regex patterns) — the
# safety invariants come from the gate, not from per-argument parsing.
# Flags with known destructive modes (e.g. `find -delete`, `find
# -exec`, `sed -i`) are excluded via negative lookahead so those
# commands never receive a read-only tag.

_READ_ONLY_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # ── filesystem_list ──────────────────────────────────────────────
    # `ls` / `tree` / `stat` / `file` / `du` / `df` plus metadata tools:
    # `lsattr` (ext-attrs), `getfacl` (ACLs), `namei` (path resolution),
    # `pathchk` (portable-name check), `findmnt` / `mountpoint` (mount
    # inspection), `lsblk` / `blkid` (block-device inspection).
    (
        re.compile(
            r"\A(?:ls|tree|stat|file|du|df|lsattr|getfacl|namei|pathchk"
            r"|findmnt|mountpoint|lsblk|blkid)"
            r"(?:\s+-{1,2}[A-Za-z0-9][A-Za-z0-9\-]*(?:=\S+)?)*"
            r"(?:\s+[^\s]+)*\s*\Z",
        ),
        "filesystem_list",
    ),
    # `find` — excluded when any write/exec flag is present.
    (
        re.compile(
            r"\Afind"
            r"(?!.*\s-(?:delete|exec|execdir|ok|okdir|fprint|fprintf|fls)\b)"
            r"(?:\s+[^\s]+)*\s*\Z",
        ),
        "filesystem_list",
    ),

    # ── filesystem_read ──────────────────────────────────────────────
    # File readers.  `sed` and `awk` are intentionally NOT included —
    # both support in-place write modes (`sed -i`, `awk -i inplace`).
    # Hashers (`md5sum`, `sha*sum`, `b2sum`, `shasum`, `cksum`, `sum`)
    # are read-only computations over file contents.
    (
        re.compile(
            r"\A(?:cat|head|tail|less|more|wc|hexdump|xxd|od|nl|tac|rev"
            r"|md5sum|sha1sum|sha224sum|sha256sum|sha384sum|sha512sum"
            r"|b2sum|shasum|cksum|sum)"
            r"(?:\s+-{1,2}[A-Za-z0-9][A-Za-z0-9\-]*(?:=\S+)?)*"
            r"(?:\s+[^\s]+)+\s*\Z",
        ),
        "filesystem_read",
    ),

    # ── search ───────────────────────────────────────────────────────
    # Content search.  `grep -P` with `(?{...})` perl-embed requires
    # `use re 'eval'` which grep does not enable, so it is safe as a
    # read-only operation from grep's side.  Structured-data queries
    # (`jq`, `yq`) have no in-place write mode; `xmllint` DOES have
    # `--output` so its write form is excluded via negative lookahead.
    (
        re.compile(
            r"\A(?:grep|egrep|fgrep|rg|ack|jq|yq)"
            r"(?:\s+-{1,2}[A-Za-z0-9][A-Za-z0-9\-]*(?:=\S+)?)*"
            r"(?:\s+[^\s]+)+\s*\Z",
        ),
        "search",
    ),
    # `xmllint` — excluded when `--output` / `-o` is present.
    (
        re.compile(
            r"\Axmllint"
            r"(?!(?:.*\s)(?:--output\b|-o\b))"
            r"(?:\s+[^\s]+)+\s*\Z",
        ),
        "search",
    ),

    # ── process_inspect ──────────────────────────────────────────────
    # Process / runtime / host-activity inspection.  `dmesg` typically
    # requires root on Linux and is intentionally omitted to keep the
    # tag trustworthy for non-privileged agents.
    (
        re.compile(
            r"\A(?:ps|top|htop|lsof|pgrep|pidof|uptime|w|jobs|fg|bg"
            r"|free|vmstat|iostat|mpstat|ipcs|nproc|arch"
            r"|last|lastlog|who|users|finger|getent|cal|ncal)"
            r"(?:\s+[^\s]+)*\s*\Z",
        ),
        "process_inspect",
    ),

    # ── system_info ──────────────────────────────────────────────────
    # Identity / environment / docs / terminal-query tools.  Several
    # binaries here share a name with writers (`sysctl`, `stty`,
    # `ulimit`); those get separate rules below that positively match
    # only the read forms.
    (
        re.compile(
            r"\A(?:uname|whoami|id|hostname|date|pwd|env|printenv|echo"
            r"|true|false|which|whereis|type|history|readlink|basename"
            r"|dirname|realpath|locale|tty|groups"
            r"|man|info|apropos|whatis|tldr|tput"
            r"|alias|clear|reset"
            r"|seq|factor|printf)"
            r"(?:\s+[^\s]+)*\s*\Z",
        ),
        "system_info",
    ),
    # `sysctl` — read forms only.  Excludes `-w|--write` (set value)
    # and `-p|--load` (load values from file).
    (
        re.compile(
            r"\Asysctl"
            r"(?!(?:.*\s)(?:-w\b|--write\b|-p\b|--load\b))"
            r"(?:\s+[^\s]+)*\s*\Z",
        ),
        "system_info",
    ),
    # `ulimit` — bare invocation or a single inspection flag (no
    # trailing value).  `ulimit -n 4096` (value-bearing) is rejected.
    (
        re.compile(r"\Aulimit(?:\s+-[A-Za-z])?\s*\Z"),
        "system_info",
    ),
    # `stty` — bare / `-a` / `-g` (dump settings in restoreable form).
    # Any other form mutates terminal attributes.
    (
        re.compile(r"\Astty(?:\s+(?:-a|--all|-g|--save))?\s*\Z"),
        "system_info",
    ),

    # ── vcs_inspect ──────────────────────────────────────────────────
    # Git read-only sub-commands.  `git config --get` / `--list` only;
    # `git config key value` (write) is rejected.
    (
        re.compile(
            r"\Agit\s+(?:status|log|diff|show|branch|remote|rev-parse"
            r"|ls-files|ls-tree|ls-remote|describe|blame|shortlog"
            r"|reflog|stash\s+list|tag(?:\s+-l)?|for-each-ref"
            r"|config\s+(?:--get|--list|-l))"
            r"(?:\s+[^\s]+)*\s*\Z",
        ),
        "vcs_inspect",
    ),
    # Mercurial read-only sub-commands.
    (
        re.compile(
            r"\Ahg\s+(?:status|st|log|diff|cat|annotate|branch|manifest"
            r"|tip|summary|heads|parents|identify|paths|showconfig)"
            r"(?:\s+[^\s]+)*\s*\Z",
        ),
        "vcs_inspect",
    ),
    # Subversion read-only sub-commands.
    (
        re.compile(
            r"\Asvn\s+(?:status|st|log|diff|di|info|list|ls|cat"
            r"|propget|pg|propdump|pd|proplist|pl|blame|annotate|praise)"
            r"(?:\s+[^\s]+)*\s*\Z",
        ),
        "vcs_inspect",
    ),
    # Fossil read-only sub-commands.
    (
        re.compile(
            r"\Afossil\s+(?:status|timeline|info|ls|finfo|branch|diff)"
            r"(?:\s+[^\s]+)*\s*\Z",
        ),
        "vcs_inspect",
    ),
    # Bazaar read-only sub-commands.
    (
        re.compile(
            r"\Abzr\s+(?:status|st|log|diff|info|ls|cat|annotate)"
            r"(?:\s+[^\s]+)*\s*\Z",
        ),
        "vcs_inspect",
    ),

    # ── text_transform ───────────────────────────────────────────────
    # Pure stdin/file → stdout processors.  `sed` / `awk` / general-
    # purpose interpreters are deliberately excluded because their
    # argument body can do anything.
    #
    # `sort` / `sdiff` have `-o outfile` write modes; excluded via
    # negative lookahead.  `uniq` has a two-positional write form
    # (`uniq input output`); handled with its own stricter rule.
    (
        re.compile(
            r"\A(?:sort|sdiff)"
            r"(?!(?:.*\s)(?:-o\b|--output\b))"
            r"(?:\s+[^\s]+)*\s*\Z",
        ),
        "text_transform",
    ),
    (
        re.compile(
            r"\Auniq"
            # Any number of flags (with optional attached or numeric
            # argument for -f/-s/-w/-D/-C).
            r"(?:"
            r"\s+-{1,2}[A-Za-z0-9][A-Za-z0-9\-]*(?:=\S+)?"
            r"|\s+-[fsDCw]\s+\d+"
            r")*"
            # At most ONE positional (the input file); forbidding a
            # second positional rejects `uniq input output`.
            r"(?:\s+[^-][^\s]*)?\s*\Z",
        ),
        "text_transform",
    ),
    (
        re.compile(
            r"\A(?:cut|paste|join|tr|column|fold|fmt|pr|expand|unexpand"
            r"|comm|diff|diff3|cmp|colordiff|delta)"
            r"(?:\s+[^\s]+)*\s*\Z",
        ),
        "text_transform",
    ),

    # ── network_inspect ──────────────────────────────────────────────
    # Local network-state inspection with no outbound traffic.  Tools
    # that actively probe remote hosts (`ping`, `traceroute`, `dig`,
    # `nmap`, `curl`, `wget`) are deliberately NOT tagged here — they
    # belong to a separate `network_probe` family if/when desired.
    (
        re.compile(
            r"\A(?:netstat|ss)"
            r"(?:\s+[^\s]+)*\s*\Z",
        ),
        "network_inspect",
    ),
    # `arp` — excluded on `-s` (add entry) / `-d` (delete entry).
    (
        re.compile(
            r"\Aarp"
            r"(?!(?:.*\s)-[sd]\b)"
            r"(?:\s+[^\s]+)*\s*\Z",
        ),
        "network_inspect",
    ),
    # `ip <obj> show|list|get`.  Explicit verb-discrimination rejects
    # `ip addr add`, `ip route del`, etc.
    (
        re.compile(
            r"\Aip(?:\s+-\S+)*"
            r"\s+(?:addr|address|link|route|neigh|neighbour|rule"
            r"|tunnel|netns|xfrm|maddr|mroute|tcp_metrics|token)"
            r"\s+(?:show|list|s|l|get|save)"
            r"(?:\s+[^\s]+)*\s*\Z",
        ),
        "network_inspect",
    ),
    # `route` — excluded on `add|del|delete|flush|change|replace`.
    (
        re.compile(
            r"\Aroute"
            r"(?!(?:.*\s)(?:add|del|delete|flush|change|replace)\b)"
            r"(?:\s+[^\s]+)*\s*\Z",
        ),
        "network_inspect",
    ),
    # `ifconfig` — safe forms: bare, `-a|-s|-v`, or a single interface
    # name.  Any trailing modification verb (`up|down|<ip>|mtu|...`)
    # takes a second token and fails the end-anchor.
    (
        re.compile(
            r"\Aifconfig(?:\s+(?:-[asv]|[a-zA-Z][a-zA-Z0-9]+))?\s*\Z",
        ),
        "network_inspect",
    ),

    # ── archive_inspect ──────────────────────────────────────────────
    # List contents of an archive without extracting.
    #
    # `tar` mode letters are exclusive; the negative lookahead rejects
    # any bundle containing `c|x|r|A|u` or the long-form write verbs.
    # `f?` allows the rare stdin-driven `tar -t` form.
    (
        re.compile(
            r"\Atar"
            r"(?!(?:.*\s)(?:-[a-zA-Z]*[cxrAu][a-zA-Z]*\b"
            r"|--(?:create|extract|append|update|concatenate|catenate|delete)\b))"
            r"\s+(?:-[a-zA-Z]*t[a-zA-Z]*|--list)"
            r"(?:\s+[^\s]+)*\s*\Z",
        ),
        "archive_inspect",
    ),
    # `unzip` with a safe mode flag (list/verbose/zipinfo/test/stream).
    # Bundle may combine only letters from `[lvZtpcq]`, rejecting
    # extraction modifiers (`-o|-n|-d|-j`).
    (
        re.compile(
            r"\Aunzip\s+-[lvZtpcq]+"
            r"(?:\s+[^\s]+)+\s*\Z",
        ),
        "archive_inspect",
    ),
    (
        re.compile(r"\Azipinfo(?:\s+[^\s]+)+\s*\Z"),
        "archive_inspect",
    ),
    # Compression list / test modes.
    (
        re.compile(
            r"\A(?:gzip|bzip2|xz|zstd|lzma)"
            r"\s+(?:-l|--list|-t|--test|-tv)"
            r"(?:\s+[^\s]+)*\s*\Z",
        ),
        "archive_inspect",
    ),
    # Streaming decompressors that write to stdout (cat/less/more/grep
    # on compressed archives).  None of these write back to disk.
    (
        re.compile(
            r"\A(?:zcat|bzcat|xzcat|zstdcat|lz4cat"
            r"|zless|zmore|bzless|bzmore|xzless|xzmore|zstdless|zstdmore"
            r"|zgrep|zegrep|zfgrep|bzgrep|xzgrep|zstdgrep)"
            r"(?:\s+[^\s]+)+\s*\Z",
        ),
        "archive_inspect",
    ),

    # ── container_inspect ────────────────────────────────────────────
    # Read-only container-runtime and cluster queries.  `docker run` /
    # `docker exec` / `kubectl apply` / `kubectl exec` / `kubectl
    # delete` etc. are NOT in the subcommand list and therefore do not
    # match; `docker exec` / `kubectl exec` also get tagged as
    # `capability:spawns_process` which the gate rejects separately.
    (
        re.compile(
            r"\A(?:docker|podman)\s+"
            r"(?:ps|images|image\s+(?:ls|inspect|history)"
            r"|logs|inspect|info|version|history|port|diff|top|stats"
            r"|events|network\s+(?:ls|inspect)"
            r"|volume\s+(?:ls|inspect)"
            r"|container\s+(?:ls|inspect|logs|top|diff|port|stats)"
            r"|system\s+(?:df|info|events))"
            r"(?:\s+[^\s]+)*\s*\Z",
        ),
        "container_inspect",
    ),
    (
        re.compile(
            r"\Akubectl\s+"
            r"(?:get|describe|logs|top|version"
            r"|api-resources|api-versions|explain"
            r"|config\s+(?:view|get-contexts|current-context)"
            r"|cluster-info|auth\s+can-i)"
            r"(?:\s+[^\s]+)*\s*\Z",
        ),
        "container_inspect",
    ),
)


# ── Network-probe family ────────────────────────────────────────────
#
# These rules emit `capability:network_probe:*` tags.  They fire only
# when the command is structurally bare (single head, no indirection,
# no dynamic content, no composition) — same structural gate as the
# read-only family, minus the incompatible-prior-capability check.
#
# Unlike `read_only:*`, this family is NOT a fast-path license.  Every
# tag here says "this command emits outbound traffic", which is a
# policy-relevant side effect the consumer must evaluate (AE routing,
# domain allow-lists, sandbox rules, etc.).
#
# Rule ordering matters: `http_mutate` is checked before `http_get` /
# `http_download` so a POST/PUT/DELETE curl never gets a weaker tag.
# `http_download` is checked before `http_get` so `curl -o` writes
# don't masquerade as idempotent reads.

_NETWORK_PROBE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # ── icmp ────────────────────────────────────────────────────────
    # `ping` / `ping6` — ICMP echo.  Requires at least one arg (the
    # host); bare `ping` is interactive and rare.
    (
        re.compile(r"\Aping6?(?:\s+[^\s]+)+\s*\Z"),
        "icmp",
    ),

    # ── trace ───────────────────────────────────────────────────────
    # Hop-by-hop route discovery.
    (
        re.compile(
            r"\A(?:traceroute6?|tracepath6?|mtr)"
            r"(?:\s+[^\s]+)+\s*\Z",
        ),
        "trace",
    ),

    # ── dns ─────────────────────────────────────────────────────────
    # DNS query tools.  Idempotent at the DNS layer; no side effects
    # beyond a resolver cache hit.
    (
        re.compile(
            r"\A(?:dig|nslookup|host|drill|kdig)"
            r"(?:\s+[^\s]+)+\s*\Z",
        ),
        "dns",
    ),

    # ── whois ───────────────────────────────────────────────────────
    (
        re.compile(r"\Awhois(?:\s+[^\s]+)+\s*\Z"),
        "whois",
    ),

    # ── http_mutate ─────────────────────────────────────────────────
    # Checked BEFORE http_get / http_download so that a POST-ish curl
    # is never downgraded to a read tag.  Triggers: explicit non-safe
    # `-X` / `--request`, or any body/upload flag.
    (
        re.compile(
            r"\A(?:curl|xh)\b"
            r"(?=(?:.*\s)(?:"
            r"-X\s+(?:POST|PUT|DELETE|PATCH)"
            r"|--request(?:\s+|=)(?:POST|PUT|DELETE|PATCH)"
            r"|-d\b|--data\b|--data-raw\b|--data-binary\b"
            r"|--data-urlencode\b|--data-ascii\b|--json\b"
            r"|-F\b|--form\b|--form-string\b"
            r"|-T\b|--upload-file\b"
            r"))"
            r"(?:\s+[^\s]+)+\s*\Z",
        ),
        "http_mutate",
    ),
    # HTTPie / xh with an explicit non-safe HTTP verb positional
    # (`http POST example.com`) OR any body-field / form-upload token.
    # HTTPie request-item grammar reminders:
    #   name=value    JSON string body field  (mutate)
    #   name:=value   JSON non-string field   (mutate)
    #   name==value   query parameter         (NOT mutate)
    #   name:value    HTTP header             (NOT mutate)
    #   name@path     file upload (legacy)    (mutate)
    #   name=@path    file upload (modern)    (mutate)
    (
        re.compile(
            r"\A(?:http|https|xh)\b"
            r"(?=.*(?:"
            r"\s(?:POST|PUT|DELETE|PATCH)\b"
            r"|=@"
            r"|:="
            r"|\s(?:-f|--form)\b"
            r"|\s[A-Za-z_][\w.-]*=[^=\s]"
            r"))"
            r"(?:\s+[^\s]+)+\s*\Z",
        ),
        "http_mutate",
    ),
    # wget writing a body.
    (
        re.compile(
            r"\Awget\b"
            r"(?=(?:.*\s)(?:"
            r"--post-data\b|--post-file\b"
            r"|--method(?:\s+|=)(?:POST|PUT|DELETE|PATCH)"
            r"|--body-data\b|--body-file\b"
            r"))"
            r"(?:\s+[^\s]+)+\s*\Z",
        ),
        "http_mutate",
    ),

    # ── http_download ───────────────────────────────────────────────
    # `curl -o|-O|--output|--remote-name` persists response to disk.
    # Checked before `http_get` so disk writes aren't hidden.
    (
        re.compile(
            r"\Acurl\b"
            r"(?!(?:.*\s)(?:"
            r"-X\s+(?:POST|PUT|DELETE|PATCH)"
            r"|--request(?:\s+|=)(?:POST|PUT|DELETE|PATCH)"
            r"|-d\b|--data\b|--data-raw\b|--data-binary\b"
            r"|--data-urlencode\b|--data-ascii\b|--json\b"
            r"|-F\b|--form\b|--form-string\b"
            r"|-T\b|--upload-file\b"
            r"))"
            r"(?=(?:.*\s)(?:-o\b|-O\b|--output\b|--remote-name\b))"
            r"(?:\s+[^\s]+)+\s*\Z",
        ),
        "http_download",
    ),
    # wget default mode writes to disk (only `-O -` streams to stdout).
    (
        re.compile(
            r"\Awget\b"
            r"(?!(?:.*\s)(?:"
            r"-O\s+-"                        # stdout-stream form
            r"|--post-data\b|--post-file\b"  # or mutating body
            r"|--method(?:\s+|=)(?:POST|PUT|DELETE|PATCH)"
            r"|--body-data\b|--body-file\b"
            r"|--help\b|-h\b|--version\b|-V\b"
            r"))"
            r"(?:\s+[^\s]+)+\s*\Z",
        ),
        "http_download",
    ),

    # ── http_get ────────────────────────────────────────────────────
    # Idempotent HTTP with response to stdout.  Must survive all the
    # mutate / download lookaheads.  Also excludes `--help` / `-V`
    # so flag-only invocations aren't mis-tagged as probes.
    (
        re.compile(
            r"\Acurl\b"
            r"(?!(?:.*\s)(?:"
            r"-X\s+(?:POST|PUT|DELETE|PATCH)"
            r"|--request(?:\s+|=)(?:POST|PUT|DELETE|PATCH)"
            r"|-d\b|--data\b|--data-raw\b|--data-binary\b"
            r"|--data-urlencode\b|--data-ascii\b|--json\b"
            r"|-F\b|--form\b|--form-string\b"
            r"|-T\b|--upload-file\b"
            r"|-o\b|-O\b|--output\b|--remote-name\b"
            r"|--help\b|-h\b|--version\b|-V\b|--manual\b"
            r"))"
            r"(?:\s+[^\s]+)+\s*\Z",
        ),
        "http_get",
    ),
    # wget stdout-stream form only.
    (
        re.compile(
            r"\Awget\s+-O\s+-"
            r"(?:\s+[^\s]+)+\s*\Z",
        ),
        "http_get",
    ),
    # HTTPie / xh without mutation tokens.  Mirror-image of the
    # http_mutate rule: same lookahead body, inverted to a negative
    # assertion, plus exclusions for help / version flags.
    (
        re.compile(
            r"\A(?:http|https|xh)\b"
            r"(?!.*(?:"
            r"\s(?:POST|PUT|DELETE|PATCH)\b"
            r"|=@"
            r"|:="
            r"|\s(?:-f|--form)\b"
            r"|\s[A-Za-z_][\w.-]*=[^=\s]"
            r"|\s(?:--help|-h|--version)\b"
            r"))"
            r"(?:\s+[^\s]+)+\s*\Z",
        ),
        "http_get",
    ),

    # ── port_scan ───────────────────────────────────────────────────
    # TCP/UDP connect-mode scanning.  `nc -l` / `ncat -l` already get
    # tagged `capability:network_bind`; the lookahead prevents double-
    # tagging as port_scan.
    (
        re.compile(
            r"\A(?:nmap|masscan|zmap)"
            r"(?:\s+[^\s]+)+\s*\Z",
        ),
        "port_scan",
    ),
    (
        re.compile(
            r"\A(?:nc|ncat|netcat)"
            # Reject listen-mode forms: `-l` standalone, `-l` anywhere
            # inside a combined flag bundle (e.g. `-lk`, `-lnv`), or
            # the long `--listen` form.
            r"(?!(?:.*\s)(?:-[a-zA-Z]*l[a-zA-Z]*\b|--listen\b))"
            r"(?:\s+[^\s]+)+\s*\Z",
        ),
        "port_scan",
    ),

    # ── file_transfer ───────────────────────────────────────────────
    # Bulk file movement over the network.
    (
        re.compile(
            r"\A(?:scp|sftp)"
            r"(?:\s+[^\s]+)+\s*\Z",
        ),
        "file_transfer",
    ),
    # `rsync` — tagged only when a `[user@]host:` endpoint appears.
    # Local-only rsync (`rsync -av src/ dst/`) emits no network traffic
    # and is intentionally NOT tagged.
    (
        re.compile(
            r"\Arsync\b"
            r"(?=.*(?:\s|=)(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9.-]+:)"
            r"(?:\s+[^\s]+)+\s*\Z",
        ),
        "file_transfer",
    ),
    # `rclone` — narrow allowlist of sub-commands that touch remote
    # backends.  Purely-local rclone commands (`rclone config`,
    # `rclone version`, `rclone help`) are not tagged.
    (
        re.compile(
            r"\Arclone\s+"
            r"(?:copy|sync|move|copyto|moveto|copyurl|mount|serve"
            r"|cat|rcat|lsjson|ls|lsl|lsd|lsf|tree|size|md5sum|sha1sum"
            r"|check|cryptcheck|hashsum|ncdu|dedupe|cleanup|purge"
            r"|delete|deletefile|rmdir|rmdirs|touch)"
            r"(?:\s+[^\s]+)*\s*\Z",
        ),
        "file_transfer",
    ),
)


# Bare shell metacharacter tokens.  When any of these appears as a
# standalone token after re-tokenising the normalized command, we
# assume shell composition is present and skip read-only emission.
# (Quoted occurrences of these characters become part of a word, not
# a standalone token, so this check is quote-aware.)
_SHELL_COMPOSITION_TOKENS: frozenset[str] = frozenset({
    "|", "||", "&", "&&", ";", ";;",
    ">", ">>", "<", "<<", "<<<",
    "&>", "2>", "2>>", "|&",
})


# Structural signal IDs that indicate dynamic content — any of these
# disqualifies the command from a read-only fast-path because the
# actual execution shape cannot be decided statically.
_DYNAMIC_STRUCTURAL_IDS: frozenset[str] = frozenset({
    "command-substitution",
    "backtick-substitution",
    "process-substitution",
    "variable-expansion",
    "interpreter-indirection",
    "parse-failure",
    "shlex-failure",
})


def classify_capabilities(
    command: str,
    *,
    sub_commands: tuple[str, ...] = (),
    indirections: tuple[str, ...] = (),
    structural_signals: tuple[Signal, ...] = (),
) -> tuple[tuple[str, ...], tuple[Signal, ...]]:
    """Classify *command* into zero or more capability tags.

    Returns (capabilities, signals) where capabilities is a tuple of
    unique capability IDs and signals is the corresponding Signal list
    (one per distinct capability).  Scans the normalized command,
    sub-commands, and indirection payloads so hidden shells still pay
    their tax.

    ``structural_signals`` is optional context from step 4 — when
    supplied, it is used by the read-only gate to reject commands that
    already produced dynamic-content signals (command substitution,
    variable expansion, parse failure, …).  Omitting it simply makes
    the gate more conservative; it never falsely enables read-only.
    """
    if not command:
        return (), ()

    haystacks: list[str] = [command]
    haystacks.extend(sub_commands)
    haystacks.extend(indirections)

    seen: dict[str, Signal] = {}
    for rx, cap_id, desc in _RULES:
        for text in haystacks:
            m = rx.search(text)
            if m is None:
                continue
            if cap_id in seen:
                break
            seen[cap_id] = Signal(
                check="capability",
                signal_id=cap_id,
                description=desc,
                evidence=m.group()[:120],
            )
            break

    if _safe_for_read_only(
        command,
        sub_commands=sub_commands,
        indirections=indirections,
        structural_signals=structural_signals,
        emitted=seen,
    ):
        for rx, suffix in _READ_ONLY_RULES:
            m = rx.match(command)
            if m is None:
                continue
            cap_id = f"{CAPABILITY_READ_ONLY}:{suffix}"
            if cap_id in seen:
                continue
            seen[cap_id] = Signal(
                check="capability",
                signal_id=cap_id,
                description=(
                    f"Command is a bare read-only {suffix.replace('_', ' ')} "
                    f"invocation (no composition / redirect / indirection)"
                ),
                evidence=m.group()[:120],
            )

    if _safe_for_network_probe(
        command,
        sub_commands=sub_commands,
        indirections=indirections,
        structural_signals=structural_signals,
    ):
        # Walk rules in declaration order and emit only the FIRST
        # matching sub-tag for each of the three HTTP-family slots.
        # Outside the HTTP family every rule can fire independently
        # (e.g. `ping` + `traceroute` composed would hit two tags —
        # but the composition gate blocks it anyway).
        http_family_tagged = False
        for rx, suffix in _NETWORK_PROBE_RULES:
            is_http = suffix in {"http_get", "http_mutate", "http_download"}
            if is_http and http_family_tagged:
                continue
            m = rx.match(command)
            if m is None:
                continue
            cap_id = f"{CAPABILITY_NETWORK_PROBE}:{suffix}"
            if cap_id in seen:
                if is_http:
                    http_family_tagged = True
                continue
            seen[cap_id] = Signal(
                check="capability",
                signal_id=cap_id,
                description=(
                    f"Command emits outbound network traffic "
                    f"({suffix.replace('_', ' ')})"
                ),
                evidence=m.group()[:120],
            )
            if is_http:
                http_family_tagged = True

    capabilities = tuple(seen.keys())
    signals = tuple(seen.values())
    return capabilities, signals


def _structurally_bare(
    command: str,
    *,
    sub_commands: tuple[str, ...],
    indirections: tuple[str, ...],
    structural_signals: tuple[Signal, ...],
) -> bool:
    """Return True iff *command* is a single-head, no-indirection,
    no-dynamic-content, no-composition invocation.

    Shared prerequisite for every positive-fact capability family
    (`read_only:*`, `network_probe:*`).  The four invariants checked:

    1. No interpreter indirection payloads (`bash -c "..."`,
       `python -c ...`).
    2. bashlex sees exactly one sub-command (no pipes / sequences /
       `&&` / `||` chains).
    3. No dynamic structural signal (command substitution, process
       substitution, variable expansion, parse failure).
    4. No bare shell-composition or redirect tokens in the
       re-tokenised normalized command (robust to quoting — a literal
       `>` inside `grep "a>b"` stays inside the same shlex token and
       will not match `_SHELL_COMPOSITION_TOKENS`).
    """
    if indirections:
        return False
    if len(sub_commands) != 1:
        return False
    for sig in structural_signals:
        if sig.signal_id in _DYNAMIC_STRUCTURAL_IDS:
            return False

    try:
        toks = shlex.split(command)
    except ValueError:
        return False
    for tok in toks:
        if tok in _SHELL_COMPOSITION_TOKENS:
            return False

    return True


def _safe_for_read_only(
    command: str,
    *,
    sub_commands: tuple[str, ...],
    indirections: tuple[str, ...],
    structural_signals: tuple[Signal, ...],
    emitted: dict[str, Signal],
) -> bool:
    """Return True if *command* is safe to consider for read-only tagging.

    Combines the shared structural predicate (`_structurally_bare`)
    with a read-only-specific semantic predicate: no already-emitted
    "unsafe" capability.  Any already-emitted ``stdin_exec``,
    ``filesystem_write``, ``spawns_process``, ``network_bind``,
    ``background_exec``, ``download_and_exec``, ``binary_download``,
    ``process_signal``, ``compilation``, or any refined
    ``package_install:*`` / ``script_execution:*`` tag disqualifies
    the command from receiving any ``read_only:*`` tag.
    """
    if not _structurally_bare(
        command,
        sub_commands=sub_commands,
        indirections=indirections,
        structural_signals=structural_signals,
    ):
        return False

    for cap_id in emitted:
        # Any refined script_execution / package_install / read-only-
        # incompatible tag means this command is doing more than
        # passive inspection.
        if cap_id in {
            CAPABILITY_STDIN_EXEC,
            CAPABILITY_FILESYSTEM_WRITE,
            CAPABILITY_SPAWNS_PROCESS,
            CAPABILITY_NETWORK_BIND,
            CAPABILITY_BACKGROUND_EXEC,
            CAPABILITY_DOWNLOAD_AND_EXEC,
            CAPABILITY_BINARY_DOWNLOAD,
            CAPABILITY_PROCESS_SIGNAL,
            CAPABILITY_COMPILATION,
        }:
            return False
        if cap_id.startswith(f"{CAPABILITY_PACKAGE_INSTALL}:"):
            return False
        if cap_id.startswith(f"{CAPABILITY_SCRIPT_EXECUTION}:"):
            return False

    return True


def _safe_for_network_probe(
    command: str,
    *,
    sub_commands: tuple[str, ...],
    indirections: tuple[str, ...],
    structural_signals: tuple[Signal, ...],
) -> bool:
    """Return True if *command* is safe to consider for network-probe
    tagging.

    Uses the same structural predicate as read-only, minus the
    incompatible-prior-capability check — `network_probe:http_download`
    is permitted to co-exist with any filesystem-related capability,
    since the whole point of tagging it is to signal the co-occurrence
    of network + disk effects.
    """
    return _structurally_bare(
        command,
        sub_commands=sub_commands,
        indirections=indirections,
        structural_signals=structural_signals,
    )
