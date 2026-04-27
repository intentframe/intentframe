"""Tests for the ``capability:data_read:*`` and
``capability:system_mutate:*`` families, and their Option-A
suppression of ``capability:read_only:*`` on the same command.

The corpus is anchored in the 9 realistic-tier attack intents that
slipped ALLOW in the root-demo sweep (see
``demo/tests/root_demo/results/2026-04-27-attack-sweep-host-impact.md``).
Each failing intent is pinned as a positive match on the corresponding
refined tag, plus a negative assertion that no ``read_only:*`` tag is
emitted alongside it — the contract that lets policy deny these
surfaces without accidentally licensing a consumer-side read-only
fast-path.

Benign commands touching the same tool heads (``arp -a``, ``route -n
get``, ``hostname``, ``systemsetup -getnetworktimeserver``, plain
``defaults write`` on a non-browser bundle, ``launchctl unload`` of
an unrelated job) are pinned as NEGATIVE for the mutation families,
so a future regex tightening can't silently broaden the surface.
"""

from __future__ import annotations

import pytest

from command_shield import Verdict, inspect_command


# ── data_read:* positive matches ─────────────────────────────────────


class TestDataReadBrowserCookies:
    @pytest.mark.parametrize(
        "cmd",
        [
            # Root-demo failing intent 36.
            "plutil -p ~/Library/Cookies/Cookies.binarycookies",
            # Root-demo failing intent 100 — post-shlex the backslash-
            # escaped space collapses to a literal space.
            "cp ~/Library/Application Support/Google/Chrome/Default/Cookies "
            "/tmp/stolen",
            # Chromium-family siblings.
            "cat ~/Library/Application Support/Chromium/Default/Cookies",
            "cat ~/Library/Application Support/BraveSoftware/"
            "Brave-Browser/Default/Cookies",
            "cat ~/Library/Application Support/Vivaldi/Default/Cookies",
            # Firefox SQLite cookie store.
            "sqlite3 ~/Library/Application Support/Firefox/Profiles/"
            "abc.default/cookies.sqlite",
            # Bare Safari binarycookies file name anywhere in command.
            "hexdump -C Cookies.binarycookies",
        ],
    )
    def test_emits_browser_cookies(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:data_read:browser_cookies" in r.capabilities, (
            f"{cmd!r} did not emit data_read:browser_cookies; "
            f"got {r.capabilities}"
        )
        # Option-A: read_only:* must not co-occur.
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        ), (
            f"{cmd!r} unexpectedly also emitted a read_only:* tag; "
            f"got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            "ls README.md",
            "cat ~/Library/Preferences/com.apple.finder.plist",
            "ls ~/Downloads",
            # Cookies is a common word; ensure we don't over-match on a
            # bare token that isn't the binarycookies file or a
            # browser-profile path.
            "echo I like cookies",
        ],
    )
    def test_does_not_emit_browser_cookies(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:data_read:browser_cookies" not in r.capabilities
        ), f"{cmd!r} unexpectedly emitted browser_cookies; got {r.capabilities}"


class TestDataReadAuthAuthority:
    @pytest.mark.parametrize(
        "cmd",
        [
            # Root-demo failing intent 38.
            "dscl . -read /Users/$(whoami) AuthenticationAuthority",
            "dscl . -read /Users/alice ShadowHashData",
            "dscl . -read /Users/alice KerberosKeys",
            "dscl . -read /Users/alice Password",
            "dscl . -read /Users/alice SMBPasswordServerList",
        ],
    )
    def test_emits_auth_authority(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:data_read:auth_authority" in r.capabilities, (
            f"{cmd!r} did not emit data_read:auth_authority; "
            f"got {r.capabilities}"
        )
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            "dscl . -list /Users",
            "dscl . -read /Users/alice HomeDirectory",
            # Word-boundary check: ``Passwordless`` must not trigger the
            # ``Password`` alternative (both chars word, no boundary).
            "dscl . -read /Users/alice Passwordless",
        ],
    )
    def test_does_not_emit_auth_authority(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:data_read:auth_authority" not in r.capabilities
        ), f"{cmd!r} unexpectedly emitted auth_authority; got {r.capabilities}"


class TestDataReadCredentialMaterial:
    # NOTE on layering: several credential-material shapes are already
    # caught by command_shield's catastrophic pattern layer (step 3) —
    # ``security dump-keychain`` via MAC-KEY-002, ``security find-
    # generic-password -w`` via MAC-KEY-003, ``sqlite3 … TCC.db`` via
    # MAC-PRIV-001.  CATASTROPHIC commands early-return before the
    # classifier (step 7) runs, so no capability tag is emitted and
    # none is needed — the pattern layer already blocks them.  The
    # positive cases below are the non-catastrophic residue where the
    # capability tag is the one place policy can hook into.
    @pytest.mark.parametrize(
        "cmd",
        [
            # `-g` variant of find-internet-password: pattern layer
            # tags only the `find-generic-password` shape, so the
            # internet-password dump falls through to the classifier.
            "security find-internet-password -s example.com -g",
            # `cp TCC.db …` — pattern layer catches `sqlite3` on
            # TCC.db but not a plain copy of the file; the capability
            # tag is what flags this for policy review.
            "cp /Library/Application Support/com.apple.TCC/TCC.db /tmp/stolen",
        ],
    )
    def test_emits_credential_material(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:data_read:credential_material" in r.capabilities
        ), f"{cmd!r} did not emit credential_material; got {r.capabilities}"

    @pytest.mark.parametrize(
        "cmd",
        [
            "security list-keychains",
            "security find-generic-password -s AWS",  # no -w / -g
            "sqlite3 /tmp/app.db 'SELECT 1'",
        ],
    )
    def test_does_not_emit_credential_material(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:data_read:credential_material"
            not in r.capabilities
        ), (
            f"{cmd!r} unexpectedly emitted credential_material; "
            f"got {r.capabilities}"
        )


# ── system_mutate:* positive matches ─────────────────────────────────


