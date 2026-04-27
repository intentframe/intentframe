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

    capability:data_read:browser_cookies       — plutil / cat / cp / sqlite3 on
                                                  Safari / Chrome / Chromium /
                                                  Brave / Edge / Firefox / Vivaldi
                                                  / Arc cookie stores
    capability:data_read:auth_authority        — dscl reads of account
                                                  AuthenticationAuthority /
                                                  ShadowHashData / KerberosKeys /
                                                  Password / SMBPasswordServerList
    capability:data_read:credential_material   — security dump-keychain,
                                                  security find-*-password -w/-g,
                                                  sqlite3 / cp on TCC.db,
                                                  gpg --export-secret-keys /
                                                  --export-secret-subkeys /
                                                  --export-ownertrust, reads of
                                                  ~/.gnupg/private-keys-v1.d,
                                                  *.kdbx / *.agilekeychain /
                                                  *.opvault password vaults,
                                                  Bitwarden Group Container,
                                                  cp|mv|rsync|scp of ~/.ssh/id_*
    capability:data_read:shell_history         — .bash_history / .zsh_history /
                                                  .fish_history / .ksh_history /
                                                  .sh_history / .history /
                                                  .psql_history / .mysql_history
                                                  / .node_repl_history /
                                                  .python_history / .sqlite_history
                                                  / .rediscli_history / .lesshst
    capability:data_read:browser_profile_data  — Chrome/Chromium/Brave/Edge/
                                                  Vivaldi/Arc Login Data /
                                                  History / Web Data / Bookmarks
                                                  / Top Sites / Visited Links /
                                                  Network Action Predictor /
                                                  Shortcuts; Firefox
                                                  places.sqlite /
                                                  formhistory.sqlite /
                                                  logins.json / key*.db /
                                                  signons.sqlite /
                                                  permissions.sqlite
    capability:data_read:messaging_history     — iMessage chat.db / Attachments,
                                                  WhatsApp Group Container,
                                                  Messages Group Container,
                                                  Telegram Desktop, Signal,
                                                  Slack storage, Discord
    capability:data_read:personal_records      — AddressBook Application Support
                                                  / *.abcddb, Notes Group
                                                  Container / NoteStore.sqlite,
                                                  Mail V* stores, iOS MobileSync
                                                  Backup, *.photoslibrary,
                                                  *.calendar stores

    capability:system_mutate:host_network_config   — networksetup -set*/
                                                      -create*/-delete*/-add*/
                                                      -remove*/-switchtolocation;
                                                      arp -s|-d; route add|del|
                                                      change|replace|flush;
                                                      ip <obj> add|del|...;
                                                      ifconfig <if> up|down|mtu|ip
    capability:system_mutate:hostname              — scutil --set HostName /
                                                      LocalHostName / ComputerName;
                                                      hostname <new>
    capability:system_mutate:time_sync             — systemsetup -setusingnetwork
                                                      time / -setnetworktimeserver
                                                      / -settimezone / -settime /
                                                      -setdate; sntp -S
    capability:system_mutate:security_daemon       — launchctl unload|bootout|
                                                      disable|remove|stop|
                                                      kickstart -k targeting
                                                      EDR / TCC / Santa / osquery
                                                      / Jamf / Kandji;
                                                      spctl --master-disable;
                                                      csrutil disable
    capability:system_mutate:browser_security_pref — defaults write on
                                                      com.apple.Safari /
                                                      com.google.Chrome /
                                                      org.mozilla.firefox
    capability:system_mutate:firewall              — pfctl -d|-e|-f|-F;
                                                      ip[6]tables / iptables-
                                                      save / iptables-restore /
                                                      iptables-legacy
                                                      -F|-X|-Z|-D|-I|-A|-N|-E|
                                                      -P <chain> ACCEPT|DROP|
                                                      REJECT|QUEUE;
                                                      nft flush|delete|add|
                                                      insert|replace|create|
                                                      rename; ufw disable|enable
                                                      |reset|default|allow|deny
                                                      |reject|limit|delete|
                                                      insert; firewall-cmd
                                                      --add/remove/change/set-*
                                                      / --panic-on/-off /
                                                      --reload; socketfilterfw
                                                      --setglobalstate /
                                                      --setallowsigned(app) /
                                                      --setloggingmode /
                                                      --setblockall /
                                                      --setstealthmode /
                                                      --unblockapp / --blockapp;
                                                      ipfw add|delete|flush|
                                                      zero|resetlog|disable|
                                                      enable
    capability:system_mutate:hosts_file            — redirect / tee / cp / mv /
                                                      install / ln / sed -i /
                                                      python|perl|ruby|awk write
                                                      shapes that land at
                                                      /etc/hosts
    capability:system_mutate:privilege_config      — visudo (not ``-c``);
                                                      redirect / tee / cp / mv /
                                                      install / ln / sed -i
                                                      targeting /etc/sudoers,
                                                      /etc/sudoers.d/<file>,
                                                      /etc/passwd, /etc/shadow,
                                                      /etc/gshadow, /etc/group,
                                                      /etc/pam.d/<file>
    capability:system_mutate:user_account          — dseditgroup -o edit|create|
                                                      delete; pwpolicy -set*/
                                                      -clear*/-resetpolicy/
                                                      -disableuser/-enableuser;
                                                      dscl . -passwd|-delete|
                                                      -append|-merge|-change|
                                                      -create; sysadminctl
                                                      -addUser|-deleteUser|
                                                      -resetPasswordFor|
                                                      -secureTokenOn/-Off|
                                                      -newPassword|-adminUser|
                                                      -*GuestAccess|
                                                      -guestAccount|-filesystem;
                                                      Linux useradd|usermod|
                                                      userdel|adduser|deluser|
                                                      groupadd|groupmod|
                                                      groupdel|addgroup|
                                                      delgroup|chpasswd|
                                                      newusers;
                                                      passwd <other-user>
    capability:system_mutate:remote_access         — systemsetup
                                                      -setremotelogin /
                                                      -setremoteappleevents /
                                                      -setwakeonnetworkaccess /
                                                      -setwakeonmodem /
                                                      -setcomputersleep /
                                                      -setdisplaysleep /
                                                      -setharddisksleep /
                                                      -setrestartfreeze /
                                                      -setrestartpoweron /
                                                      -setallowpowerbuttontosleep
                                                      computer / -setstartupdisk
                                                      / -setdisableloginchime
    capability:system_mutate:disk_encryption       — fdesetup enable|disable|
                                                      add|remove|changerecovery
                                                      |sync|authrestart
    capability:system_mutate:kernel_tunable        — sysctl -w / sysctl -p /
                                                      sysctl <name>=<value>;
                                                      redirect or tee into
                                                      /proc/sys/<path>
    capability:system_mutate:persistence           — at noon|midnight|teatime|
                                                      today|tomorrow|<HH[:MM]>
                                                      [am|pm]|now|+|-f; osascript
                                                      involving ``System Events``
                                                      + ``login item`` or ``make
                                                      [new] login item``

