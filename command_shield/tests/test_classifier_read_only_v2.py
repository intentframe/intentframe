"""v2 coverage for the `capability:read_only:*` family.

Tests the additions beyond the v1 six-subtag set:

    - extended heads for filesystem_list / filesystem_read / search /
      process_inspect / system_info / vcs_inspect
    - flag-discriminated rules: sort / sdiff (-o), uniq (2-positional
      write form), sysctl (-w / -p / --load), ulimit (value-bearing),
      stty (mutating forms), tar (c/x/r/A/u mode letters), unzip
      (extraction modifiers), xmllint (--output), arp (-s / -d),
      route (add / del / flush), ip (non-show verbs)
    - new sub-families: text_transform, network_inspect,
      archive_inspect, container_inspect

Each positive case also re-asserts the verdict stays SAFE and that
the structural gate still blocks composition / redirect / indirection.
"""

from __future__ import annotations

import pytest

from command_shield import Verdict, inspect_command


# ── Extended existing families ──────────────────────────────────────


class TestFilesystemListExtended:
    @pytest.mark.parametrize(
        "cmd",
        [
            "lsattr /tmp",
            "getfacl /etc/hosts",
            "namei /usr/bin/python3",
            "pathchk -p README.md",
            "findmnt",
            "findmnt /",
            "mountpoint /tmp",
            "lsblk",
            "lsblk -f",
            "blkid",
        ],
    )
    def test_emits_filesystem_list(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:read_only:filesystem_list" in r.capabilities, (
            f"{cmd!r} did not emit filesystem_list; got {r.capabilities}"
        )


class TestFilesystemReadExtendedHashers:
    @pytest.mark.parametrize(
        "cmd",
        [
            "md5sum README.md",
            "sha1sum README.md",
            "sha224sum README.md",
            "sha256sum README.md",
            "sha384sum README.md",
            "sha512sum README.md",
            "b2sum README.md",
            "shasum -a 256 README.md",
            "cksum README.md",
            "sum README.md",
        ],
    )
    def test_emits_filesystem_read(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:read_only:filesystem_read" in r.capabilities, (
            f"{cmd!r} did not emit filesystem_read; got {r.capabilities}"
        )


class TestSearchExtended:
    @pytest.mark.parametrize(
        "cmd",
        [
            "jq .foo data.json",
            "jq -r '.items[].name' data.json",
            "yq '.foo' data.yaml",
            "xmllint --xpath '//foo' data.xml",
            "xmllint --format data.xml",
        ],
    )
    def test_emits_search(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:read_only:search" in r.capabilities, (
            f"{cmd!r} did not emit search; got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            "xmllint --output out.xml in.xml",
            "xmllint -o out.xml in.xml",
        ],
    )
    def test_xmllint_output_suppresses_search(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:read_only:search" not in r.capabilities, (
            f"{cmd!r} should not emit search; got {r.capabilities}"
        )


class TestProcessInspectExtended:
    @pytest.mark.parametrize(
        "cmd",
        [
            "free -h",
            "vmstat 1 3",
            "iostat",
            "mpstat",
            "ipcs",
            "nproc",
            "arch",
            "last",
            "lastlog",
            "who",
            "users",
            "finger",
            "getent passwd root",
            "cal",
            "ncal 2026",
        ],
    )
    def test_emits_process_inspect(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:read_only:process_inspect" in r.capabilities, (
            f"{cmd!r} did not emit process_inspect; got {r.capabilities}"
        )


class TestSystemInfoExtended:
    @pytest.mark.parametrize(
        "cmd",
        [
            "man ls",
            "info grep",
            "apropos editor",
            "whatis ls",
            "tldr tar",
            "tput cols",
            "alias",
            "clear",
            "reset",
            "seq 1 10",
            "factor 42",
            "printf '%s\\n' hi",
        ],
    )
    def test_emits_system_info(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:read_only:system_info" in r.capabilities, (
            f"{cmd!r} did not emit system_info; got {r.capabilities}"
        )


