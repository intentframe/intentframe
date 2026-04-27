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
    capability:data_read:dotfile_secrets       — .env / .envrc / .env.<stage> /
                                                  .npmrc / .pypirc / .netrc /
                                                  .gemrc / .pgpass / .my.cnf /
                                                  .pip/pip.conf /
                                                  .docker/config.json — the
                                                  canonical "secrets in a
                                                  dotfile" surface
    capability:data_read:cloud_tokens          — .aws/credentials, .aws/config,
                                                  .kube/config,
                                                  .config/gcloud/** credentials,
                                                  .azure/accessTokens.json,
                                                  .terraform.d/credentials.tfrc
                                                  .json, .vault-token,
                                                  .hcp/credentials, Kubernetes
                                                  service-account token mount,
                                                  gcloud/aws/az access-token
                                                  print verbs
    capability:data_read:db_client_history     — mongosh history / .mongorc.js
                                                  / .mongoshrc.js / .dbshell /
                                                  .snowsql/history / .duckdbrc
                                                  / .cqlshrc (db-client history
                                                  files not already covered by
                                                  ``shell_history``)
    capability:data_read:browser_session_data  — Chromium-family Local Storage
                                                  / Session Storage / IndexedDB
                                                  / Service Worker / Cache /
                                                  {Current,Last} {Session,Tabs};
                                                  Firefox sessionstore /
                                                  storage/default / cache2
                                                  entries
    capability:data_read:password_manager_export
                                              — 1Password *.1pif exports,
                                                  bitwarden/lastpass/dashlane/
                                                  keepass/enpass/roboform
                                                  _export.{csv,json,xml,zip,
                                                  1pif}; password-manager app
                                                  data containers beyond the
                                                  ``credential_material``
                                                  shapes
    capability:data_read:process_env           — /proc/<pid>/environ reads,
                                                  ``ps`` invocations with an
                                                  ``e`` flag (BSD env dump),
                                                  ``launchctl print`` /
                                                  ``procinfo``
    capability:data_read:ssh_known_hosts       — ~/.ssh/known_hosts /
                                                  ~/.ssh/config reads — lateral-
                                                  movement recon surface
    capability:data_read:mail_store            — Thunderbird profile ImapMail/
                                                  Mail/Messages, Microsoft
                                                  Outlook for Mac app data,
                                                  Airmail / Spark app data,
                                                  raw *.mbox stores (Apple
                                                  Mail's Library/Mail/V* is
                                                  already covered by
                                                  ``personal_records``)

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
    capability:system_mutate:mdm_profile            — profiles -I / -R / -E /
                                                      install / remove / renew
                                                      (configuration-profile
                                                      install / removal)
    capability:system_mutate:boot_policy            — bputil set-* / disable-*;
                                                      bless --setBoot / --bootefi;
                                                      nvram <name>=<value> / -d /
                                                      -c; firmwarepasswd
                                                      -setpasswd / -delete /
                                                      -setmode (boot / firmware
                                                      trust state)
    capability:system_mutate:audit_log              — audit -n / -s / -t / -R /
                                                      -A / -c; log erase; log
                                                      config (BSM / unified
                                                      logging subsystem
                                                      mutation)
    capability:system_mutate:tcc_privacy            — tccutil reset / insert;
                                                      sqlite3 .TCC.db with
                                                      INSERT / UPDATE / DELETE /
                                                      REPLACE verbs
    capability:system_mutate:backup                 — tmutil disable / enable /
                                                      startbackup / stopbackup /
                                                      delete / inherit /
                                                      setdestination /
                                                      removedestination /
                                                      addexclusion /
                                                      removeexclusion; asr
                                                      restore / create /
                                                      imagescan
    capability:system_mutate:installer_pkg          — installer -pkg / -package;
                                                      softwareupdate --install /
                                                      -i; pkgutil --forget
    capability:system_mutate:kernel_extension       — kextload / kextunload /
                                                      kmutil load / unload
                                                      (kernel / system
                                                      extensions)
    capability:system_mutate:service_mgmt           — systemctl start / stop /
                                                      restart / enable /
                                                      disable / mask / unmask /
                                                      daemon-reload / …;
                                                      service <name>
                                                      (start|stop|…);
                                                      rc-update add / del;
                                                      chkconfig --add / --del /
                                                      on / off; update-rc.d
    capability:system_mutate:launchd_mutation       — launchctl load / unload /
                                                      bootstrap / bootout /
                                                      enable / disable /
                                                      remove / stop / start /
                                                      kickstart / submit /
                                                      setenv / unsetenv /
                                                      override / limit /
                                                      config — superset of
                                                      ``security_daemon``
                                                      (which fires
                                                      additionally when the
                                                      target service name is a
                                                      known security daemon)
    capability:system_mutate:cron_mutation          — crontab -e / -r / -u /
                                                      <file> (install from
                                                      file); redirect / tee /
                                                      cp / mv / install / ln
                                                      targeting
                                                      /etc/cron.{d,daily,
                                                      hourly,weekly,monthly}/
    capability:system_mutate:browser_extension      — defaults write on
                                                      Chrome/Edge/Firefox
                                                      ExtensionInstall*
                                                      policy keys; writes to
                                                      browser policies.json /
                                                      External Extensions
                                                      directories
    capability:system_mutate:screen_sharing         — Apple Remote Desktop
                                                      ``kickstart`` activate /
                                                      configure / access /
                                                      restart / deactivate /
                                                      uninstall; com.apple.
                                                      RemoteDesktop kickstart
                                                      path invocation
    capability:system_mutate:print_config           — cupsenable / cupsdisable
                                                      / cupsaccept / cupsreject
                                                      / lpadmin / lpoptions
    capability:system_mutate:radio_power            — networksetup
                                                      -setairportpower /
                                                      -setairportnetwork;
                                                      airport -z /
                                                      --disassociate /
                                                      --associate; blueutil
                                                      -p / --power

    capability:network_exfil:http_upload           — curl/wget/http/xh requests
                                                      that reference a LOCAL
                                                      file as the body / upload
                                                      payload: curl -T /
                                                      --upload-file, -F ...=@,
                                                      -d|--data|--data-binary|
                                                      --data-ascii|--data-
                                                      urlencode @file; wget
                                                      --post-file / --body-file;
                                                      HTTPie/xh ``name@path`` /
                                                      ``name=@path`` request-
                                                      item syntax
    capability:network_exfil:file_transfer_outbound — scp / rsync commands whose
                                                      final positional is a
                                                      ``[user@]host:`` remote
                                                      endpoint (LOCAL → REMOTE
                                                      direction); sftp batch
                                                      mode with -b
    capability:network_exfil:ssh_tunnel             — ssh -R / -L / -D (remote /
                                                      local / dynamic port
                                                      forwarding)
    capability:network_exfil:cloud_upload           — aws s3 cp / sync / mv /
                                                      mb / rb; aws s3api
                                                      put-object /
                                                      upload-part(-copy) /
                                                      create-multipart-upload;
                                                      gsutil cp / mv / rsync;
                                                      gcloud storage cp / mv /
                                                      rsync; az storage blob /
                                                      file upload(-batch); mc
                                                      cp / mv / mirror; b2
                                                      upload-file /
                                                      upload-unbound-stream

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

from command_shield.capabilities import CORPUS as _CAPABILITY_CORPUS
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
# All three are emitted only as ``<base>:<suffix>`` refined tags — the
# bare base form is never seen on a command.  Consumers MUST prefix-
# match these families (literal equality against ``capability:data_read``
# / ``capability:system_mutate`` / ``capability:network_exfil`` will
# never fire).
#
#   * ``capability:data_read:*`` — reads that yield information an
#     agent must not exfiltrate under the root-compromised-agent threat
#     model.  Suffixes cover browser cookies (``browser_cookies``),
#     macOS Directory-Services account records (``auth_authority``),
#     keychain / TCC.db / GPG secret-key / password-manager vault
#     contents (``credential_material``), shell-history stores
#     (``shell_history``), browser saved-login / history / bookmark /
#     form-autofill data beyond cookies (``browser_profile_data``),
#     messaging-client on-disk histories (``messaging_history``),
#     high-PII personal stores (``personal_records``), dotfile secrets
#     (``dotfile_secrets``), cloud-provider CLI tokens / token-printing
#     verbs (``cloud_tokens``), non-shell DB-client history files
#     (``db_client_history``), browser Local/Session storage / IndexedDB
#     / Service Worker / Firefox sessionstore (``browser_session_data``),
#     password-manager export files and app containers
#     (``password_manager_export``), process-environment dumps
#     (``process_env``), ~/.ssh/known_hosts / config / authorized_keys
#     (``ssh_known_hosts``), and non-Apple mail stores
#     (``mail_store``).  Structurally these commands are read-shaped,
#     so this family is treated as read-only-incompatible in the
#     classifier gate (``_safe_for_read_only``): emitting
#     ``data_read:*`` suppresses ``read_only:*`` on the same command so
#     the consumer fast-path license is not accidentally available for
#     a sensitive read.
#
#   * ``capability:system_mutate:*`` — commands that change host /
#     network / identity / trust-surface state.  Suffixes cover routing
#     and interface config (``host_network_config``), hostname
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
#     ``at`` / AppleScript login-item persistence
#     (``persistence``), MDM ``profiles`` install / remove
#     (``mdm_profile``), boot-chain mutation — bputil / bless / nvram
#     / firmwarepasswd (``boot_policy``), audit / unified-logging
#     subsystem mutation (``audit_log``), tccutil reset / TCC.db writes
#     (``tcc_privacy``), Time Machine / asr backup mutation
#     (``backup``), installer / softwareupdate / pkgutil --forget
#     (``installer_pkg``), kext / kmutil load / unload
#     (``kernel_extension``), Linux service-manager verbs
#     (``service_mgmt``), generic launchctl mutation superset
#     (``launchd_mutation``), crontab -e / -r / -u / <file> and
#     /etc/cron.* writes (``cron_mutation``), browser extension-install
#     policy writes (``browser_extension``), ARD ``kickstart``
#     (``screen_sharing``), CUPS printer daemon mutation
#     (``print_config``), and Wi-Fi / Bluetooth radio power
#     (``radio_power``).  Structurally these are mutating and so would
#     not qualify for ``read_only:*`` on their own; the read-only-
#     incompatible membership is belt-and-braces against an
#     unanticipated co-occurrence.
#
#   * ``capability:network_exfil:*`` — commands whose primary effect is
#     moving local-host data outbound over the network, distinct from
#     ``network_probe:*`` (which is idempotent remote queries).
#     Suffixes cover HTTP-body / file-upload shapes (``http_upload``),
#     scp / rsync / sftp with a remote destination
#     (``file_transfer_outbound``), ssh port forwarding
#     (``ssh_tunnel``), and cloud-object-store / MinIO / B2 upload
#     verbs (``cloud_upload``).  Treated as read-only-incompatible in
#     the classifier gate so a ``curl -T secrets.tar …`` can never be
#     blessed as a read-only fast-path candidate.
CAPABILITY_DATA_READ = "capability:data_read"
CAPABILITY_SYSTEM_MUTATE = "capability:system_mutate"
CAPABILITY_NETWORK_EXFIL = "capability:network_exfil"


# ── Detection rules ─────────────────────────────────────────────────
#
# Each rule is (regex, capability_id, description).
# Regexes run against the normalized command string and against each
# indirection payload.  Rules are intentionally conservative — false
# negatives are preferable to false positives, since the verdict comes
# from step 3 patterns and these signals are advisory.

# Refined rules for package install / stdin exec / script execution are
# loaded from ``command_shield/capabilities/*.yaml`` via the corpus.
# Only rules that carry a suffix participate as refined (per-interpreter
# or per-manager) tags; the bare umbrella rule for stdin_exec lives in
# the same YAML but is emitted separately from the ``_RULES`` tuple
# below.  Order matters only within a capability family (first match
# wins per tag in ``seen``); across capabilities all independent rules
# are evaluated.
_PACKAGE_INSTALL_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (r.pattern, r.suffix)
    for r in _CAPABILITY_CORPUS.by_family("package_install")
    if r.suffix
)

_STDIN_EXEC_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (r.pattern, r.suffix)
    for r in _CAPABILITY_CORPUS.by_family("stdin_exec")
    if r.suffix
)

_SCRIPT_EXECUTION_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (r.pattern, r.suffix)
    for r in _CAPABILITY_CORPUS.by_family("script_execution")
    if r.suffix
)


# Sensitive-data-read refined rules — loaded from
# ``command_shield/capabilities/data_read.yaml``.  Emission is
# driven purely by the main ``_RULES`` loop (no structural-
# bareness gate), since the point of the family is to tag the
# command regardless of shape; a policy that denies
# ``capability:data_read:browser_cookies`` wants the deny to
# fire whether the command is bare, composed, or hidden behind
# an indirection.  Multiple rules may share a suffix — the
# first one to match adds the tag, subsequent rules with the
# same suffix are skipped by the main classification loop
# (``if cap_id in seen``).
_DATA_READ_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (r.pattern, r.suffix) for r in _CAPABILITY_CORPUS.by_family("data_read")
)


# System-mutation refined rules — loaded from
# ``command_shield/capabilities/system_mutate.yaml``.  Each regex is
# the mutation-verb shape for a host / network / trust-surface
# mutation class; the corresponding read forms stay untagged here and
# are picked up by the read-only family instead.
_SYSTEM_MUTATE_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (r.pattern, r.suffix)
    for r in _CAPABILITY_CORPUS.by_family("system_mutate")
)


# Network-exfil refined rules — loaded from
# ``command_shield/capabilities/network_exfil.yaml``.  Distinct from
# ``network_probe:*`` (idempotent remote queries): every tag here
# says "this command carries LOCAL data outbound".  Emission is
# driven purely by the main ``_RULES`` loop (no structural-bareness
# gate), since the point of the family is to tag the command whether
# it is bare, composed, pipelined, or hidden behind indirection — a
# policy that denies ``capability:network_exfil:cloud_upload`` wants
# the deny to fire in all shapes.
_NETWORK_EXFIL_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (r.pattern, r.suffix)
    for r in _CAPABILITY_CORPUS.by_family("network_exfil")
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


def _family_bare(family: str) -> tuple[tuple[re.Pattern[str], str, str], ...]:
    """Return ``(pattern, tag, description)`` rows for bare-family rules.

    "Bare" here means the YAML rule has no ``suffix``, so the emitted
    tag is ``capability:<family>`` with no trailing ``:<sub>``.  Used
    by :data:`_RULES` to expand single-tag capability families
    (``compilation``, ``network_bind``, ``background_exec``,
    ``download_and_exec``, ``binary_download``, ``process_signal``,
    ``spawns_process``, ``filesystem_write``, and the ``stdin_exec``
    umbrella rule) loaded from YAML.
    """
    return tuple(
        (r.pattern, r.capability_tag(), r.description)
        for r in _CAPABILITY_CORPUS.by_family(family)
        if not r.suffix
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
    # Refined: network-exfil surfaces (one rule per exfil shape).
    # No base ``capability:network_exfil`` tag is emitted; consumers
    # prefix-match on ``capability:network_exfil:*``.  Treated as
    # read-only-incompatible so an exfil-shaped curl / rsync / aws-s3
    # command never receives a ``read_only:*`` fast-path tag.
    *_expand_refined(
        _NETWORK_EXFIL_RULES,
        CAPABILITY_NETWORK_EXFIL,
        "Command moves local data outbound via {suffix}",
    ),
    # Bare single-tag capability families — loaded from
    # ``command_shield/capabilities/*.yaml``.  Each rule emits a single
    # ``capability:<family>`` tag with no ``:<sub>`` suffix.  The
    # ``stdin_exec`` umbrella rule lives in the same YAML as the per-
    # interpreter refined rules above; ``_family_bare`` selects only
    # suffix-less rows so the umbrella fires in addition to the refined
    # per-interpreter tags.
    *_family_bare("compilation"),
    *_family_bare("network_bind"),
    *_family_bare("background_exec"),
    *_family_bare("download_and_exec"),
    *_family_bare("binary_download"),
    *_family_bare("stdin_exec"),
    *_family_bare("process_signal"),
    *_family_bare("spawns_process"),
    *_family_bare("filesystem_write"),
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

_READ_ONLY_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (r.pattern, r.suffix)
    for r in _CAPABILITY_CORPUS.by_family('read_only')
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

_NETWORK_PROBE_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (r.pattern, r.suffix)
    for r in _CAPABILITY_CORPUS.by_family('network_probe')
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
    / ``system_mutate:*`` / ``network_exfil:*`` tag disqualifies the
    command from receiving any ``read_only:*`` tag. The sensitive-tag
    suppression rule prevents a sensitive-surface command from also
    being blessed as a cheap read-only fast-path candidate downstream.
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
        if cap_id.startswith(f"{CAPABILITY_NETWORK_EXFIL}:"):
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
       data_read / system_mutate / network_exfil families.  This is
       the single broadest safety gate: any sub-segment that emits
       ``filesystem_write`` (redirects, ``tee``), ``spawns_process``
       (``xargs``, ``sudo``, ``ssh``, ``docker run``, …),
       ``stdin_exec`` (``| sh``, ``| python -``),
       ``download_and_exec`` (``curl … | sh``), ``background_exec``
       (trailing ``&``), ``network_bind``, ``data_read:*``
       (sensitive data reads), ``system_mutate:*`` (host-state
       mutations), ``network_exfil:*`` (outbound data transfer),
       etc. disqualifies the whole composition automatically.
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
        if cap_id.startswith(f"{CAPABILITY_NETWORK_EXFIL}:"):
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