Each hit produces a Signal with check="capability" and signal_id set to
the capability tag.  Multiple capabilities per command are expected;
they are not mutually exclusive.  Policy can match exact tags or use
prefix matching on the `:` boundary (e.g. `capability:package_install:*`).

`capability:read_only:*` is a positive fact family. It fires on two
shapes:

1. **Single-head** — the command is structurally a bare single-head
   invocation (bashlex reports exactly one sub-command, no interpreter
   indirection, no shell composition / redirect tokens).  The specific
   sub-tag corresponding to the head's family is emitted
   (``filesystem_list``, ``filesystem_read``, ``search``, …).  The
   head may be either a bare name (``ls``) or an absolute path under a
   trusted system bin directory (``/bin/ls``, ``/usr/bin/cat``,
   ``/opt/homebrew/bin/rg``) — see ``_TRUSTED_BIN_DIRS``.  Path-prefixed
   heads under user-writable directories (``/tmp/ls``, ``./ls``,
   ``~/bin/ls``) stay rejected; spoofing is credible there.

2. **Composition** — the command is a multi-segment composition joined
   by ``|``, ``||``, ``&&``, ``;``, or ``|&`` where every segment is
   independently either a read-only head (same rule set as single-head)
   or a safe ``cd <literal>``, no redirect tokens are present, no
   incompatible capability was emitted anywhere in the command, and no
   dynamic-content structural signal fired.  A single aggregate tag
   ``capability:read_only:composition`` is emitted — specific family
   sub-tags are *not* emitted for pipelines, since the composition's
   effect is the pipe-joined whole, not any one segment.

Consumers — notably the intentframe-side deterministic Guardian — use
the combination ``verdict == SAFE`` + at least one
``capability:read_only:*`` + no deny-listed capabilities + no
edge/code-intel signals as a fast-path ALLOW rule that skips the AE
LLM call.  Because all sub-tags share the ``capability:read_only:``
prefix, a consumer that prefix-matches the family picks up
``composition`` automatically; a consumer that wants stricter control
can list the accepted sub-tags explicitly.  The tag still does not
change the verdict — that stability guarantee is preserved.

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
# ── Sensitive surface families (refined-only) ────────────────────────
# Both are emitted only as ``<base>:<suffix>`` refined tags — the bare
# base form is never seen on a command.  Consumers MUST prefix-match
# these families (literal equality against ``capability:data_read`` /
# ``capability:system_mutate`` will never fire).
#
#   * ``capability:data_read:*`` — reads that yield information an
#     agent must not exfiltrate under the root-compromised-agent threat
#     model.  Today's suffixes cover browser cookies (``browser_cookies``),
#     macOS Directory-Services account records (``auth_authority``),
#     keychain / TCC.db / GPG secret-key / password-manager vault
#     contents (``credential_material``), shell-history stores
#     (``shell_history``), browser saved-login / history / bookmark /
#     form-autofill data beyond cookies (``browser_profile_data``),
#     messaging-client on-disk histories (``messaging_history``), and
#     high-PII personal stores — Contacts, Notes, Mail, Photos,
#     Calendar, iOS backup (``personal_records``).  Structurally these
#     commands are read-shaped, so this family is treated as read-only-
#     incompatible in the classifier gate (``_safe_for_read_only``):
#     emitting ``data_read:*`` suppresses ``read_only:*`` on the same
#     command so the consumer fast-path license is not accidentally
#     available for a sensitive read.
#
#   * ``capability:system_mutate:*`` — commands that change host /
#     network / identity / trust-surface state.  Today's suffixes cover
#     routing and interface config (``host_network_config``), hostname
#     (``hostname``), NTP / clock (``time_sync``), launchd jobs for
#     EDR / TCC / security daemons plus the macOS trust-disable shapes
#     (``security_daemon``), browser security preferences
#     (``browser_security_pref``), packet-filter / firewall mutations
#     (``firewall``), DNS-hijack writes to /etc/hosts (``hosts_file``),
#     sudoers / pam.d / passwd / shadow / group / gshadow writes
#     (``privilege_config``), user-and-group account mutation verbs
#     (``user_account``), systemsetup remote-access and power toggles
#     (``remote_access``), FileVault encryption toggles
#     (``disk_encryption``), kernel tunable writes (``kernel_tunable``),
#     and ``at`` / AppleScript login-item persistence shapes not
#     already pattern-catastrophic (``persistence``).  Structurally
#     these are mutating and so would not qualify for ``read_only:*``
#     on their own; the read-only-incompatible membership is belt-and-
#     braces against an unanticipated co-occurrence.
CAPABILITY_DATA_READ = "capability:data_read"
CAPABILITY_SYSTEM_MUTATE = "capability:system_mutate"


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

# Refined rules: one per interpreter.
#
# File-form rules require an explicit script file (or `-jar` / `run`
# verb) as proof the command is execution-shaped rather than help/
# version/REPL.  Inline-form rules (`-e`, `-r`, `--eval`) are
# enumerated for every interpreter EXCEPT python/shell, which the
# python+shell-only profile is meant to allow.  Adding a python
# inline tag here would force every `_safe_for_read_only` consumer
# to deal with `python -c` showing up as a script_execution
# capability — out of scope for this change.
# Stdin-piped execution into an interpreter, refined by interpreter family.
# Mirror the per-interpreter shape of ``_SCRIPT_EXECUTION_RULES`` so policy
# layers can deny ``capability:stdin_exec:node`` while still allowing
# ``capability:stdin_exec:python`` (e.g. python+shell-only profiles).
#
# These rules are emitted IN ADDITION to the binary ``CAPABILITY_STDIN_EXEC``
# tag below; ``_READ_ONLY_INCOMPATIBLE_CAPS`` keys off the binary tag, so
# read-only fast-path semantics are preserved unchanged.  Suffixes mirror
# ``_SCRIPT_EXECUTION_RULES`` (``shell`` collapses bash/sh/zsh/dash/ksh/ash
# the same way).
#
# The lookahead ``(?=\s|$|\||;|&)`` after the optional ``-`` prevents
# false matches against tokens that merely *start* with an interpreter
# name (``| nodejs-utility``, ``| sharp``).  ``python3?|python2`` is
# split into its own rule because the suffix is uniformly ``python``.
_STDIN_EXEC_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\|\s*python(?:3|2)?(?:\s+-)?(?=\s|$|\||;|&)"), "python"),
    (re.compile(r"\|\s*node(?:js)?(?:\s+-)?(?=\s|$|\||;|&)"), "node"),
    (re.compile(r"\|\s*ruby(?:\s+-)?(?=\s|$|\||;|&)"), "ruby"),
    (re.compile(r"\|\s*perl(?:\s+-)?(?=\s|$|\||;|&)"), "perl"),
    # `php` reads from stdin in CLI mode (`cat foo.php | php`); the
    # ``-r`` and ``-f -`` shapes are also covered structurally because
    # the optional ``\s+-`` accepts ``php -``.
    (re.compile(r"\|\s*php(?:\s+-)?(?=\s|$|\||;|&)"), "php"),
    (
        re.compile(r"\|\s*(?:bash|sh|zsh|dash|ksh|ash)(?:\s+-)?(?=\s|$|\||;|&)"),
        "shell",
    ),
)