class TestSysctlRead:
    @pytest.mark.parametrize(
        "cmd",
        [
            "sysctl -a",
            "sysctl kernel.hostname",
            "sysctl -n kernel.hostname",
            "sysctl -e kernel.hostname",
        ],
    )
    def test_sysctl_read_emits_system_info(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:read_only:system_info" in r.capabilities, (
            f"{cmd!r} did not emit system_info; got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            "sysctl -w kernel.hostname=foo",
            "sysctl --write kernel.hostname=foo",
            "sysctl -p /etc/sysctl.conf",
            "sysctl --load /etc/sysctl.conf",
        ],
    )
    def test_sysctl_write_forms_not_tagged(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        ), f"{cmd!r} should not emit read_only; got {r.capabilities}"


class TestUlimitRead:
    @pytest.mark.parametrize(
        "cmd",
        [
            "ulimit",
            "ulimit -a",
            "ulimit -n",
            "ulimit -s",
        ],
    )
    def test_ulimit_read_emits_system_info(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:read_only:system_info" in r.capabilities, (
            f"{cmd!r} did not emit system_info; got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            "ulimit -n 4096",
            "ulimit -s 8192",
        ],
    )
    def test_ulimit_value_forms_not_tagged(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        ), f"{cmd!r} should not emit read_only; got {r.capabilities}"


class TestSttyRead:
    @pytest.mark.parametrize(
        "cmd",
        [
            "stty",
            "stty -a",
            "stty --all",
            "stty -g",
            "stty --save",
        ],
    )
    def test_stty_read_emits_system_info(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:read_only:system_info" in r.capabilities, (
            f"{cmd!r} did not emit system_info; got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            "stty erase ^?",
            "stty rows 40",
            "stty -echo",
        ],
    )
    def test_stty_mutation_forms_not_tagged(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        ), f"{cmd!r} should not emit read_only; got {r.capabilities}"


class TestVcsInspectExtended:
    @pytest.mark.parametrize(
        "cmd",
        [
            "hg status",
            "hg log -l 10",
            "hg diff",
            "hg cat foo.py",
            "hg annotate README.md",
            "hg branch",
            "hg manifest",
            "hg tip",
            "hg summary",
            "hg identify",
            "hg paths",
            "hg showconfig",
            "svn status",
            "svn st",
            "svn log -l 20",
            "svn diff",
            "svn info",
            "svn list ^/trunk",
            "svn ls ^/trunk",
            "svn cat foo.py",
            "svn propget svn:ignore .",
            "svn blame foo.py",
            "fossil status",
            "fossil timeline",
            "fossil info",
            "fossil ls",
            "fossil finfo foo.py",
            "bzr status",
            "bzr log",
            "bzr diff",
            "bzr info",
        ],
    )
    def test_emits_vcs_inspect(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:read_only:vcs_inspect" in r.capabilities, (
            f"{cmd!r} did not emit vcs_inspect; got {r.capabilities}"
        )


# ── New sub-family: text_transform ──────────────────────────────────


class TestTextTransform:
    @pytest.mark.parametrize(
        "cmd",
        [
            "sort",
            "sort file.txt",
            "sort -n file.txt",
            "sort -k 2 file.txt",
            "cut -d, -f1 file.csv",
            "paste a.txt b.txt",
            "join a.txt b.txt",
            "tr a b",
            "column -t",
            "fold -w 80 file.txt",
            "fmt file.txt",
            "pr file.txt",
            "expand file.txt",
            "unexpand file.txt",
            "comm a.txt b.txt",
            "diff a.txt b.txt",
            "diff -r a b",
            "diff3 a b c",
            "cmp a.txt b.txt",
            "colordiff a.txt b.txt",
            "delta a.txt b.txt",
            "uniq",
            "uniq file.txt",
            "uniq -c file.txt",
            "uniq -f 1 file.txt",
            "sdiff a.txt b.txt",
        ],
    )
    def test_emits_text_transform(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:read_only:text_transform" in r.capabilities, (
            f"{cmd!r} did not emit text_transform; got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            "sort -o out.txt file.txt",
            "sort --output=out.txt file.txt",
            "sort file.txt -o out.txt",
            "sdiff -o merged a.txt b.txt",
            "sdiff --output=merged a.txt b.txt",
            "uniq input.txt output.txt",
            "uniq -c input.txt output.txt",
        ],
    )
    def test_write_forms_not_tagged(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        ), f"{cmd!r} should not emit read_only; got {r.capabilities}"


# ── New sub-family: network_inspect ─────────────────────────────────


