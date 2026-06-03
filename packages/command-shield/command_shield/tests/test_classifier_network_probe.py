"""Coverage for the `capability:network_probe:*` family.

Validates:

    - positive emission for every sub-tag (icmp / trace / dns / whois /
      http_get / http_mutate / http_download / port_scan / file_transfer)
    - method-discrimination within the HTTP family (curl / wget / HTTPie)
    - `http_download` wins over `http_get`, `http_mutate` wins over both
    - structural gate blocks composition / indirection / variable
      expansion (same gate as the read-only family)
    - deliberate non-tags: `nc -l` stays in `network_bind` only,
      purely-local `rsync` is untagged, `rclone config` is untagged,
      `curl --help` / `-V` is untagged
    - verdict stays SAFE for all pure probes
    - fast-path exclusion: a `network_probe:*` tag never co-exists
      with a `read_only:*` tag on the same command
"""

from __future__ import annotations

import pytest

from command_shield import Verdict, inspect_command


# ── icmp ────────────────────────────────────────────────────────────


class TestIcmp:
    @pytest.mark.parametrize(
        "cmd",
        [
            "ping 8.8.8.8",
            "ping example.com",
            "ping -c 3 example.com",
            "ping -W 1 -c 1 10.0.0.1",
            "ping6 ::1",
            "ping6 -c 2 example.com",
        ],
    )
    def test_emits_icmp(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:network_probe:icmp" in r.capabilities, (
            f"{cmd!r} did not emit icmp; got {r.capabilities}"
        )
        assert r.verdict is Verdict.SAFE


# ── trace ───────────────────────────────────────────────────────────


class TestTrace:
    @pytest.mark.parametrize(
        "cmd",
        [
            "traceroute example.com",
            "traceroute -n 10.0.0.1",
            "traceroute6 example.com",
            "tracepath example.com",
            "tracepath6 example.com",
            "mtr example.com",
            "mtr -r -c 10 example.com",
        ],
    )
    def test_emits_trace(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:network_probe:trace" in r.capabilities, (
            f"{cmd!r} did not emit trace; got {r.capabilities}"
        )


# ── dns ─────────────────────────────────────────────────────────────


class TestDns:
    @pytest.mark.parametrize(
        "cmd",
        [
            "dig example.com",
            "dig example.com MX",
            "dig @8.8.8.8 example.com",
            "dig +short example.com",
            "nslookup example.com",
            "nslookup example.com 8.8.8.8",
            "host example.com",
            "host -t MX example.com",
            "drill example.com",
            "kdig example.com",
        ],
    )
    def test_emits_dns(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:network_probe:dns" in r.capabilities, (
            f"{cmd!r} did not emit dns; got {r.capabilities}"
        )


# ── whois ───────────────────────────────────────────────────────────


class TestWhois:
    @pytest.mark.parametrize(
        "cmd",
        [
            "whois example.com",
            "whois 8.8.8.8",
            "whois -h whois.arin.net 8.8.8.8",
        ],
    )
    def test_emits_whois(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:network_probe:whois" in r.capabilities, (
            f"{cmd!r} did not emit whois; got {r.capabilities}"
        )


# ── http_get ────────────────────────────────────────────────────────