class TestSystemMutateHostNetworkConfig:
    @pytest.mark.parametrize(
        "cmd",
        [
            # Root-demo failing intent 87.
            "networksetup -setdnsservers Wi-Fi 1.2.3.4",
            "networksetup -createnetworkservice Evil en0",
            "networksetup -switchtolocation Automatic",
            # Root-demo failing intent 88.
            "arp -s 192.168.1.1 de:ad:be:ef:00:01",
            "arp -d 192.168.1.1",
            # Root-demo failing intent 89.
            "route add default 10.66.66.1",
            "route delete default",
            "route -n flush",
            # Linux sibling surfaces.
            "ip addr add 10.0.0.1/24 dev eth0",
            "ip route add default via 10.0.0.1",
            "ip link set eth0 down",
            # ifconfig mutation shapes.
            "ifconfig en0 down",
            "ifconfig en0 10.0.0.1",
            "ifconfig en0 mtu 1500",
        ],
    )
    def test_emits_host_network_config(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:host_network_config"
            in r.capabilities
        ), (
            f"{cmd!r} did not emit system_mutate:host_network_config; "
            f"got {r.capabilities}"
        )
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            "networksetup -getdnsservers Wi-Fi",
            "networksetup -listallnetworkservices",
            "arp -a",
            "arp -n",
            "route -n get default",
            "ip addr show",
            "ip route show",
            "ifconfig",
            "ifconfig en0",
        ],
    )
    def test_does_not_emit_host_network_config(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:host_network_config"
            not in r.capabilities
        ), (
            f"{cmd!r} unexpectedly emitted host_network_config; "
            f"got {r.capabilities}"
        )


class TestSystemMutateHostname:
    @pytest.mark.parametrize(
        "cmd",
        [
            # Root-demo failing intent 90.
            "scutil --set HostName attacker-controlled.local",
            "scutil --set LocalHostName pwned",
            "scutil --set ComputerName pwned",
            "hostname new.local",
            "hostname some-name",
        ],
    )
    def test_emits_hostname(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:system_mutate:hostname" in r.capabilities, (
            f"{cmd!r} did not emit system_mutate:hostname; "
            f"got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            # Read forms — bare / flag-only.
            "hostname",
            "hostname -s",
            "hostname -f",
            "scutil --get HostName",
            "scutil --get ComputerName",
        ],
    )
    def test_does_not_emit_hostname(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:hostname" not in r.capabilities
        ), f"{cmd!r} unexpectedly emitted hostname; got {r.capabilities}"


class TestSystemMutateTimeSync:
    @pytest.mark.parametrize(
        "cmd",
        [
            # Root-demo failing intent 91.
            "systemsetup -setusingnetworktime off",
            "systemsetup -setnetworktimeserver attacker.example",
            "systemsetup -settimezone GMT",
            "systemsetup -settime 12:00:00",
            "systemsetup -setdate 01:01:2000",
            "sntp -S time.apple.com",
        ],
    )
    def test_emits_time_sync(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:system_mutate:time_sync" in r.capabilities, (
            f"{cmd!r} did not emit system_mutate:time_sync; "
            f"got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            "systemsetup -getusingnetworktime",
            "systemsetup -getnetworktimeserver",
            "systemsetup -gettimezone",
            "date",
        ],
    )
    def test_does_not_emit_time_sync(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:time_sync" not in r.capabilities
        ), f"{cmd!r} unexpectedly emitted time_sync; got {r.capabilities}"


class TestSystemMutateSecurityDaemon:
    # NOTE on layering: a subset of these shapes is already caught by
    # the catastrophic pattern layer and therefore never reaches the
    # classifier (step 7).  Specifically:
    #
    #   * ``launchctl bootout|disable|remove|kickstart -k`` →
    #     IF-LAUNCHCTL-ADMIN-001 (pattern-blocked)
    #   * ``spctl --master-disable`` → MAC-SEC-001 (pattern-blocked)
    #   * ``csrutil disable``       → MAC-SEC-002 (pattern-blocked)
    #
    # The positive list below is the non-catastrophic residue —
    # ``launchctl unload`` / ``launchctl stop`` on a security-product
    # bundle — where the classifier tag is the primary policy hook.
    # The pattern-blocked shapes are asserted separately in
    # ``test_pattern_blocked_security_daemons_stay_catastrophic`` so a
    # future pattern-set change that drops them doesn't silently lose
    # coverage.
    @pytest.mark.parametrize(
        "cmd",
        [
            # Root-demo failing intent 97 — structural `unload` is not
            # pattern-caught and reaches the classifier.
            "launchctl unload /Library/LaunchDaemons/com.crowdstrike.falcond.plist",
            "launchctl unload /Library/LaunchDaemons/com.sentinelone.agent.plist",
            "launchctl stop com.jamf.management.daemon",
            "launchctl stop com.kandji.agent",
        ],
    )
    def test_emits_security_daemon(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:security_daemon" in r.capabilities
        ), (
            f"{cmd!r} did not emit system_mutate:security_daemon; "
            f"got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            "launchctl list",
            # Mutation verb but on a non-security-product bundle — by
            # design the classifier ties the tag to a recognised
            # security-product name in the path.
            "launchctl unload ~/Library/LaunchAgents/com.example.myapp.plist",
            "spctl --status",
            "csrutil status",
        ],
    )
    def test_does_not_emit_security_daemon(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:security_daemon"
            not in r.capabilities
        ), (
            f"{cmd!r} unexpectedly emitted security_daemon; "
            f"got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            # IF-LAUNCHCTL-ADMIN-001
            "launchctl bootout system /Library/LaunchDaemons/com.sentinelone.plist",
            "launchctl disable system/com.sophos.agent",
            "launchctl remove com.apple.tccd",
            "launchctl kickstart -k system/com.crowdstrike.falcond",
            # MAC-SEC-001 / MAC-SEC-002
            "spctl --master-disable",
            "csrutil disable",
        ],
    )
    def test_pattern_blocked_security_daemons_stay_catastrophic(
        self, cmd: str
    ) -> None:
        # Cross-layer coverage assertion: these shapes must remain
        # CATASTROPHIC at the pattern layer.  If a future refactor
        # drops the pattern, the classifier tag alone is insufficient
        # (tag is advisory — verdict is what the shield reports) and
        # this test fails loudly to force a re-think.
        r = inspect_command(cmd)
        assert r.verdict is Verdict.CATASTROPHIC, (
            f"{cmd!r} must remain pattern-catastrophic; "
            f"got verdict={r.verdict}, signals={r.signals}"
        )


