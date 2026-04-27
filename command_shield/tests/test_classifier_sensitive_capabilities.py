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
        ],
    )
    def test_sensitive_tag_does_not_change_verdict(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert r.verdict is Verdict.SAFE, (
            f"{cmd!r} was expected SAFE (tags are advisory); "
            f"got verdict={r.verdict}, capabilities={r.capabilities}"
        )
