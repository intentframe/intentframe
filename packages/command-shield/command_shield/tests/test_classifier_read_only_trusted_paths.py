"""Trusted absolute-path head normalisation for `capability:read_only:*`
and `capability:network_probe:*` emission.

When the command's head is an absolute path under a trusted system
``bin`` directory (``/bin``, ``/usr/bin``, ``/sbin``, ``/usr/sbin``,
``/usr/local/bin``, ``/usr/local/sbin``, ``/opt/homebrew/bin``,
``/opt/homebrew/sbin``, ``/opt/local/bin``, ``/opt/local/sbin``), the
head is rewritten to its basename before the capability regexes run.
That recovers the common LLM-generated shape where the model emits
``/bin/ls`` instead of ``ls``.

Non-trusted path heads (``/tmp/ls``, ``./ls``, ``~/bin/ls``, any other
absolute path, any relative path) stay rejected — their safety would
depend on who owns the target, which the classifier cannot verify
statically.
"""

from __future__ import annotations

import pytest

from command_shield import Verdict, inspect_command


# ── Positive: trusted paths recover the same tag as the bare head ───


class TestTrustedPathReadOnly:
    """All trusted bin-dir prefixes yield the expected family tag."""

    @pytest.mark.parametrize(
        "cmd, expected",
        [
            # filesystem_list
            ("/bin/ls", "filesystem_list"),
            ("/bin/ls -la", "filesystem_list"),
            ("/bin/ls -la ~", "filesystem_list"),
            ("/usr/bin/ls", "filesystem_list"),
            ("/bin/du -sh .", "filesystem_list"),
            ("/usr/bin/find . -name '*.py'", "filesystem_list"),
            # filesystem_read
            ("/bin/cat /etc/hosts", "filesystem_read"),
            ("/usr/bin/cat README.md", "filesystem_read"),
            ("/usr/bin/head -n 20 file.txt", "filesystem_read"),
            ("/usr/bin/tail -f log.txt", "filesystem_read"),
            ("/usr/bin/wc -l file.py", "filesystem_read"),
            ("/usr/bin/shasum -a 256 file", "filesystem_read"),
            # search
            ("/usr/bin/grep foo /etc/hosts", "search"),
            ("/opt/homebrew/bin/rg pattern file", "search"),
            ("/usr/local/bin/jq .foo data.json", "search"),
            # process_inspect
            ("/bin/ps aux", "process_inspect"),
            ("/usr/bin/lsof -i", "process_inspect"),
            ("/usr/bin/uptime", "process_inspect"),
            # system_info
            ("/usr/bin/whoami", "system_info"),
            ("/usr/bin/env", "system_info"),
            ("/bin/pwd", "system_info"),
            ("/usr/bin/id", "system_info"),
            # vcs_inspect
            ("/usr/bin/git status", "vcs_inspect"),
            ("/opt/homebrew/bin/git log", "vcs_inspect"),
            # text_transform
            ("/usr/bin/sort file.txt", "text_transform"),
            ("/usr/bin/diff a b", "text_transform"),
            # network_inspect
            ("/usr/sbin/netstat -an", "network_inspect"),
            # archive_inspect
            ("/usr/bin/zipinfo archive.zip", "archive_inspect"),
            ("/usr/bin/zcat file.gz", "archive_inspect"),
        ],
    )
    def test_emits_expected_sub_tag(self, cmd: str, expected: str) -> None:
        r = inspect_command(cmd)
        assert f"capability:read_only:{expected}" in r.capabilities, (
            f"{cmd!r} did not emit read_only:{expected}; got {r.capabilities}"
        )
        assert r.verdict is Verdict.SAFE, (
            f"{cmd!r} verdict was {r.verdict}; expected SAFE"
        )