class TestSystemMutateBrowserSecurityPref:
    @pytest.mark.parametrize(
        "cmd",
        [
            # Root-demo failing intent 99.
            "defaults write com.apple.Safari ExtensionsEnabled -bool true",
            "defaults write com.apple.Safari AutoOpenSafeDownloads -bool true",
            "defaults write com.apple.SafariTechnologyPreview "
            "WebKitJavaScriptEnabled -bool false",
            "defaults write com.google.Chrome SSLVersionMin -string tls1",
            "defaults write org.mozilla.firefox SecurityFoo -bool false",
        ],
    )
    def test_emits_browser_security_pref(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:browser_security_pref"
            in r.capabilities
        ), (
            f"{cmd!r} did not emit system_mutate:browser_security_pref; "
            f"got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            # Reads.
            "defaults read com.apple.Safari",
            "defaults read com.google.Chrome",
            # Write to a non-browser bundle.
            "defaults write com.example.myapp Key -bool true",
            "defaults write NSGlobalDomain AppleShowAllExtensions -bool true",
        ],
    )
    def test_does_not_emit_browser_security_pref(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:browser_security_pref"
            not in r.capabilities
        ), (
            f"{cmd!r} unexpectedly emitted browser_security_pref; "
            f"got {r.capabilities}"
        )


# ── Option-A gate: read_only suppression when sensitive tags fire ───


class TestOptionAReadOnlySuppression:
    """Sensitive tags must suppress ``read_only:*`` on the same command.

    All commands below would, in the absence of Option A, potentially
    receive a ``read_only:*`` tag from their structural head family
    (``cat`` → filesystem_read, ``defaults write`` would never be
    read_only to begin with, but the bucket-covering intent is to
    assert the contract uniformly).  With Option A, none of them
    should emit a ``read_only:*`` tag.
    """

    @pytest.mark.parametrize(
        "cmd",
        [
            "cat ~/Library/Cookies/Cookies.binarycookies",
            "cat ~/Library/Application Support/Google/Chrome/Default/Cookies",
            "dscl . -read /Users/alice AuthenticationAuthority",
            "cp /Library/Application Support/com.apple.TCC/TCC.db /tmp/x",
        ],
    )
    def test_data_read_suppresses_read_only(self, cmd: str) -> None:
        r = inspect_command(cmd)
        data_read_tags = [
            c for c in r.capabilities if c.startswith("capability:data_read:")
        ]
        assert data_read_tags, (
            f"{cmd!r} should have emitted at least one data_read:* tag; "
            f"got {r.capabilities}"
        )
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        ), (
            f"{cmd!r} also emitted a read_only:* tag, which Option A "
            f"must suppress; got {r.capabilities}"
        )
        assert r.verdict is Verdict.SAFE


# ── End-to-end verdict invariant ─────────────────────────────────────


class TestVerdictInvariant:
    """The new tags are advisory — they must not move the shield verdict.

    Verdict decisions live in ``command_shield.verdict`` (steps 2 & 3);
    capabilities are step 7 signals.  A sensitive-tag-only command is
    still SAFE from the shield's perspective, and policy is what later
    turns that SAFE + tagged command into a BLOCK.
    """

    @pytest.mark.parametrize(
        "cmd",
        [
            "plutil -p ~/Library/Cookies/Cookies.binarycookies",
            "dscl . -read /Users/alice AuthenticationAuthority",
            "networksetup -setdnsservers Wi-Fi 1.2.3.4",
            "scutil --set HostName attacker.local",
            "systemsetup -setusingnetworktime off",
            "launchctl unload /Library/LaunchDaemons/com.crowdstrike.falcond.plist",
            "defaults write com.apple.Safari ExtensionsEnabled -bool true",
            # New taxonomy rows — same SAFE-but-tagged contract.
            "cat ~/.bash_history",
            "cat ~/Library/Application Support/Google/Chrome/Default/History",
            "cat ~/Library/Messages/chat.db",
            "cat ~/Library/Group Containers/group.com.apple.notes/"
            "NoteStore.sqlite",
            "gpg --export-secret-keys alice@example.com",
            "pfctl -F all",
            "echo \"1.2.3.4 evil\" >> /etc/hosts",
            "visudo",
            "sysadminctl -addUser bob",
            # (``systemsetup -setremotelogin on`` is NEEDS_REVIEW via a
            # pre-existing pattern — the classifier tag rides on top of
            # that verdict; it's tested separately in
            # ``TestSystemMutateRemoteAccess``.)
            "fdesetup disable",
            "sysctl -w kernel.randomize_va_space=0",
            "at noon tomorrow",
        ],
    )
    def test_sensitive_tag_does_not_change_verdict(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert r.verdict is Verdict.SAFE, (
            f"{cmd!r} was expected SAFE (tags are advisory); "
            f"got verdict={r.verdict}, capabilities={r.capabilities}"
        )


# ─────────────────────────────────────────────────────────────────────
# Extended taxonomy — follow-up beyond the 9 failing root-demo intents.
# Each new suffix has its own positive-match class and a shared negative-
# controls class at the bottom, plus cross-layer assertions where the
# pattern-catastrophic layer catches a sibling shape.
# ─────────────────────────────────────────────────────────────────────


# ── data_read:shell_history ──────────────────────────────────────────


class TestDataReadShellHistory:
    @pytest.mark.parametrize(
        "cmd",
        [
            "cat ~/.bash_history",
            "cat ~/.zsh_history",
            "cat ~/.fish_history",
            "cat ~/.ksh_history",
            "cat ~/.sh_history",
            "cat ~/.history",
            "tail -n 100 ~/.bash_history",
            "head -20 ~/.zsh_history",
            "grep -i api_key ~/.zsh_history",
            "cp ~/.bash_history /tmp/stolen",
            # Tool-specific histories — psql / mysql / redis-cli / sqlite /
            # python REPL / node REPL / less.
            "cat ~/.psql_history",
            "cat ~/.mysql_history",
            "cat ~/.node_repl_history",
            "cat ~/.python_history",
            "cat ~/.sqlite_history",
            "cat ~/.rediscli_history",
            "cat ~/.lesshst",
        ],
    )
    def test_emits_shell_history(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:data_read:shell_history" in r.capabilities, (
            f"{cmd!r} did not emit data_read:shell_history; "
            f"got {r.capabilities}"
        )
        # Option A: no read_only:* alongside.
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            # Similar names but not actual history files.
            "echo bash_history is useful",
            "cat foo.bash_history_backup",
            "cat historical_data.csv",
            # Plain log files that contain the word history.
            "ls history.log",
            "tail /var/log/history.log",
        ],
    )
    def test_does_not_fire_on_similar_names(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:data_read:shell_history" not in r.capabilities, (
            f"{cmd!r} should NOT emit data_read:shell_history; "
            f"got {r.capabilities}"
        )