_SCRIPT_EXECUTION_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bpython3?\s+[^|;&]*\.py\b"), "python"),
    (re.compile(r"\bnode\s+[^|;&]*\.(?:js|mjs|cjs|ts)\b"), "node"),
    (re.compile(r"\bruby\s+[^|;&]*\.rb\b"), "ruby"),
    (re.compile(r"\bperl\s+[^|;&]*\.pl\b"), "perl"),
    (re.compile(r"\b(?:bash|sh|zsh|ksh|dash)\s+[^|;&]*\.(?:sh|bash|zsh)\b"), "shell"),
    (re.compile(r"(?:^|[\s;&|])\./[\w.][\w./-]*"), "local_binary"),
    # ── long-tail interpreters: file-form ───────────────────────────
    # `java -jar foo.jar` / `java -cp ... Main` / `java Foo.class`.
    # The `-jar` flag is the canonical run form; `Foo.class` direct
    # exec is rare but covered by the second alternative.
    (re.compile(r"\bjava\s+(?:[^|;&]*\s)?-jar\b"), "java"),
    (re.compile(r"\bjava\s+[^|;&]*\.(?:class|jar)\b"), "java"),
    # `go run main.go` — distinct from `go build` (compilation) and
    # `go install` (package_install).
    (re.compile(r"\bgo\s+run\b"), "go"),
    # `dotnet foo.dll` — the .NET host running a managed assembly.
    (re.compile(r"\bdotnet\s+[^|;&]*\.dll\b"), "dotnet"),
    # `php foo.php` — file-mode interpretation.
    (re.compile(r"\bphp\s+[^|;&]*\.php\b"), "php"),
    # `lua foo.lua`.
    (re.compile(r"\blua\s+[^|;&]*\.lua\b"), "lua"),
    # `Rscript foo.R` / `.r`.
    (re.compile(r"\bRscript\s+[^|;&]*\.[Rr]\b"), "r"),
    # `julia foo.jl`.
    (re.compile(r"\bjulia\s+[^|;&]*\.jl\b"), "julia"),
    # `swift run` (package mode) or `swift script.swift`.
    (re.compile(r"\bswift\s+(?:run\b|[^|;&]*\.swift\b)"), "swift"),
    # Deno / Bun share a single suffix; both are JS/TS runtimes whose
    # `run`/`test` verbs execute a script.
    (re.compile(r"\b(?:deno|bun)\s+(?:run|test)\b"), "deno_bun"),
    # ── long-tail interpreters: inline-eval form ─────────────────────
    # These mirror file-form rules above.  Each catches an inline
    # body so policies that deny `script_execution:<lang>` reject
    # both `node app.js` and `node -e '...'`.
    (re.compile(r"\bnode\s+(?:-e|--eval)\b"), "node"),
    (re.compile(r"\bruby\s+-e\b"), "ruby"),
    (re.compile(r"\bperl\s+-e\b"), "perl"),
    (re.compile(r"\bphp\s+-r\b"), "php"),
    # `awk 'BEGIN{...}'` / `awk -f script.awk` — both shapes are
    # AWK-language execution.  The classifier's haystack is the
    # shlex-normalised command (quotes already stripped), so we
    # cannot anchor on `'`.  Instead we accept any awk invocation
    # that has a non-flag positional argument; `awk --version` /
    # `awk -h` (no positional) stay untagged.  `gawk` / `mawk` get
    # the same suffix so policy can deny the family with one tag.
    (
        re.compile(
            r"\b(?:awk|gawk|mawk)\b"
            r"(?:\s+-[a-zA-Z][^\s]*)*"
            r"\s+(?!--?(?:help|version|h|V)\b)\S",
        ),
        "awk",
    ),
)