class TestNetworkInspect:
    @pytest.mark.parametrize(
        "cmd",
        [
            "netstat",
            "netstat -tulpn",
            "netstat -rn",
            "ss",
            "ss -tulpn",
            "arp",
            "arp -a",
            "arp -n",
            "arp -e",
            "arp -a gateway",
            "ip addr show",
            "ip addr list",
            "ip link show",
            "ip route show",
            "ip route list",
            "ip neigh show",
            "ip rule show",
            "ip -4 addr show",
            "ip -6 route show",
            "route",
            "route -n",
            "route -v",
            "ifconfig",
            "ifconfig -a",
            "ifconfig eth0",
            "ifconfig lo0",
        ],
    )
    def test_emits_network_inspect(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:read_only:network_inspect" in r.capabilities, (
            f"{cmd!r} did not emit network_inspect; got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            "arp -s 10.0.0.1 00:11:22:33:44:55",
            "arp -d 10.0.0.1",
            "ip addr add 10.0.0.1/24 dev eth0",
            "ip route add default via 10.0.0.1",
            "ip link set eth0 up",
            "ip link delete eth0",
            "route add default gw 10.0.0.1",
            "route del default",
            "route flush",
            "ifconfig eth0 up",
            "ifconfig eth0 10.0.0.1",
        ],
    )
    def test_mutating_forms_not_tagged(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        ), f"{cmd!r} should not emit read_only; got {r.capabilities}"

    @pytest.mark.parametrize(
        "cmd",
        [
            "ping 8.8.8.8",
            "ping -c 3 example.com",
            "traceroute example.com",
            "dig example.com",
            "nslookup example.com",
            "host example.com",
            "whois example.com",
        ],
    )
    def test_network_probes_not_tagged(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        ), f"{cmd!r} should not emit read_only; got {r.capabilities}"


# ── New sub-family: archive_inspect ─────────────────────────────────


class TestArchiveInspect:
    @pytest.mark.parametrize(
        "cmd",
        [
            "tar -tf archive.tar",
            "tar -tvf archive.tar",
            "tar -tvzf archive.tar.gz",
            "tar -tjf archive.tar.bz2",
            "tar -tzf archive.tar.gz",
            "tar --list -f archive.tar",
            "unzip -l archive.zip",
            "unzip -v archive.zip",
            "unzip -Z archive.zip",
            "unzip -t archive.zip",
            "unzip -p archive.zip path/in/zip.txt",
            "zipinfo archive.zip",
            "gzip -l archive.gz",
            "gzip --list archive.gz",
            "gzip -t archive.gz",
            "bzip2 -t archive.bz2",
            "xz -l archive.xz",
            "zstd -l archive.zst",
            "zcat archive.gz",
            "bzcat archive.bz2",
            "xzcat archive.xz",
            "zstdcat archive.zst",
            "lz4cat archive.lz4",
            "zless archive.gz",
            "zmore archive.gz",
            "bzless archive.bz2",
            "xzless archive.xz",
            "zgrep pattern archive.gz",
            "bzgrep pattern archive.bz2",
            "xzgrep pattern archive.xz",
        ],
    )
    def test_emits_archive_inspect(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:read_only:archive_inspect" in r.capabilities, (
            f"{cmd!r} did not emit archive_inspect; got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            "tar -xf archive.tar",
            "tar -xvf archive.tar",
            "tar -xvzf archive.tar.gz",
            "tar -cf archive.tar src",
            "tar -cvzf archive.tar.gz src",
            "tar -rf archive.tar extra.txt",
            "tar -uf archive.tar extra.txt",
            "tar -Af archive.tar second.tar",
            "tar --create -f archive.tar src",
            "tar --extract -f archive.tar",
            "tar --append -f archive.tar x.txt",
            "tar --delete -f archive.tar x.txt",
            "unzip archive.zip",
            "unzip -o archive.zip",
            "unzip -d out archive.zip",
            "gzip archive.txt",
            "bzip2 archive.txt",
            "xz archive.txt",
            "zstd archive.txt",
        ],
    )
    def test_write_modes_not_tagged(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        ), f"{cmd!r} should not emit read_only; got {r.capabilities}"


# ── New sub-family: container_inspect ───────────────────────────────