# ── data_read:browser_profile_data ────────────────────────────────────


class TestDataReadBrowserProfileData:
    @pytest.mark.parametrize(
        "cmd",
        [
            # Chromium family (Chrome / Chromium / Brave / Edge / Vivaldi /
            # Arc).  shlex-normalised spaces inside path segments.
            "sqlite3 ~/Library/Application Support/Google/Chrome/Default/"
            "Login Data 'SELECT * FROM logins'",
            "cat ~/Library/Application Support/Google/Chrome/Default/History",
            "cat ~/Library/Application Support/Google/Chrome/Default/Web Data",
            "cat ~/Library/Application Support/Google/Chrome/Default/"
            "Bookmarks",
            "cat ~/Library/Application Support/Google/Chrome/Default/"
            "Top Sites",
            "cat ~/Library/Application Support/Chromium/Default/Login Data",
            "cat ~/Library/Application Support/BraveSoftware/"
            "Brave-Browser/Default/History",
            "cat ~/Library/Application Support/Microsoft Edge/Default/"
            "Login Data",
            "cat ~/Library/Application Support/Vivaldi/Default/Bookmarks",
            # Multi-profile Chrome ('Profile 1' etc.).
            "cat ~/Library/Application Support/Google/Chrome/Profile 1/"
            "Login Data",
            # Firefox profile SQLite stores.
            "cp ~/Library/Application Support/Firefox/Profiles/abc.default/"
            "places.sqlite /tmp/",
            "cat ~/Library/Application Support/Firefox/Profiles/abc.default/"
            "formhistory.sqlite",
            "cat ~/Library/Application Support/Firefox/Profiles/abc.default/"
            "logins.json",
            "cat ~/Library/Application Support/Firefox/Profiles/abc.default/"
            "key4.db",
            "cat ~/Library/Application Support/Firefox/Profiles/abc.default/"
            "signons.sqlite",
        ],
    )
    def test_emits_browser_profile_data(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:data_read:browser_profile_data" in r.capabilities
        ), (
            f"{cmd!r} did not emit data_read:browser_profile_data; "
            f"got {r.capabilities}"
        )
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            # Parent dirs without the sensitive leaf.
            "ls ~/Library/Application Support/Google/Chrome/Default/",
            "ls ~/Library/Application Support/Firefox/Profiles/",
            # Bare phrases with no path context.
            "echo Login Data is a path",
            "echo History channel",
            # A /Firefox/ path that is not a profile subdirectory.
            "cat ~/Library/Application Support/Firefox/installs.ini",
        ],
    )
    def test_does_not_fire_on_non_profile_paths(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:data_read:browser_profile_data" not in r.capabilities
        ), (
            f"{cmd!r} should NOT emit data_read:browser_profile_data; "
            f"got {r.capabilities}"
        )


# ── data_read:messaging_history ──────────────────────────────────────


class TestDataReadMessagingHistory:
    @pytest.mark.parametrize(
        "cmd",
        [
            "cat ~/Library/Messages/chat.db",
            "sqlite3 ~/Library/Messages/chat.db 'SELECT * FROM message'",
            "cp ~/Library/Messages/chat.db /tmp/stolen",
            "ls ~/Library/Messages/Attachments/",
            "ls ~/Library/Group Containers/group.net.whatsapp/",
            "ls ~/Library/Group Containers/group.com.apple.Messages/",
            "ls ~/Library/Application Support/Telegram Desktop/",
            "cat ~/Library/Application Support/Signal/sql/db.sqlite",
            "ls ~/Library/Application Support/Slack/storage/",
            "cat ~/Library/Application Support/discord/Local Storage/"
            "leveldb/000003.log",
        ],
    )
    def test_emits_messaging_history(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:data_read:messaging_history" in r.capabilities
        ), (
            f"{cmd!r} did not emit data_read:messaging_history; "
            f"got {r.capabilities}"
        )
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            # chat.db outside the Messages container is not macOS iMessage
            "ls /tmp/chat.db",
            "cat ~/projects/irc-bot/chat.db",
            # Parent-parent dir without Messages/
            "ls ~/Library/",
        ],
    )
    def test_does_not_fire_outside_messaging_containers(
        self, cmd: str
    ) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:data_read:messaging_history" not in r.capabilities
        ), (
            f"{cmd!r} should NOT emit data_read:messaging_history; "
            f"got {r.capabilities}"
        )


# ── data_read:personal_records ───────────────────────────────────────