# Sensitive-data-read refined rules — one per data class.  Emission is
# driven purely by the main ``_RULES`` loop (no structural-bareness gate),
# since the point of the family is to tag the command regardless of shape;
# a policy that denies ``capability:data_read:browser_cookies`` wants the
# deny to fire whether the command is bare, composed, or hidden behind
# an indirection.  Multiple rules may share a suffix — the first one to
# match adds the tag, subsequent rules with the same suffix are skipped
# by the main classification loop (``if cap_id in seen``).
_DATA_READ_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # Browser cookies on macOS — Safari on-disk store + Chromium-family
    # profile cookies + Firefox SQLite cookie store.  shlex normalisation
    # collapses `Application\ Support` to `Application Support`, so we
    # accept `\s+` between the two words.  Path segments are bounded by
    # `[^\s|;&]+` to keep the match inside a single shlex token and out
    # of shell metacharacters.
    (
        re.compile(
            r"(?:^|[^A-Za-z0-9_])(?:/)?Library/Cookies/"
            r"|\bCookies\.binarycookies\b"
            r"|\bApplication\s+Support/"
            r"(?:Google/Chrome|Chromium|BraveSoftware|Vivaldi|Arc|"
            r"Microsoft\s+Edge)[^\s|;&]*/Cookies\b"
            r"|\bFirefox/Profiles/[^\s/|;&]+/cookies\.sqlite\b"
        ),
        "browser_cookies",
    ),
    # Directory-Services account records — the macOS local-identity
    # plumbing.  ``AuthenticationAuthority``, ``ShadowHashData``,
    # ``KerberosKeys`` are the credential-bearing fields; ``Password``
    # is included because dscl exposes the field name literally and
    # ``\bPassword\b`` will not match substrings like ``Passwordless``
    # (both chars are word chars so there's no boundary).
    (
        re.compile(
            r"\bdscl\b[^|;&]*\b(?:AuthenticationAuthority|ShadowHashData"
            r"|KerberosKeys|Password|SMBPasswordServerList)\b"
        ),
        "auth_authority",
    ),
    # Credential-material reads — pattern layer already catches the
    # common catastrophic shapes (``security dump-keychain``,
    # ``security find-generic-password -w``, ``sqlite3 … TCC.db``)
    # via MAC-KEY-002 / MAC-KEY-003 / MAC-PRIV-001; keeping these
    # alternatives here is belt-and-braces so a future pattern-set
    # change that drops any of them does not silently lose the tag.
    (
        re.compile(
            r"\bsecurity\s+dump-keychain\b"
            r"|\bsecurity\s+find-(?:generic|internet)-password\b"
            r"[^|;&]*\s-[wg]\b"
            r"|\bsqlite3\b[^|;&]*\bTCC\.db\b"
            r"|\bcp\b[^|;&]*\bTCC\.db\b"
        ),
        "credential_material",
    ),
    # Credential-material (extension) — GPG secret-key export verbs,
    # the GnuPG private-key directory itself, cleartext password-
    # manager database files (KeePass, 1Password legacy vaults,
    # Bitwarden exports), and ``cp|mv|rsync|scp`` of ``~/.ssh/id_*``
    # (the direct *read* of ``id_rsa`` etc. is already pattern-
    # catastrophic via CAT-SSHKEY-*; we tag the *copy* shape so
    # "stage then exfil via a second command" is visible to policy).
    (
        re.compile(
            r"\bgpg\s+[^|;&]*--export-secret-(?:keys?|subkeys?)\b"
            r"|\bgpg\s+--export-ownertrust\b"
            r"|(?<![\w.])\.gnupg/private-keys-v1\.d\b"
            r"|\b[^\s|;&]*\.kdbx\b"
            r"|\b[^\s|;&]*\.agilekeychain\b"
            r"|\b[^\s|;&]*\.opvault\b"
            r"|\bLibrary/Group\s+Containers/group\.com\.bitwarden\b"
            r"|\b(?:cp|mv|rsync|scp)\b[^|;&]*\s~?/?\.ssh/"
            r"(?:id_[A-Za-z0-9_]+|identity)\b"
        ),
        "credential_material",
    ),
    # Shell history files — may contain pasted secrets, API keys,
    # typo'd passwords.  Lookbehind ``(?<![\w.])`` prevents matches
    # inside larger identifiers (``foo.bash_history_x``) while still
    # firing when the path starts with ``/`` or ``~/`` or a space.
    (
        re.compile(
            r"(?<![\w.])\.(?:bash|zsh|fish|ksh|sh)_history\b"
            r"|(?<![\w.])\.history\b"
            r"|(?<![\w.])\.psql_history\b"
            r"|(?<![\w.])\.mysql_history\b"
            r"|(?<![\w.])\.node_repl_history\b"
            r"|(?<![\w.])\.python_history\b"
            r"|(?<![\w.])\.sqlite_history\b"
            r"|(?<![\w.])\.rediscli_history\b"
            r"|(?<![\w.])\.lesshst\b"
        ),
        "shell_history",
    ),
    # Browser saved-login / saved-form / browsing-history / bookmark
    # stores — everything beyond ``cookies`` that lives under a
    # Chromium-family or Firefox profile directory.  Chromium
    # profiles: ``Login Data`` (saved passwords, encrypted with OS
    # keychain but still sensitive), ``History`` (URL + visit times),
    # ``Web Data`` (form autofill incl. card numbers), ``Bookmarks``,
    # ``Top Sites``, ``Visited Links``.  Firefox profiles:
    # ``places.sqlite`` (bookmarks + history), ``formhistory.sqlite``
    # (autofill), ``logins.json`` + ``key*.db`` (saved passwords).
    # The outer ``[^\s|;&]*?`` non-greedy segment spans the profile-
    # name token (e.g. ``Default``, ``Profile 1``) without crossing
    # shell metacharacters.
    (
        re.compile(
            r"/(?:Google/Chrome|Chromium|BraveSoftware|"
            r"Microsoft\s+Edge|Vivaldi|Arc)"
            r"[^|;&]*?/(?:Login\s+Data|History|Web\s+Data|Bookmarks|"
            r"Top\s+Sites|Visited\s+Links|Network\s+Action\s+Predictor|"
            r"Shortcuts)\b"
            r"|/Firefox/Profiles/[^\s/|;&]+/"
            r"(?:places\.sqlite|formhistory\.sqlite|logins\.json"
            r"|key\d*\.db|signons\.sqlite|permissions\.sqlite)\b"
        ),
        "browser_profile_data",
    ),
    # Messaging histories — on-disk databases and container
    # directories for the major macOS messaging clients.  iMessage
    # lives at ``~/Library/Messages/chat.db``; WhatsApp / Signal /
    # Telegram / Slack / Discord use Group Containers or per-app
    # Application Support trees.  Matching by container / DB name
    # so any ``cat|cp|sqlite3|ls`` over the path fires the tag.
    (
        re.compile(
            r"\bLibrary/Messages/(?:chat\.db|Attachments)\b"
            r"|\bLibrary/Group\s+Containers/group\.net\.whatsapp\b"
            r"|\bLibrary/Group\s+Containers/group\.com\.apple\.Messages\b"
            r"|\bLibrary/Application\s+Support/Telegram\s+Desktop\b"
            r"|\bLibrary/Application\s+Support/Signal\b"
            r"|\bLibrary/Application\s+Support/Slack/storage\b"
            r"|\bLibrary/Application\s+Support/discord\b"
        ),
        "messaging_history",
    ),
    # Personal records — Contacts, Notes, Mail, Photos, Calendar,
    # iOS backup.  Not "credentials" but high-PII under the root-
    # compromised-agent threat model: one root shell yields every
    # contact, private note, saved photo, and calendared meeting.
    (
        re.compile(
            r"\bLibrary/Application\s+Support/AddressBook\b"
            r"|\bAddressBook[^\s|;&]*\.abcddb\b"
            r"|\bLibrary/Group\s+Containers/group\.com\.apple\.notes\b"
            r"|\bNoteStore\.sqlite\b"
            r"|\bLibrary/Mail/V\d+\b"
            r"|\bLibrary/Group\s+Containers/group\.com\.apple\.mail\b"
            r"|\bLibrary/Application\s+Support/MobileSync/Backup\b"
            r"|\.photoslibrary\b"
            r"|\bLibrary/Calendars/[^\s|;&]*\.calendar\b"
        ),
        "personal_records",
    ),
)