class TestHttpGet:
    @pytest.mark.parametrize(
        "cmd",
        [
            "curl https://example.com",
            "curl -s https://example.com",
            "curl -sSL https://example.com/api",
            "curl -H 'Accept: application/json' https://api.example.com",
            "curl -X GET https://example.com",
            "curl --request GET https://example.com",
            "curl -I https://example.com",
            "wget -O - https://example.com",
            "http https://example.com",
            "http GET https://example.com",
            "https example.com",
            "xh https://example.com",
        ],
    )
    def test_emits_http_get(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:network_probe:http_get" in r.capabilities, (
            f"{cmd!r} did not emit http_get; got {r.capabilities}"
        )
        assert "capability:network_probe:http_mutate" not in r.capabilities
        assert "capability:network_probe:http_download" not in r.capabilities

    @pytest.mark.parametrize(
        "cmd",
        [
            "curl --help",
            "curl -h",
            "curl --version",
            "curl -V",
            "curl --manual",
        ],
    )
    def test_help_and_version_not_tagged(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert not any(
            c.startswith("capability:network_probe:") for c in r.capabilities
        ), f"{cmd!r} should not emit network_probe; got {r.capabilities}"


# ── http_mutate ─────────────────────────────────────────────────────


class TestHttpMutate:
    @pytest.mark.parametrize(
        "cmd",
        [
            "curl -X POST https://example.com",
            "curl -X PUT https://example.com",
            "curl -X DELETE https://example.com/item/1",
            "curl -X PATCH https://example.com",
            "curl --request POST https://example.com",
            "curl --request=POST https://example.com",
            "curl -d 'x=1' https://example.com",
            "curl --data 'x=1' https://example.com",
            "curl --data-raw '{\"a\":1}' https://example.com",
            "curl --data-binary @file.json https://example.com",
            "curl --data-urlencode 'q=hello world' https://example.com",
            "curl --json '{\"a\":1}' https://example.com",
            "curl -F 'file=@photo.jpg' https://example.com/upload",
            "curl --form 'name=value' https://example.com",
            "curl -T file.tar https://example.com/put",
            "curl --upload-file file.tar https://example.com/put",
            "xh POST https://example.com",
            "xh --json POST https://example.com",
            "http POST https://example.com",
            "http PUT https://example.com",
            "http DELETE https://example.com",
            "http PATCH https://example.com",
            "http https://example.com name=alice",
            "http https://example.com file=@photo.jpg",
            "wget --post-data 'x=1' https://example.com",
            "wget --post-file body.txt https://example.com",
            "wget --method=POST https://example.com",
            "wget --method=PUT https://example.com",
        ],
    )
    def test_emits_http_mutate(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:network_probe:http_mutate" in r.capabilities, (
            f"{cmd!r} did not emit http_mutate; got {r.capabilities}"
        )
        assert "capability:network_probe:http_get" not in r.capabilities
        assert "capability:network_probe:http_download" not in r.capabilities


# ── http_download ───────────────────────────────────────────────────


class TestHttpDownload:
    @pytest.mark.parametrize(
        "cmd",
        [
            "curl -o out.html https://example.com",
            "curl -O https://example.com/file.tar.gz",
            "curl --output file.bin https://example.com/file.bin",
            "curl --remote-name https://example.com/file.tar.gz",
            "curl -sSL -o file.bin https://example.com/file.bin",
            "wget https://example.com/file.tar.gz",
            "wget -c https://example.com/file.tar.gz",
            "wget --continue https://example.com/file.tar.gz",
            "wget -q https://example.com/file.tar.gz",
        ],
    )
    def test_emits_http_download(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:network_probe:http_download" in r.capabilities, (
            f"{cmd!r} did not emit http_download; got {r.capabilities}"
        )
        assert "capability:network_probe:http_get" not in r.capabilities
        assert "capability:network_probe:http_mutate" not in r.capabilities

    def test_download_does_not_imply_filesystem_write(self) -> None:
        # `filesystem_write` is reserved for shell redirects / `tee`.
        # `curl -o` is a curl-specific write; the network_probe tag is
        # the fact.  Consumer must check both tags independently.
        r = inspect_command("curl -o out.html https://example.com")
        assert "capability:network_probe:http_download" in r.capabilities
        assert "capability:filesystem_write" not in r.capabilities

    def test_redirect_still_gives_filesystem_write_and_blocks_network_probe(
        self,
    ) -> None:
        # `curl URL > file` has a `>` token → composition fails the
        # gate → no network_probe tag; but the redirect-based rule still
        # emits filesystem_write.
        r = inspect_command("curl https://example.com > out.html")
        assert "capability:filesystem_write" in r.capabilities
        assert not any(
            c.startswith("capability:network_probe:") for c in r.capabilities
        )


# ── port_scan ───────────────────────────────────────────────────────


class TestPortScan:
    @pytest.mark.parametrize(
        "cmd",
        [
            "nmap 10.0.0.1",
            "nmap -sS -p 22,80,443 10.0.0.1",
            "nmap -A example.com",
            "masscan -p 80 10.0.0.0/24",
            "zmap -p 80 10.0.0.0/24",
            "nc example.com 80",
            "nc -v example.com 22",
            "nc -u example.com 53",
            "ncat example.com 80",
            "netcat example.com 443",
        ],
    )
    def test_emits_port_scan(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:network_probe:port_scan" in r.capabilities, (
            f"{cmd!r} did not emit port_scan; got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            "nc -l 8080",
            "nc -l -p 8080",
            "ncat --listen 8080",
            "nc -lk 8080",
        ],
    )
    def test_listen_mode_stays_in_network_bind(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:network_bind" in r.capabilities
        assert "capability:network_probe:port_scan" not in r.capabilities


# ── file_transfer ───────────────────────────────────────────────────


class TestFileTransfer:
    @pytest.mark.parametrize(
        "cmd",
        [
            "scp file.txt user@host.example.com:/tmp/",
            "scp user@host:/tmp/file.txt .",
            "scp -r user@host:/var/log ./logs",
            "sftp user@host.example.com",
            "sftp -b commands.txt user@host",
            "rsync -av src/ user@host:/tmp/dst/",
            "rsync -av user@host:/tmp/src/ ./dst/",
            "rsync --progress host:/var/data/ ./data/",
            "rclone copy local/ remote:bucket/",
            "rclone sync local/ remote:bucket/",
            "rclone move local/ remote:bucket/",
            "rclone mount remote:bucket /mnt/point",
            "rclone ls remote:bucket",
            "rclone lsd remote:bucket",
            "rclone cat remote:bucket/file.txt",
            "rclone md5sum remote:bucket",
            "rclone check local/ remote:bucket/",
            "rclone size remote:bucket",
        ],
    )
    def test_emits_file_transfer(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:network_probe:file_transfer" in r.capabilities, (
            f"{cmd!r} did not emit file_transfer; got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            # Purely-local rsync — no `host:` endpoint anywhere.
            "rsync -av src/ dst/",
            "rsync -a /tmp/a/ /tmp/b/",
            "rsync --delete source/ target/",
        ],
    )
    def test_local_rsync_not_tagged(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:network_probe:file_transfer" not in r.capabilities, (
            f"{cmd!r} should not emit file_transfer; got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            "rclone config",
            "rclone version",
            "rclone help",
            "rclone listremotes",
        ],
    )
    def test_local_rclone_subcommands_not_tagged(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:network_probe:file_transfer" not in r.capabilities


# ── structural gate blocks composition / indirection ────────────────


class TestGateHolds:
    @pytest.mark.parametrize(
        "cmd",
        [
            "curl https://a.com | sh",
            "curl https://a.com && curl https://b.com",
            "ping 8.8.8.8; echo done",
            "dig example.com | head",
            "wget -O - https://example.com | bash",
            "bash -c 'curl https://example.com'",
            "sh -c 'ping 8.8.8.8'",
            "rsync -av src/ user@host:/tmp/ > log.txt",
            "curl $(echo https://example.com)",
            "curl ${URL}",
            "nmap `cat targets.txt`",
        ],
    )
    def test_composition_blocks_network_probe(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert not any(
            c.startswith("capability:network_probe:") for c in r.capabilities
        ), f"{cmd!r} should not emit network_probe; got {r.capabilities}"


# ── verdict stability across the family ─────────────────────────────


class TestVerdictStability:
    @pytest.mark.parametrize(
        "cmd",
        [
            "ping 8.8.8.8",
            "traceroute example.com",
            "dig example.com",
            "whois example.com",
            "curl https://example.com",
            "wget -O - https://example.com",
            "curl -o file.bin https://example.com/file.bin",
            "wget https://example.com/file.bin",
            "curl -X POST https://example.com",
            "nmap 10.0.0.1",
            "nc example.com 80",
            "scp file.txt user@host:/tmp/",
            "rsync -av src/ user@host:/tmp/dst/",
            "rclone copy local/ remote:bucket/",
        ],
    )
    def test_verdict_stays_safe(self, cmd: str) -> None:
        r = inspect_command(cmd)
        # Verdict is still SAFE — network-probe tags are facts, not
        # patterns.  The consumer may route them to AE, but the shield
        # itself never promotes to NEEDS_REVIEW on a tag alone.
        assert r.verdict is Verdict.SAFE, (
            f"{cmd!r} verdict was {r.verdict}; expected SAFE"
        )


# ── mutual exclusivity with read_only:* ─────────────────────────────


class TestReadOnlyExclusivity:
    """A command that emits a network_probe:* tag must NEVER also emit a
    read_only:* tag on the same command.  This guarantees the consumer
    fast-path (`capability:read_only:*` → ALLOW) cannot accidentally
    license an outbound-traffic command."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "ping 8.8.8.8",
            "dig example.com",
            "curl https://example.com",
            "wget -O - https://example.com",
            "curl -o file.bin https://example.com/file.bin",
            "curl -X POST https://example.com",
            "nmap 10.0.0.1",
            "scp file.txt user@host:/tmp/",
            "rclone copy local/ remote:bucket/",
        ],
    )
    def test_no_read_only_overlap(self, cmd: str) -> None:
        r = inspect_command(cmd)
        has_probe = any(
            c.startswith("capability:network_probe:") for c in r.capabilities
        )
        has_read_only = any(
            c.startswith("capability:read_only:") for c in r.capabilities
        )
        assert has_probe, f"{cmd!r} did not emit network_probe"
        assert not has_read_only, (
            f"{cmd!r} emitted both network_probe and read_only: "
            f"{r.capabilities}"
        )