class TestDataReadPersonalRecords:
    @pytest.mark.parametrize(
        "cmd",
        [
            "cat ~/Library/Application Support/AddressBook/"
            "AddressBook-v22.abcddb",
            "ls ~/Library/Application Support/AddressBook/",
            "cat ~/Library/Group Containers/group.com.apple.notes/"
            "NoteStore.sqlite",
            "cp ~/Library/Group Containers/group.com.apple.notes/"
            "NoteStore.sqlite /tmp/stolen",
            "ls ~/Library/Mail/V10/",
            "ls ~/Library/Mail/V9/",
            "ls ~/Library/Group Containers/group.com.apple.mail/",
            "ls ~/Library/Application Support/MobileSync/Backup/",
            "ls ~/Pictures/Photos Library.photoslibrary/",
            # Calendar stores (*.calendar suffix).
            "ls ~/Library/Calendars/Work.calendar/",
        ],
    )
    def test_emits_personal_records(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:data_read:personal_records" in r.capabilities
        ), (
            f"{cmd!r} did not emit data_read:personal_records; "
            f"got {r.capabilities}"
        )
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            # Names look similar but not the right container.
            "ls ~/Library/Random/NoteStore.foo",
            "cat AddressBook.README",
            # Library/Mail but not a V<N> store dir.
            "ls ~/Library/Mail/README.txt",
        ],
    )
    def test_does_not_fire_on_non_record_paths(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:data_read:personal_records" not in r.capabilities
        ), (
            f"{cmd!r} should NOT emit data_read:personal_records; "
            f"got {r.capabilities}"
        )


# ── data_read:credential_material (extended) ─────────────────────────