# System-mutation refined rules — one per surface.  Each regex matches
# only the mutating verbs/flags; the existing read-only ``arp`` /
# ``route`` / ``ip`` rules (which explicitly exclude ``-s|-d`` and
# ``add|del|change|replace|flush``) stay intact, so the same tool can
# still be tagged ``read_only:network_inspect`` in its inspection form
# and ``system_mutate:host_network_config`` in its mutation form.
_SYSTEM_MUTATE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # Host network configuration — macOS ``networksetup`` + the POSIX
    # ``arp`` / ``route`` / ``ip`` / ``ifconfig`` mutation verbs.
    # ``networksetup -get*`` / ``-list*`` stay untagged (read forms).
    # ``route`` accepts intervening short flags (``route -n flush``,
    # ``route -T 254 add …``) before the verb.  ``ip <obj> set`` is
    # iproute2's mutation verb for ``ip link set <dev> up|down`` — no
    # ``set`` sub-verb exists on ``ip route`` / ``ip neigh`` but it's
    # harmless to accept it uniformly since ``ip route set`` is not a
    # real command.  ``ifconfig <iface> <ip>`` matches on a dotted-quad
    # second token; bare ``ifconfig`` / ``ifconfig en0`` stay at
    # ``read_only:network_inspect``.
    (
        re.compile(
            r"\bnetworksetup\s+-(?:set[A-Za-z]+|create[A-Za-z]+"
            r"|delete[A-Za-z]+|add[A-Za-z]+|remove[A-Za-z]+"
            r"|switchtolocation)\b"
            r"|\barp\s+(?:[^|;&]*\s)?-[sd]\b"
            r"|\broute\s+(?:-[A-Za-z]+(?:\s+\S+)?\s+)*"
            r"(?:add|del|delete|change|replace|flush)\b"
            r"|\bip\s+(?:addr|address|link|route|neigh|neighbour|rule"
            r"|tunnel|netns|xfrm)\s+(?:add|del|delete|change|replace"
            r"|flush|set)\b"
            r"|\bifconfig\s+\S+\s+(?:up|down|mtu|\d+\.\d+\.\d+\.\d+)\b"
        ),
        "host_network_config",
    ),
    # Host identity — the three scutil hostname slots and the
    # ``hostname <new>`` shell builtin.  ``hostname`` bare / with flags
    # stays at ``read_only:system_info``; the non-dash positional
    # alternative catches the mutation shape.
    (
        re.compile(
            r"\bscutil\s+--set\s+(?:HostName|LocalHostName|ComputerName)\b"
            r"|\bhostname\s+[A-Za-z0-9][^\s]*"
        ),
        "hostname",
    ),
    # Time sync / NTP.  ``systemsetup -setusingnetworktime`` is the
    # failing-intent shape (root-demo intent 91); sibling surfaces are
    # included so policy can deny the whole family with one tag.
    # Alternation order (``timezone`` before ``time``) ensures the
    # longer match wins via backtracking on the trailing ``\b``.
    (
        re.compile(
            r"\bsystemsetup\s+-set(?:usingnetworktime|networktimeserver"
            r"|timezone|time|date)\b"
            r"|\bsntp\s+-S\b"
        ),
        "time_sync",
    ),
    # Security daemons / trust surfaces.  Matches the mutation verb +
    # a known security-product name (EDR, TCC, Santa, osquery, Jamf,
    # Kandji) for launchctl; plus the two macOS trust-disable shapes
    # (``spctl --master-disable`` / ``csrutil disable``) that any
    # sibling deny surface would ride with.
    (
        re.compile(
            r"\blaunchctl\s+(?:unload|bootout|disable|remove|stop"
            r"|kickstart\s+-k)\b[^|;&]*\b"
            r"(?:crowdstrike|falcond|sentinelone|sophos|mcafee|defender"
            r"|tccd|santa|osquery|jamf|kandji|com\.apple\.tcc"
            r"|com\.apple\.sandboxd)\b"
            r"|\bspctl\s+--master-disable\b"
            r"|\bcsrutil\s+disable\b"
        ),
        "security_daemon",
    ),
    # Browser security preferences.  ``defaults write`` to the three
    # major browser bundle ids.  Broad on purpose — any write to a
    # browser bundle's preferences is policy-relevant; narrowing to
    # specific preference keys would force the classifier to track
    # every rename Apple / Google / Mozilla ships.
    (
        re.compile(
            r"\bdefaults\s+write\s+"
            r"(?:com\.apple\.Safari(?:TechnologyPreview)?"
            r"|com\.google\.Chrome"
            r"|org\.mozilla\.firefox)"
            r"\b"
        ),
        "browser_security_pref",
    ),
    # Firewall / packet-filter mutations.  Covers macOS ``pfctl``
    # (``-d`` disable, ``-e`` enable, ``-f`` load rules file, ``-F``
    # flush), Linux ``ip[6]tables`` / ``iptables-restore`` /
    # ``iptables-legacy`` (``-F|-X|-Z|-D|-I|-A|-N|-E|-P`` mutation
    # verbs), nftables (``nft flush|delete|add|insert|replace|
    # create|rename``), the distro-neutral ``ufw``, RHEL's
    # ``firewall-cmd`` write verbs, macOS Application Firewall
    # ``socketfilterfw --set* / --block* / --unblock*``, and
    # FreeBSD ``ipfw``.  Read forms (``-s``, ``-L``, ``-S``,
    # ``list``, ``status``, ``--list-all``, ``--getglobalstate``)
    # stay outside every alternation and remain untagged.
    (
        re.compile(
            r"\bpfctl\s+(?:-[a-zA-Z]+\s+)*-[dfeF]\b"
            r"|\bip6?tables-restore\b"
            r"|\bip6?tables(?:-legacy)?\s+"
            r"(?:-[a-zA-Z]+\s+)*"
            r"(?:-F|-X|-Z|-D|-I|-A|-N|-E|"
            r"-P\s+\S+\s+(?:ACCEPT|DROP|REJECT|QUEUE))\b"
            r"|\bnft\s+(?:flush|delete|add|insert|replace|create|rename)\b"
            r"|\bufw\s+(?:disable|enable|reset|default|allow|deny|"
            r"reject|limit|delete|insert)\b"
            r"|\bfirewall-cmd\s+(?:--(?:add|remove|change|set)-"
            r"[a-zA-Z-]+|--panic-on|--panic-off|--reload|"
            r"--complete-reload|--runtime-to-permanent)\b"
            r"|\bsocketfilterfw\s+--(?:setglobalstate|setallowsigned"
            r"(?:app)?|setloggingmode|setblockall|setstealthmode|"
            r"unblockapp|blockapp|add|remove)\b"
            r"|\bipfw\s+(?:add|delete|flush|zero|resetlog|disable|enable)\b"
        ),
        "firewall",
    ),
    # /etc/hosts mutations — the classic DNS hijack surface.
    # Deliberately narrow to write shapes that actually land at
    # ``/etc/hosts``: redirect, tee, cp/mv/install/ln, sed -i,
    # or any interpreter argument.  ``filesystem_write`` also
    # fires on redirect writes, but ``hosts_file`` is the policy
    # hook that says "…and the target is /etc/hosts specifically".
    (
        re.compile(
            r"(?:^|[\s;&|])(?:>>?|&>|2>>?)\s*/etc/hosts\b"
            r"|\btee\s+(?:-[a-zA-Z]+\s+)*/etc/hosts\b"
            r"|\b(?:cp|mv|install|ln)\b[^|;&]*\s+/etc/hosts\b"
            r"|\bsed\s+[^|;&]*-i\b[^|;&]*\s+/etc/hosts\b"
            r"|\b(?:python3?|perl|ruby|awk)\b[^|;&]*/etc/hosts\b"
        ),
        "hosts_file",
    ),
    # Privilege config files — the system-ACL surface.
    # ``visudo`` opens /etc/sudoers for edit; ``visudo -c`` is the
    # syntax-check read form and stays untagged via negative
    # lookahead.  Direct redirects / tees / copies / in-place seds
    # on /etc/sudoers{,.d/<file>}, /etc/passwd, /etc/shadow,
    # /etc/gshadow, /etc/group, or /etc/pam.d/<file> all fire.
    # ``chmod 777 /etc/shadow`` is already pattern-catastrophic
    # via SYSD-001 and never reaches the classifier; other chmods
    # on the same files go through ``filesystem_write`` plus this
    # tag via the cp/mv/install/ln alternation in many shapes.
    (
        re.compile(
            r"\bvisudo\b(?!\s+-c)"
            r"|(?:^|[\s;&|])(?:>>?|&>|2>>?)\s*/etc/"
            r"(?:sudoers(?:\.d/[^\s|;&]*)?|passwd|shadow|gshadow|"
            r"group|pam\.d/[^\s|;&]*)\b"
            r"|\btee\s+(?:-[a-zA-Z]+\s+)*/etc/"
            r"(?:sudoers(?:\.d/[^\s|;&]*)?|passwd|shadow|gshadow|"
            r"group|pam\.d/[^\s|;&]*)\b"
            r"|\b(?:cp|mv|install|ln)\b[^|;&]*\s+/etc/"
            r"(?:sudoers(?:\.d/?[^\s|;&]*)?|passwd|shadow|gshadow|"
            r"group|pam\.d/?[^\s|;&]*)\b"
            r"|\bsed\s+[^|;&]*-i\b[^|;&]*\s+/etc/"
            r"(?:sudoers|passwd|shadow|gshadow|group)\b"
        ),
        "privilege_config",
    ),
    # User / group account mutation surfaces across macOS and Linux.
    # macOS: ``dseditgroup -o edit|create|delete``, ``pwpolicy
    # -set*|-clear*|-resetpolicy|-disableuser|-enableuser``,
    # ``dscl . -passwd|-delete|-append|-merge|-change|-create``
    # (the first four are already pattern-catastrophic via
    # IF-DSCL-ACCOUNT-001 / MAC-DS-001; kept here for belt-and-
    # braces), ``sysadminctl -addUser|-deleteUser|-resetPassword*|
    # -secureTokenOn|-secureTokenOff|-newPassword|-adminUser``.
    # Linux: the full ``useradd|usermod|userdel|adduser|deluser|
    # groupadd|groupmod|groupdel|addgroup|delgroup|chpasswd|
    # newusers`` family.  Finally ``passwd <other-user>`` is the
    # mutation shape — plain ``passwd`` (no args) is an own-
    # password interactive prompt which we intentionally leave
    # untagged; an attacker with root already has easier routes.
    (
        re.compile(
            r"\bdseditgroup\b[^|;&]*-o\s+(?:edit|create|delete)\b"
            r"|\bpwpolicy\b[^|;&]*-(?:setpolicy|setaccountpolicies|"
            r"clearaccountpolicies|setglobalpolicy|resetpolicy|"
            r"disableuser|enableuser)\b"
            r"|\bdscl\b[^|;&]*\s-(?:passwd|delete|append|merge|change|"
            r"create)\b"
            r"|\bsysadminctl\b[^|;&]*-(?:addUser|deleteUser|"
            r"resetPasswordFor|secureTokenOn|secureTokenOff|newPassword|"
            r"adminUser|afpGuestAccess|smbGuestAccess|guestAccount|"
            r"filesystem)\b"
            r"|\b(?:useradd|usermod|userdel|adduser|deluser|groupadd|"
            r"groupmod|groupdel|addgroup|delgroup|chpasswd|newusers)\b"
            # ``passwd <other-user>`` — mutation.  Require the verb to
            # sit at command-start position (either at the beginning of
            # the string or immediately after a shell-composition
            # separator), so that tool arguments like ``getent passwd
            # <user>``, ``grep passwd /etc/nss.conf``, or ``ldapsearch
            # passwd`` — all of which put ``passwd`` in an argument
            # slot after a plain whitespace separator — do NOT fire.
            r"|(?:^|[;&|])\s*passwd\s+[A-Za-z_][A-Za-z0-9_-]*"
        ),
        "user_account",
    ),
    # Remote-access and power / startup toggles via ``systemsetup``.
    # Siblings to the existing ``time_sync`` family — same tool,
    # different surfaces: SSH daemon on/off (-setremotelogin), Remote
    # Apple Events (-setremoteappleevents), wake-on-LAN / wake-on-
    # modem, sleep / display-sleep / hard-disk-sleep, restart on
    # freeze / power-on, power-button-sleep, boot-disk selection,
    # login-chime toggle.  ``systemsetup -get*`` / ``-list*`` stay
    # untagged (read forms).
    (
        re.compile(
            r"\bsystemsetup\s+-set(?:remotelogin|remoteappleevents|"
            r"wakeonnetworkaccess|wakeonmodem|computersleep|"
            r"displaysleep|harddisksleep|restartfreeze|restartpoweron|"
            r"allowpowerbuttontosleepcomputer|startupdisk|"
            r"disableloginchime)\b"
        ),
        "remote_access",
    ),
    # FileVault disk-encryption mutation.  ``fdesetup enable|disable|
    # add|remove|changerecovery|sync|authrestart``.  Read verbs
    # (``status``, ``list``, ``haspersonalrecoverykey``,
    # ``hasinstitutionalrecoverykey``, ``isactive``,
    # ``usingrecoverykey``) stay outside the alternation.
    (
        re.compile(
            r"\bfdesetup\s+(?:enable|disable|remove|add|changerecovery|"
            r"sync|authrestart)\b"
        ),
        "disk_encryption",
    ),
    # Kernel tunables.  ``sysctl -w key=val`` is the explicit write;
    # ``sysctl key=val`` (no -w) is an implicit write; ``sysctl -p
    # [file]`` loads a config file.  Linux's alternate path is a
    # redirect or tee into ``/proc/sys/...``.  Read forms
    # (``sysctl key``, ``sysctl -a``, ``sysctl -n key``) stay
    # untagged — covered by the existing ``read_only:system_info``
    # rule which excludes ``-w`` / ``-p``.
    (
        re.compile(
            r"\bsysctl\s+(?:-[a-zA-Z]+\s+)*-w\b"
            r"|\bsysctl\s+(?:-[a-zA-Z]+\s+)*-p\b"
            r"|\bsysctl\s+(?:-[a-zA-Z]+\s+)*"
            r"[A-Za-z_][A-Za-z0-9_.]*="
            r"|(?:^|[\s;&|])(?:>>?|&>|2>>?)\s*/proc/sys/[^\s|;&]+"
            r"|\btee\s+(?:-[a-zA-Z]+\s+)*/proc/sys/[^\s|;&]+"
        ),
        "kernel_tunable",
    ),
    # Persistence mechanisms not already caught by the catastrophic
    # pattern layer.  ``at <time>`` is pattern-catastrophic for the
    # common ``now`` / ``now + N minute`` / ``-f file`` shapes via
    # IF-AT-SCHEDULE-001; the natural-language time shapes
    # (``at noon tomorrow``, ``at teatime``, ``at 3pm`` etc.) fall
    # through to this classifier rule.  ``osascript`` + ``System
    # Events`` + ``login item`` is the canonical AppleScript login-
    # item persistence incantation; matching all three tokens
    # keeps benign osascript invocations (Finder actions,
    # notifications, display dialogs) untagged.
    (
        re.compile(
            r"\bat\s+(?:noon|midnight|teatime|today|tomorrow|"
            r"\d{1,2}(?::\d{2})?(?:am|pm|AM|PM)?(?:\s|$))"
            r"|\bat\s+(?:now|\+)"
            r"|\bat\s+-f\b"
            r"|\bosascript\b[^|;&]*\bSystem\s+Events\b"
            r"[^|;&]*\blogin\s+item\b"
            r"|\bosascript\b[^|;&]*\bmake\s+(?:new\s+)?login\s+item\b"
        ),
        "persistence",
    ),
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
    # Refined: stdin-piped exec (one rule per interpreter family).
    # Emitted alongside the binary CAPABILITY_STDIN_EXEC below so
    # ``_READ_ONLY_INCOMPATIBLE_CAPS`` (literal-string lookup) keeps
    # working, while policy layers gain ``stdin_exec:<lang>`` granularity
    # for the python+shell-only deny set.
    *_expand_refined(
        _STDIN_EXEC_RULES,
        CAPABILITY_STDIN_EXEC,
        "Command pipes input into a {suffix} interpreter (stdin exec)",
    ),
    # Refined: sensitive data-read surfaces (one rule per data class).
    # No base ``capability:data_read`` tag is emitted; consumers prefix-
    # match on ``capability:data_read:*`` — see module docstring and
    # ``_safe_for_read_only`` / ``_composition_is_all_read_only`` for
    # the classifier-side suppression of ``read_only:*`` when any
    # ``data_read:*`` tag fires on the same command.
    *_expand_refined(
        _DATA_READ_RULES,
        CAPABILITY_DATA_READ,
        "Command reads sensitive {suffix} material",
    ),
    # Refined: system-mutation surfaces (one rule per surface).
    # No base ``capability:system_mutate`` tag is emitted; consumers
    # prefix-match on ``capability:system_mutate:*``.  The rules are
    # positive-mutation matches only — read forms of the same tools
    # stay tagged under the read-only family.
    *_expand_refined(
        _SYSTEM_MUTATE_RULES,
        CAPABILITY_SYSTEM_MUTATE,
        "Command mutates host {suffix} state",
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
            r"\|\s*(?:python3?|python2|node|nodejs|ruby|perl|php|"
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


# Composition tokens that a read-only multi-segment invocation may
# use as joiners.  Everything in `_SHELL_COMPOSITION_TOKENS` outside
# this set is a redirect or a state-changing token (background `&`,
# case fallthrough `;;`) that disqualifies a composition from being
# tagged read-only.
_READ_ONLY_COMPOSITION_JOINERS: frozenset[str] = frozenset({
    "|", "||", "&&", ";", "|&",
})

_READ_ONLY_DISQUALIFYING_TOKENS: frozenset[str] = (
    _SHELL_COMPOSITION_TOKENS - _READ_ONLY_COMPOSITION_JOINERS
)


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


# Capabilities that are incompatible with any read-only tagging.
# Shared between the single-head gate (`_safe_for_read_only`) and the
# composition gate (`_composition_is_all_read_only`) so both families
# reject the same set of side-effect signals.
_READ_ONLY_INCOMPATIBLE_CAPS: frozenset[str] = frozenset({
    CAPABILITY_STDIN_EXEC,
    CAPABILITY_FILESYSTEM_WRITE,
    CAPABILITY_SPAWNS_PROCESS,
    CAPABILITY_NETWORK_BIND,
    CAPABILITY_BACKGROUND_EXEC,
    CAPABILITY_DOWNLOAD_AND_EXEC,
    CAPABILITY_BINARY_DOWNLOAD,
    CAPABILITY_PROCESS_SIGNAL,
    CAPABILITY_COMPILATION,
})


# Trusted absolute-path bin directories.  Heads matching
# ``<trusted>/<name>`` are rewritten to just ``<name>`` for rule
# matching, on the premise that these directories are system-owned
# and not user-writable without root on a correctly-configured host,
# so path-prefix spoofing is not a credible threat.  Any other
# absolute or relative path prefix keeps the current strict behaviour.
_TRUSTED_BIN_DIRS: frozenset[str] = frozenset({
    "/bin", "/usr/bin", "/sbin", "/usr/sbin",
    "/usr/local/bin", "/usr/local/sbin",
    "/opt/homebrew/bin", "/opt/homebrew/sbin",
    "/opt/local/bin", "/opt/local/sbin",
})


# Characters that, if present in a ``cd`` argument, indicate shell
# expansion or composition the classifier cannot statically reason
# about.  A ``cd`` arg containing any of these is NOT treated as a
# safe read-only prefix.  ``~`` is intentionally NOT included —
# tilde expansion is deterministic and resolves to the user's home
# directory with no side effects.
_CD_UNSAFE_METACHARS: frozenset[str] = frozenset("$`*?[](){}<>|&;\n\r\"'\\")


# Heads that safely consume from stdin in a pipeline and are therefore
# accepted as read-only pipe-consumer segments even without a
# positional file argument.  The main ``_READ_ONLY_RULES`` regexes for
# ``filesystem_read`` / ``search`` / streaming ``archive_inspect``
# require ``\s+<positional>`` because bare single-head invocations of
# these tools would wait on an interactive TTY — an unusual shape the
# classifier intentionally doesn't bless outside a pipeline.  Inside a
# composition, though, ``… | head``, ``… | wc``, ``cat`` reading from
# a heredoc, etc. are the overwhelmingly common pattern.
#
# Verb-discriminated heads (``git``, ``hg``, ``svn``, ``docker``,
# ``kubectl``, ``tar``, ``unzip``, ``arp``, ``route``, ``ip``,
# ``ifconfig``, ``sort`` with ``-o``, ``xmllint`` with ``--output``,
# ``sysctl`` with ``-w``, etc.) are deliberately NOT in this set —
# their safety depends on arguments the main regex checks.
_PIPE_CONSUMER_HEADS: frozenset[str] = frozenset({
    "cat", "head", "tail", "less", "more", "wc",
    "hexdump", "xxd", "od", "nl", "tac", "rev",
    "md5sum", "sha1sum", "sha224sum", "sha256sum", "sha384sum",
    "sha512sum", "b2sum", "shasum", "cksum", "sum",
    "grep", "egrep", "fgrep", "rg", "ack",
    "zcat", "bzcat", "xzcat", "zstdcat", "lz4cat",
})

_FLAG_TOKEN_RE: re.Pattern[str] = re.compile(
    r"\A(?:-{1,2}[A-Za-z0-9][A-Za-z0-9\-]*(?:=\S+)?|-\d+)\Z"
)


def _normalize_trusted_head(command: str) -> str:
    """Return *command* with its head token replaced by basename iff
    the head is an absolute path under ``_TRUSTED_BIN_DIRS``.

    The input is assumed to be the already-shlex-normalised command
    string produced by :func:`command_shield.structural.normalize`
    (quotes already stripped, whitespace collapsed).  That means the
    first whitespace-delimited field is the head token verbatim.

    Returns the original command unchanged when:
      * the command is empty,
      * the head is not an absolute path,
      * the head's parent directory is not trusted,
      * the head's basename is empty.
    """
    parts = command.split(None, 1)
    if not parts:
        return command
    head = parts[0]
    if not head.startswith("/"):
        return command
    parent, slash, base = head.rpartition("/")
    if not slash or not base or parent not in _TRUSTED_BIN_DIRS:
        return command
    if len(parts) == 1:
        return base
    return f"{base} {parts[1]}"


def _is_safe_cd(sub_command: str) -> bool:
    """True iff *sub_command* is a read-only-equivalent ``cd`` form:
    ``cd``, ``cd -``, or ``cd <arg>`` where ``<arg>`` is a single
    literal with no shell metacharacters.

    A safe ``cd`` changes the working directory deterministically
    without touching disk, spawning processes, or emitting network
    traffic.  It is accepted as a segment inside a read-only
    composition even though ``cd`` itself is not in the
    ``_READ_ONLY_RULES`` (which target observable read operations).
    """
    try:
        toks = shlex.split(sub_command)
    except ValueError:
        return False
    if not toks or toks[0] != "cd":
        return False
    if len(toks) == 1:
        return True
    if len(toks) != 2:
        return False
    return not any(c in _CD_UNSAFE_METACHARS for c in toks[1])


def _sub_command_matches_read_only(sub_command: str) -> bool:
    """True iff *sub_command*, after trusted-path head normalisation,
    is a read-only invocation.

    Primary check: match any regex in ``_READ_ONLY_RULES``.

    Fallback: pipe-consumer head from ``_PIPE_CONSUMER_HEADS`` with
    no positional argument (only flag-shaped tokens).  The main
    ``filesystem_read`` / ``search`` regexes require ≥1 positional
    so bare ``head``, ``wc``, ``grep`` etc. never match as
    single-head invocations — but in a pipeline those same heads are
    the canonical stdin consumers.  The fallback accepts that narrow
    shape and nothing else.

    Used by the composition gate to check per-segment read-only-ness
    without duplicating the rule list.  The sub-command is assumed
    to be the whitespace-joined word form produced by the structural
    visitor (no quoting to strip).
    """
    normalized = _normalize_trusted_head(sub_command)
    for rx, _suffix in _READ_ONLY_RULES:
        if rx.match(normalized) is not None:
            return True
    parts = normalized.split()
    if not parts or parts[0] not in _PIPE_CONSUMER_HEADS:
        return False
    return all(_FLAG_TOKEN_RE.match(t) is not None for t in parts[1:])


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
        head_normalized = _normalize_trusted_head(command)
        for rx, suffix in _READ_ONLY_RULES:
            m = rx.match(head_normalized)
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
                evidence=command[:120],
            )
    elif _composition_is_all_read_only(
        command,
        sub_commands=sub_commands,
        indirections=indirections,
        structural_signals=structural_signals,
        emitted=seen,
    ):
        cap_id = f"{CAPABILITY_READ_ONLY}:composition"
        seen[cap_id] = Signal(
            check="capability",
            signal_id=cap_id,
            description=(
                "Command is a read-only composition: every sub-command is "
                "an individually bare read-only invocation (or a safe "
                "literal `cd`), joined by pipe / && / || / ; only, with "
                "no redirects, indirection, or dynamic content"
            ),
            evidence=command[:120],
        )

    if _safe_for_network_probe(
        command,
        sub_commands=sub_commands,
        indirections=indirections,
        structural_signals=structural_signals,
    ):
        head_normalized = _normalize_trusted_head(command)
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
            m = rx.match(head_normalized)
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
                evidence=command[:120],
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
    ``package_install:*`` / ``script_execution:*`` / ``data_read:*``
    / ``system_mutate:*`` tag disqualifies the command from receiving
    any ``read_only:*`` tag.  The ``data_read:*`` / ``system_mutate:*``
    suppression is the classifier-side Option-A gate that prevents a
    sensitive-surface command from also being blessed as a cheap
    read-only fast-path candidate downstream.
    """
    if not _structurally_bare(
        command,
        sub_commands=sub_commands,
        indirections=indirections,
        structural_signals=structural_signals,
    ):
        return False

    for cap_id in emitted:
        if cap_id in _READ_ONLY_INCOMPATIBLE_CAPS:
            return False
        if cap_id.startswith(f"{CAPABILITY_PACKAGE_INSTALL}:"):
            return False
        if cap_id.startswith(f"{CAPABILITY_SCRIPT_EXECUTION}:"):
            return False
        if cap_id.startswith(f"{CAPABILITY_DATA_READ}:"):
            return False
        if cap_id.startswith(f"{CAPABILITY_SYSTEM_MUTATE}:"):
            return False

    return True


def _composition_is_all_read_only(
    command: str,
    *,
    sub_commands: tuple[str, ...],
    indirections: tuple[str, ...],
    structural_signals: tuple[Signal, ...],
    emitted: dict[str, Signal],
) -> bool:
    """Return True iff *command* is a multi-segment composition
    whose every sub-command is independently a read-only invocation.

    Invariants — a composition qualifies only if all hold:

    1. No interpreter indirection payloads.
    2. At least two structural sub-commands (single-head case is
       already handled by ``_safe_for_read_only``).
    3. No dynamic-content structural signal (command-substitution,
       process-substitution, variable-expansion, parse/shlex failure,
       interpreter indirection).
    4. No already-emitted capability in the read-only-incompatible
       set or the refined package_install / script_execution /
       data_read / system_mutate families.  This is the single
       broadest safety gate: any sub-segment that emits
       ``filesystem_write`` (redirects, ``tee``), ``spawns_process``
       (``xargs``, ``sudo``, ``ssh``, ``docker run``, …),
       ``stdin_exec`` (``| sh``, ``| python -``),
       ``download_and_exec`` (``curl … | sh``), ``background_exec``
       (trailing ``&``), ``network_bind``, ``data_read:*``
       (sensitive data reads), ``system_mutate:*`` (host-state
       mutations), etc. disqualifies the whole composition
       automatically.
    5. Every bare shell token in the re-tokenised command that lies
       in ``_SHELL_COMPOSITION_TOKENS`` must also lie in
       ``_READ_ONLY_COMPOSITION_JOINERS`` — i.e. only ``|``, ``||``,
       ``&&``, ``;``, ``|&`` are allowed as joiners; redirects and
       ``;;`` / standalone ``&`` are rejected at this layer even
       though they would also be caught by the capability check.
    6. Every structural sub-command is either a safe ``cd <literal>``
       or a head that matches ``_READ_ONLY_RULES`` (with trusted-path
       head-basename normalisation applied).
    """
    if indirections:
        return False
    if len(sub_commands) < 2:
        return False

    for sig in structural_signals:
        if sig.signal_id in _DYNAMIC_STRUCTURAL_IDS:
            return False

    for cap_id in emitted:
        if cap_id in _READ_ONLY_INCOMPATIBLE_CAPS:
            return False
        if cap_id.startswith(f"{CAPABILITY_PACKAGE_INSTALL}:"):
            return False
        if cap_id.startswith(f"{CAPABILITY_SCRIPT_EXECUTION}:"):
            return False
        if cap_id.startswith(f"{CAPABILITY_DATA_READ}:"):
            return False
        if cap_id.startswith(f"{CAPABILITY_SYSTEM_MUTATE}:"):
            return False

    try:
        toks = shlex.split(command)
    except ValueError:
        return False
    for tok in toks:
        if tok in _READ_ONLY_DISQUALIFYING_TOKENS:
            return False

    for sub in sub_commands:
        if _is_safe_cd(sub):
            continue
        if _sub_command_matches_read_only(sub):
            continue
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