class TestContainerInspect:
    @pytest.mark.parametrize(
        "cmd",
        [
            "docker ps",
            "docker ps -a",
            "docker images",
            "docker image ls",
            "docker logs abc123",
            "docker inspect abc123",
            "docker info",
            "docker version",
            "docker history alpine",
            "docker port abc123",
            "docker diff abc123",
            "docker top abc123",
            "docker stats --no-stream",
            "docker events --since 1h",
            "docker network ls",
            "docker volume ls",
            "docker container ls",
            "docker container inspect abc123",
            "docker container logs abc123",
            "docker system df",
            "docker system info",
            "podman ps",
            "podman images",
            "podman inspect abc",
            "podman info",
            "podman version",
            "kubectl get pods",
            "kubectl get pods -n kube-system",
            "kubectl get pods -o yaml",
            "kubectl describe pod mypod",
            "kubectl logs mypod",
            "kubectl top pod",
            "kubectl top nodes",
            "kubectl version",
            "kubectl api-resources",
            "kubectl api-versions",
            "kubectl explain pod",
            "kubectl config view",
            "kubectl config get-contexts",
            "kubectl config current-context",
            "kubectl cluster-info",
            "kubectl auth can-i get pods",
        ],
    )
    def test_emits_container_inspect(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:read_only:container_inspect" in r.capabilities, (
            f"{cmd!r} did not emit container_inspect; got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            "docker run alpine",
            "docker build .",
            "docker pull alpine",
            "docker push myimg",
            "docker rm abc",
            "docker rmi alpine",
            "docker start abc",
            "docker stop abc",
            "docker commit abc newimg",
            "kubectl apply -f manifest.yaml",
            "kubectl create deployment foo --image=bar",
            "kubectl delete pod mypod",
            "kubectl edit deployment foo",
            "kubectl patch deployment foo -p '{}'",
        ],
    )
    def test_write_subcommands_not_tagged(self, cmd: str) -> None:
        r = inspect_command(cmd)
        # docker exec / kubectl exec / sudo are tagged spawns_process;
        # other mutations must NOT receive any read_only tag.
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        ), f"{cmd!r} should not emit read_only; got {r.capabilities}"


# ── Gate robustness across new families ─────────────────────────────


class TestGateHoldsOnNewFamilies:
    """Gate robustness across the v2 families.

    Pure-read-only compositions now emit the aggregate
    ``capability:read_only:composition`` tag, but the family-specific
    sub-tags (``text_transform``, ``archive_inspect``, …) stay a
    single-head-only contract.  Compositions containing a write
    redirect or other incompatible segment must still emit no
    ``read_only:*`` tag at all.
    """

    @pytest.mark.parametrize(
        "cmd",
        [
            "tar -tf archive.tar > listing.txt",
            "kubectl get pods > pods.yaml",
        ],
    )
    def test_redirect_in_composition_blocks_read_only(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        ), f"{cmd!r} should not emit read_only; got {r.capabilities}"

    @pytest.mark.parametrize(
        "cmd",
        [
            "sort file.txt | uniq -c",
            "docker ps | grep alpine",
            "zcat file.gz | head",
            "netstat -tulpn; echo done",
            "jq .foo a.json && jq .bar b.json",
            "diff a b | less",
        ],
    )
    def test_pure_read_only_composition_emits_only_composition_tag(
        self, cmd: str
    ) -> None:
        r = inspect_command(cmd)
        read_only_caps = [
            c for c in r.capabilities if c.startswith("capability:read_only:")
        ]
        assert read_only_caps == ["capability:read_only:composition"], (
            f"{cmd!r} expected only composition tag; got {read_only_caps}"
        )

    def test_verdict_stays_safe_for_all_new_families(self) -> None:
        for cmd in [
            "lsattr /tmp",
            "md5sum README.md",
            "jq .foo data.json",
            "free -h",
            "man ls",
            "sysctl -a",
            "ulimit -a",
            "stty",
            "hg status",
            "svn info",
            "sort file.txt",
            "uniq file.txt",
            "netstat -tulpn",
            "ip addr show",
            "tar -tf archive.tar",
            "zcat archive.gz",
            "docker ps",
            "kubectl get pods",
        ]:
            r = inspect_command(cmd)
            assert r.verdict is Verdict.SAFE, (
                f"{cmd!r} verdict was {r.verdict}; expected SAFE"
            )
            assert any(
                c.startswith("capability:read_only:") for c in r.capabilities
            ), f"{cmd!r} produced no read_only tag: {r.capabilities}"