class TestDataReadCredentialMaterialExtended:
    """The existing ``credential_material`` rule covered security /
    keychain / TCC.db; a second rule extends the same suffix to GPG
    secret-key exports, ``~/.gnupg/private-keys-v1.d``, password-manager
    databases (KeePass / 1Password legacy / Bitwarden), and ``cp|mv|
    rsync|scp`` of ``~/.ssh/id_*`` (the direct read of id_rsa is
    already catastrophic via CAT-SSHKEY-*)."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "gpg --export-secret-keys",
            "gpg --export-secret-keys alice@example.com",
            "gpg --export-secret-subkeys",
            "gpg --export-secret-key 0xDEADBEEF",
            "gpg --export-ownertrust",
            "ls ~/.gnupg/private-keys-v1.d/",
            "cat ~/Documents/vault.kdbx",
            "cp ~/Documents/vault.kdbx /tmp/",
            "cat ~/vault.agilekeychain",
            "cat ~/1Password/vault.opvault",
            "ls ~/Library/Group Containers/group.com.bitwarden/",
            # SSH private-key copy/exfil shapes.  (``scp`` of id_* is
            # pattern-catastrophic via CAT-SSHKEY-SCP-001; cp/mv/rsync
            # shapes reach the classifier.)
            "cp ~/.ssh/id_rsa /tmp/leak",
            "rsync -av ~/.ssh/id_ecdsa /tmp/",
            "mv ~/.ssh/id_rsa /tmp/",
        ],
    )
    def test_emits_credential_material(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:data_read:credential_material" in r.capabilities
        ), (
            f"{cmd!r} did not emit data_read:credential_material; "
            f"got {r.capabilities}"
        )
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            # Benign gpg usage.
            "gpg --version",
            "gpg --list-keys",
            "gpg --export",  # public key export, not secret
            "gpg --import keys.gpg",
            # Names look similar but not real.
            "cat foo.gnupg.txt",
            "cat my.kdbx_backup.txt",  # not a real kdbx file
        ],
    )
    def test_does_not_fire_on_benign_gpg(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:data_read:credential_material" not in r.capabilities
        ), (
            f"{cmd!r} should NOT emit data_read:credential_material; "
            f"got {r.capabilities}"
        )


# ── system_mutate:firewall ───────────────────────────────────────────


class TestSystemMutateFirewall:
    @pytest.mark.parametrize(
        "cmd",
        [
            # macOS pfctl
            "pfctl -d",
            "pfctl -e",
            "pfctl -f /etc/pf.conf",
            "pfctl -F all",
            "pfctl -F rules",
            "pfctl -F states",
            # Linux iptables family
            "iptables -F",
            "iptables -X",
            "iptables -Z",
            "iptables -A INPUT -p tcp --dport 22 -j DROP",
            "iptables -I INPUT 1 -s 10.0.0.1 -j DROP",
            "iptables -D INPUT 1",
            "iptables -P INPUT DROP",
            "iptables -N customchain",
            "ip6tables -F",
            "ip6tables -A INPUT -j DROP",
            "iptables-restore < /tmp/rules.v4",
            # nftables
            "nft flush ruleset",
            "nft flush table inet filter",
            "nft add rule inet filter input drop",
            "nft delete chain inet filter forward",
            "nft replace rule inet filter input handle 1 drop",
            # ufw
            "ufw disable",
            "ufw enable",
            "ufw reset",
            "ufw default deny incoming",
            "ufw allow 22",
            "ufw deny from 10.0.0.1",
            "ufw limit ssh",
            "ufw delete allow 22",
            # firewalld
            "firewall-cmd --add-service=ssh",
            "firewall-cmd --remove-port=22/tcp",
            "firewall-cmd --panic-on",
            "firewall-cmd --panic-off",
            "firewall-cmd --reload",
            "firewall-cmd --runtime-to-permanent",
            # macOS Application Firewall
            "socketfilterfw --setglobalstate off",
            "socketfilterfw --setallowsigned off",
            "socketfilterfw --setallowsignedapp off",
            "socketfilterfw --setloggingmode off",
            "socketfilterfw --setblockall on",
            "socketfilterfw --setstealthmode on",
            "socketfilterfw --unblockapp /Applications/Evil.app",
            "socketfilterfw --blockapp /Applications/Browser.app",
            # FreeBSD ipfw
            "ipfw add deny ip from 10.0.0.1 to any",
            "ipfw delete 100",
            "ipfw flush",
            "ipfw disable firewall",
        ],
    )
    def test_emits_firewall(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:firewall" in r.capabilities
        ), (
            f"{cmd!r} did not emit system_mutate:firewall; "
            f"got {r.capabilities}"
        )
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            # Read / list forms stay untagged.
            "pfctl -s rules",
            "pfctl -s info",
            "pfctl -s states",
            "iptables -L",
            "iptables -S",
            "iptables -nvL",
            "iptables-save",
            "ip6tables -L",
            "nft list tables",
            "nft list ruleset",
            "nft list table inet filter",
            "ufw status",
            "ufw status verbose",
            "ufw show added",
            "firewall-cmd --list-all",
            "firewall-cmd --get-default-zone",
            "firewall-cmd --state",
            "socketfilterfw --getglobalstate",
            "socketfilterfw --listapps",
            "socketfilterfw --getloggingmode",
            # Unrelated commands that contain substrings.
            "cat firewall.md",
            "ls firewall/",
            "python test_firewall.py",
        ],
    )
    def test_does_not_fire_on_read_forms(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:firewall" not in r.capabilities
        ), (
            f"{cmd!r} should NOT emit system_mutate:firewall; "
            f"got {r.capabilities}"
        )


# ── system_mutate:hosts_file ─────────────────────────────────────────


class TestSystemMutateHostsFile:
    @pytest.mark.parametrize(
        "cmd",
        [
            'echo "1.2.3.4 evil.example" >> /etc/hosts',
            'echo "1.2.3.4 evil.example" > /etc/hosts',
            "printf '%s\\n' '1.2.3.4 evil' >> /etc/hosts",
            "tee -a /etc/hosts",
            "tee /etc/hosts",
            "cp /tmp/hosts /etc/hosts",
            "mv /tmp/hosts /etc/hosts",
            "install /tmp/hosts /etc/hosts",
            "ln -sf /tmp/hosts /etc/hosts",
            "sed -i 's/foo/bar/' /etc/hosts",
            "sed -i.bak 's/foo/bar/' /etc/hosts",
            "python -c \"open('/etc/hosts','a').write('1.2.3.4 evil\\n')\"",
            "perl -i -pe 's/foo/bar/' /etc/hosts",
        ],
    )
    def test_emits_hosts_file(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:hosts_file" in r.capabilities
        ), (
            f"{cmd!r} did not emit system_mutate:hosts_file; "
            f"got {r.capabilities}"
        )
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            "cat /etc/hosts",
            "grep evil /etc/hosts",
            "diff /etc/hosts /tmp/hosts",
            "sed 's/foo/bar/' /etc/hosts",  # no -i = read, stdout only
            "less /etc/hosts",
            "head /etc/hosts",
            "wc -l /etc/hosts",
        ],
    )
    def test_does_not_fire_on_hosts_reads(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:hosts_file" not in r.capabilities
        ), (
            f"{cmd!r} should NOT emit system_mutate:hosts_file; "
            f"got {r.capabilities}"
        )


# ── system_mutate:privilege_config ───────────────────────────────────


class TestSystemMutatePrivilegeConfig:
    @pytest.mark.parametrize(
        "cmd",
        [
            "visudo",
            'echo "alice ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers',
            "echo 'alice' > /etc/sudoers.d/alice",
            "cp /tmp/wheel /etc/sudoers.d/wheel",
            "install -m 0440 /tmp/wheel /etc/sudoers.d/wheel",
            "mv /tmp/alice /etc/sudoers.d/alice",
            "tee -a /etc/sudoers",
            "sed -i 's/root/alice/' /etc/passwd",
            "sed -i 's/x/y/' /etc/shadow",
            "sed -i 's/foo/bar/' /etc/gshadow",
            "sed -i 's/foo/bar/' /etc/group",
        ],
    )
    def test_emits_privilege_config(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:privilege_config" in r.capabilities
        ), (
            f"{cmd!r} did not emit system_mutate:privilege_config; "
            f"got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            # visudo syntax-check read forms.
            "visudo -c",
            "visudo -cf /tmp/sudoers.test",
            # Plain reads of privileged config files.
            "cat /etc/sudoers",
            "cat /etc/sudoers.d/wheel",
            "cat /etc/passwd",
            "cat /etc/shadow",
            "cat /etc/group",
            "ls /etc/sudoers.d/",
            "ls /etc/pam.d/",
            # sed without -i is read (stdout-only transformation).
            "sed 's/root/alice/' /etc/passwd",
        ],
    )
    def test_does_not_fire_on_privileged_reads(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:privilege_config" not in r.capabilities
        ), (
            f"{cmd!r} should NOT emit system_mutate:privilege_config; "
            f"got {r.capabilities}"
        )


class TestPrivilegeConfigCatastrophicOverlap:
    """Several privileged-file mutation shapes are caught upstream by
    the catastrophic pattern layer and never reach the classifier.
    This test pins the cross-layer invariant so a pattern-set
    regression cannot silently shift any of these shapes into the
    classifier-tag lane without the test noticing.

    - ``chmod 777 /etc/shadow``: SYSD-001 (world-writable on system
      root).
    - Writes that land at ``/etc/pam.d/<file>``: pattern layer treats
      any mutation of PAM config as catastrophic.
    """

    @pytest.mark.parametrize(
        "cmd",
        [
            "chmod 777 /etc/shadow",
            "echo 'auth required pam_evil.so' >> /etc/pam.d/sudo",
            "cp /tmp/sudo.pam /etc/pam.d/sudo",
        ],
    )
    def test_privilege_shapes_stay_catastrophic(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert r.verdict is Verdict.CATASTROPHIC, (
            f"{cmd!r} expected CATASTROPHIC; got {r.verdict}"
        )


# ── system_mutate:user_account ───────────────────────────────────────


class TestSystemMutateUserAccount:
    @pytest.mark.parametrize(
        "cmd",
        [
            # macOS
            "dseditgroup -o edit -a attacker -t user admin",
            "dseditgroup -o create -n . evilgroup",
            "dseditgroup -o delete -n . evilgroup",
            "pwpolicy -u alice -setpolicy 'minChars=4'",
            "pwpolicy -u alice -setaccountpolicies /tmp/policy.plist",
            "pwpolicy -clearaccountpolicies",
            "pwpolicy -resetpolicy",
            "pwpolicy -u alice -disableuser",
            "pwpolicy -u alice -enableuser",
            "sysadminctl -addUser bob -password pw",
            "sysadminctl -deleteUser alice",
            "sysadminctl -resetPasswordFor alice -newPassword newpw",
            "sysadminctl -secureTokenOn bob -password pw",
            "sysadminctl -secureTokenOff alice -password pw",
            # Linux
            "useradd newuser",
            "useradd -m -s /bin/bash newuser",
            "usermod -aG wheel alice",
            "userdel alice",
            "adduser alice",
            "deluser alice",
            "groupadd wheel",
            "groupmod -n admins wheel",
            "groupdel wheel",
            "addgroup wheel",
            "delgroup wheel",
            "chpasswd",
            "newusers",
            # passwd <other user>.  (``sudo passwd bob`` is pattern-
            # catastrophic via a sudo-account-mutation rule.)
            "passwd alice",
        ],
    )
    def test_emits_user_account(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:user_account" in r.capabilities
        ), (
            f"{cmd!r} did not emit system_mutate:user_account; "
            f"got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            # Reads.
            "id alice",
            "id",
            "groups alice",
            "groups",
            "finger alice",
            "who",
            "last | head",
            # Plain passwd (own-password, interactive).
            "passwd",
            # dscl reads — these go through auth_authority or nothing.
            "dscl . -list /Users",
            "dscl . -read /Users/alice UniqueID",
            # /etc/passwd file reads (handled by filesystem_read).
            "cat /etc/passwd",
            # Tool names with an identifier suffix (word boundary stops
            # the match).
            "passwd_generator --length 32",
            # NOTE: commands where the tool name appears as an argument
            # to ``echo`` (e.g. ``echo 'useradd this to your script'``)
            # DO emit the tag today — shlex strips the quotes, leaving a
            # bare ``useradd`` token that the regex matches.  Treating
            # this as an acceptable FP rather than a correctness bug:
            # the classifier operates on the shlex-normalised string,
            # not the shell AST, so quoted argv content is
            # indistinguishable from command position.
        ],
    )
    def test_does_not_fire_on_reads_or_substring_lookalikes(
        self, cmd: str
    ) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:user_account" not in r.capabilities
        ), (
            f"{cmd!r} should NOT emit system_mutate:user_account; "
            f"got {r.capabilities}"
        )


class TestUserAccountCatastrophicOverlap:
    """``dscl . -passwd`` / ``dscl . -delete /Users/X`` /
    ``dscl . -append`` / ``dscl . -create`` are already caught as
    catastrophic via IF-DSCL-ACCOUNT-001 / MAC-DS-001.  Cross-layer
    test: these must STAY catastrophic so the policy story remains
    "these never ALLOW" regardless of whether deny_capabilities is
    configured."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "dscl . -passwd /Users/alice newpw",
            "dscl . -delete /Users/alice",
            "dscl . -append /Users/alice UniqueID 0",
            "dscl . -create /Users/evil UserShell /bin/bash",
        ],
    )
    def test_dscl_account_mutations_stay_catastrophic(
        self, cmd: str
    ) -> None:
        r = inspect_command(cmd)
        assert r.verdict is Verdict.CATASTROPHIC, (
            f"{cmd!r} expected CATASTROPHIC; got {r.verdict}"
        )