class TestTrustedPathNetworkProbe:
    """Trusted-path normalisation also applies to the network-probe
    family so that ``/bin/ping``, ``/usr/bin/curl``, ``/usr/bin/dig``
    are recognised identically to their bare-head forms."""

    @pytest.mark.parametrize(
        "cmd, expected",
        [
            ("/bin/ping 8.8.8.8", "icmp"),
            ("/sbin/ping6 ::1", "icmp"),
            ("/usr/bin/traceroute 8.8.8.8", "trace"),
            ("/usr/bin/dig example.com", "dns"),
            ("/usr/bin/whois example.com", "whois"),
            ("/usr/bin/curl https://example.com", "http_get"),
            (
                "/usr/bin/curl -X POST -d x=y https://example.com",
                "http_mutate",
            ),
            (
                "/usr/bin/curl -o out.bin https://example.com/file",
                "http_download",
            ),
        ],
    )
    def test_emits_expected_network_probe_sub_tag(
        self, cmd: str, expected: str
    ) -> None:
        r = inspect_command(cmd)
        assert f"capability:network_probe:{expected}" in r.capabilities, (
            f"{cmd!r} did not emit network_probe:{expected}; "
            f"got {r.capabilities}"
        )


# ── Negative: untrusted paths and mis-shapes stay rejected ──────────


class TestUntrustedPathsRejected:
    """Heads outside ``_TRUSTED_BIN_DIRS`` must not receive a
    read-only tag — spoofing is credible in user-writable locations."""

    @pytest.mark.parametrize(
        "cmd",
        [
            # User-writable / non-system-owned paths
            "/tmp/ls",
            "/tmp/ls -la",
            "/Users/foo/bin/ls",
            "/home/foo/bin/ls",
            "/var/tmp/ls",
            "/root/ls",
            "/opt/custom/ls",
            # Relative paths
            "./ls",
            "../ls",
            "bin/ls",
            # Tilde-prefixed (tilde expansion happens at shell time;
            # the classifier cannot confirm $HOME is system-owned)
            "~/bin/ls",
            # Deeper trusted-parent but not a direct bin-dir child
            "/usr/bin/subdir/ls",
            "/bin/subdir/ls",
        ],
    )
    def test_untrusted_path_does_not_emit_read_only(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        ), (
            f"{cmd!r} should NOT emit read_only; got {r.capabilities}"
        )


class TestTrustedPathEvidencePreservesOriginal:
    """The Signal evidence must retain the original command so that
    audit logs remain faithful to what the user/agent actually ran."""

    def test_evidence_is_original_command(self) -> None:
        r = inspect_command("/bin/ls -la /etc")
        tags = [
            s for s in r.signals
            if s.signal_id == "capability:read_only:filesystem_list"
        ]
        assert len(tags) == 1
        assert tags[0].evidence == "/bin/ls -la /etc", (
            f"evidence should be the original command, got {tags[0].evidence!r}"
        )


class TestTrustedPathStillFailsStructuralGate:
    """Trusted-path normalisation must NOT let redirects, pipes, or
    dynamic content slip through — it only rewrites the head."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "/bin/ls > /tmp/out",
            "/bin/ls 2>> err.log",
            "/bin/ls $FOO",
            "/bin/ls $(whoami)",
            "/bin/ls `whoami`",
            "/bin/ls <(echo hi)",
        ],
    )
    def test_structural_hazards_still_block(self, cmd: str) -> None:
        r = inspect_command(cmd)
        # The aggregate composition tag could fire for safe chains;
        # here the command has a write redirect, var expansion, or
        # command substitution so NO read_only tag should appear.
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        ), f"{cmd!r} should NOT emit read_only; got {r.capabilities}"


class TestTrustedPathMixedWithCompositions:
    """Trusted-path heads compose with the other read-only mechanics."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "cd /tmp && /bin/ls -la",
            "/bin/ls -la | /usr/bin/grep foo",
            "/usr/bin/cat /etc/hosts | /usr/bin/wc -l",
            "/bin/ls && /usr/bin/pwd",
            "/usr/bin/ps aux | /usr/bin/grep nginx",
        ],
    )
    def test_trusted_path_in_composition_emits_composition_tag(
        self, cmd: str
    ) -> None:
        r = inspect_command(cmd)
        assert "capability:read_only:composition" in r.capabilities, (
            f"{cmd!r} expected composition tag; got {r.capabilities}"
        )
        assert r.verdict is Verdict.SAFE