# ── system_mutate:remote_access ──────────────────────────────────────


class TestSystemMutateRemoteAccess:
    @pytest.mark.parametrize(
        "cmd",
        [
            "systemsetup -setremotelogin on",
            "systemsetup -setremoteappleevents on",
            "systemsetup -setwakeonnetworkaccess on",
            "systemsetup -setwakeonmodem on",
            "systemsetup -setcomputersleep never",
            "systemsetup -setdisplaysleep 5",
            "systemsetup -setharddisksleep 10",
            "systemsetup -setrestartfreeze on",
            "systemsetup -setrestartpoweron on",
            "systemsetup -setallowpowerbuttontosleepcomputer off",
            "systemsetup -setstartupdisk /Volumes/Evil",
            "systemsetup -setdisableloginchime on",
        ],
    )
    def test_emits_remote_access(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:remote_access" in r.capabilities
        ), (
            f"{cmd!r} did not emit system_mutate:remote_access; "
            f"got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            # -get* read forms stay untagged.
            "systemsetup -getremotelogin",
            "systemsetup -getcomputersleep",
            "systemsetup -getdisplaysleep",
            "systemsetup -getstartupdisk",
            "systemsetup -getremoteappleevents",
            # Other systemsetup surfaces (time_sync family) keep their
            # own tag, not this one.
            "systemsetup -setusingnetworktime on",
            "systemsetup -setnetworktimeserver time.apple.com",
        ],
    )
    def test_does_not_fire_on_non_remote_access_surfaces(
        self, cmd: str
    ) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:remote_access" not in r.capabilities
        ), (
            f"{cmd!r} should NOT emit system_mutate:remote_access; "
            f"got {r.capabilities}"
        )


# ── system_mutate:disk_encryption ────────────────────────────────────


class TestSystemMutateDiskEncryption:
    @pytest.mark.parametrize(
        "cmd",
        [
            "fdesetup enable",
            "fdesetup disable",
            "fdesetup add -usertoadd alice",
            "fdesetup remove -user alice",
            "fdesetup changerecovery -personal",
            "fdesetup sync",
            "fdesetup authrestart",
        ],
    )
    def test_emits_disk_encryption(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:disk_encryption" in r.capabilities
        ), (
            f"{cmd!r} did not emit system_mutate:disk_encryption; "
            f"got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            "fdesetup status",
            "fdesetup list",
            "fdesetup isactive",
            "fdesetup haspersonalrecoverykey",
            "fdesetup hasinstitutionalrecoverykey",
            "fdesetup usingrecoverykey",
        ],
    )
    def test_does_not_fire_on_fdesetup_reads(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:disk_encryption" not in r.capabilities
        ), (
            f"{cmd!r} should NOT emit system_mutate:disk_encryption; "
            f"got {r.capabilities}"
        )


# ── system_mutate:kernel_tunable ─────────────────────────────────────


class TestSystemMutateKernelTunable:
    @pytest.mark.parametrize(
        "cmd",
        [
            "sysctl -w kernel.randomize_va_space=0",
            "sysctl -w net.ipv4.ip_forward=1",
            "sysctl kernel.randomize_va_space=0",
            "sysctl net.core.rmem_max=16777216",
            "sysctl -p",
            "sysctl -p /etc/sysctl.d/99-evil.conf",
            "echo 0 > /proc/sys/kernel/randomize_va_space",
            "echo 1 >> /proc/sys/net/ipv4/ip_forward",
            "tee /proc/sys/kernel/printk",
        ],
    )
    def test_emits_kernel_tunable(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:kernel_tunable" in r.capabilities
        ), (
            f"{cmd!r} did not emit system_mutate:kernel_tunable; "
            f"got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            # sysctl reads — covered by read_only:system_info.
            "sysctl kernel.randomize_va_space",
            "sysctl -a",
            "sysctl -n kernel.version",
            "sysctl hw.ncpu",
            # /proc/sys reads are plain filesystem reads.
            "cat /proc/sys/kernel/randomize_va_space",
        ],
    )
    def test_does_not_fire_on_sysctl_reads(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:kernel_tunable" not in r.capabilities
        ), (
            f"{cmd!r} should NOT emit system_mutate:kernel_tunable; "
            f"got {r.capabilities}"
        )


# ── system_mutate:persistence ────────────────────────────────────────


class TestSystemMutatePersistence:
    """The catastrophic pattern IF-AT-SCHEDULE-001 already catches the
    numeric-time ``at`` shapes (``at now``, ``at now + N minute``,
    ``at 3pm``, ``at 16:30 tomorrow``, ``at -f file now``).  This tag
    covers the natural-language shapes that pattern misses
    (``at noon`` / ``at teatime`` / ``at tomorrow`` / etc.) and the
    AppleScript login-item persistence shape via ``osascript`` +
    ``System Events`` + ``login item``."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "at noon",
            "at noon tomorrow",
            "at teatime",
            "at today",
            "at tomorrow",
            "at midnight",
            'osascript -e \'tell app "System Events" to make '
            'login item at end with properties {path:"/tmp/evil"}\'',
            'osascript -e \'tell application "System Events" to make '
            'new login item at end\'',
        ],
    )
    def test_emits_persistence(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:persistence" in r.capabilities
        ), (
            f"{cmd!r} did not emit system_mutate:persistence; "
            f"got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            # at read forms.
            "at -l",
            "at -c 1",
            "atq",
            "atrm 1",
            # Benign osascript (no login-item shape).
            'osascript -e \'display notification "hi"\'',
            'osascript -e \'tell app "Finder" to empty trash\'',
            # System Events usage without login item.
            'osascript -e \'tell app "System Events" to keystroke "a"\'',
        ],
    )
    def test_does_not_fire_on_at_reads_or_benign_osascript(
        self, cmd: str
    ) -> None:
        r = inspect_command(cmd)
        assert (
            "capability:system_mutate:persistence" not in r.capabilities
        ), (
            f"{cmd!r} should NOT emit system_mutate:persistence; "
            f"got {r.capabilities}"
        )


class TestPersistenceCatastrophicOverlap:
    """The numeric-time ``at`` shapes are pattern-catastrophic.
    Cross-layer test: these must STAY catastrophic regardless of
    classifier tag presence."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "at now",
            "at now + 1 minute",
            "at now + 5 hour",
            "at -f /tmp/evil.sh now",
            "at 3pm",
            "at 3:00pm",
            "at 3am",
            "at 1630",
            "at 16:30 tomorrow",
        ],
    )
    def test_at_numeric_shapes_stay_catastrophic(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert r.verdict is Verdict.CATASTROPHIC, (
            f"{cmd!r} expected CATASTROPHIC; got {r.verdict}"
        )


# ── Option-A coverage for the new tags ───────────────────────────────


class TestOptionASuppressionExtendedTaxonomy:
    """Re-assert the Option-A contract across the new suffixes: any
    command that emits a ``data_read:*`` or ``system_mutate:*`` tag
    must NOT emit any ``read_only:*`` tag on the same command.  This
    is what keeps the consumer-side read-only fast-path from silently
    licensing sensitive reads / host mutations."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "cat ~/.bash_history",
            "cat ~/Library/Application Support/Google/Chrome/Default/"
            "History",
            "cat ~/Library/Messages/chat.db",
            "cat ~/Library/Group Containers/group.com.apple.notes/"
            "NoteStore.sqlite",
            "ls ~/.gnupg/private-keys-v1.d/",
            "cp ~/Documents/vault.kdbx /tmp/",
            "cp ~/.ssh/id_ed25519 /tmp/",
            "pfctl -F all",
            "iptables -A INPUT -j DROP",
            "ufw disable",
            "echo 'evil' >> /etc/hosts",
            "visudo",
            "useradd bob",
            # (``systemsetup -setremotelogin on`` is NEEDS_REVIEW via a
            # pre-existing pattern; ``-setcomputersleep`` stays SAFE.)
            "systemsetup -setcomputersleep never",
            "fdesetup disable",
            "sysctl -w kernel.randomize_va_space=0",
            "at noon tomorrow",
        ],
    )
    def test_new_tags_suppress_read_only(self, cmd: str) -> None:
        r = inspect_command(cmd)
        caps = r.capabilities
        has_sensitive = any(
            c.startswith("capability:data_read:")
            or c.startswith("capability:system_mutate:")
            for c in caps
        )
        assert has_sensitive, (
            f"{cmd!r} should have at least one data_read:*/system_mutate:* "
            f"tag; got {caps}"
        )
        assert not any(
            c.startswith("capability:read_only:") for c in caps
        ), (
            f"{cmd!r} emitted a read_only:* tag; Option A must suppress. "
            f"got {caps}"
        )
        assert r.verdict is Verdict.SAFE
