"""Tests for the `capability:read_only:*` family and `capability:filesystem_write`.

Covers:
    - each read_only family emits on its canonical heads,
    - the structural gate rejects composition / redirect / indirection,
    - destructive flags on otherwise read-only heads suppress emission,
    - `capability:filesystem_write` fires on redirects but not on
      quoted `>` characters and not on `/dev/null`-style sinks,
    - the tag never changes the verdict.
"""

from __future__ import annotations

import pytest

from command_shield import Verdict, inspect_command


class TestReadOnlyFilesystemList:
    @pytest.mark.parametrize(
        "cmd",
        [
            "ls",
            "ls -la",
            "ls -laF /tmp",
            "tree",
            "tree -L 2 src",
            "stat /etc/hosts",
            "file /usr/bin/python3",
            "du -sh .",
            "df -h",
            "find .",
            "find . -name '*.py'",
            "find . -type f -name README",
        ],
    )
    def test_emits_filesystem_list(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:read_only:filesystem_list" in r.capabilities, (
            f"{cmd!r} did not emit read_only:filesystem_list; got {r.capabilities}"
        )
        assert r.verdict is Verdict.SAFE

    @pytest.mark.parametrize(
        "cmd",
        [
            "find . -delete",
            "find . -name '*.tmp' -delete",
            "find . -exec rm {} \\;",
            "find . -execdir cat {} \\;",
            "find . -ok rm {} \\;",
            "find . -fprint out.txt",
        ],
    )
    def test_find_with_destructive_flag_not_emitted(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:read_only:filesystem_list" not in r.capabilities, (
            f"{cmd!r} should not emit read_only; got {r.capabilities}"
        )


class TestReadOnlyFilesystemRead:
    @pytest.mark.parametrize(
        "cmd",
        [
            "cat README.md",
            "cat -n README.md",
            "head -n 20 file.txt",
            "tail -f log.txt",
            "less foo",
            "more foo",
            "wc -l src/main.py",
            "hexdump -C /bin/ls",
            "xxd -s 0 -l 64 /bin/ls",
            "od -c /etc/hosts",
            "nl README.md",
        ],
    )
    def test_emits_filesystem_read(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:read_only:filesystem_read" in r.capabilities, (
            f"{cmd!r} did not emit read_only:filesystem_read; got {r.capabilities}"
        )

    def test_sed_not_in_read_only_family(self) -> None:
        # sed -i writes; we exclude sed entirely from the read-only
        # family rather than trying to whitelist safe sub-flags.
        r = inspect_command("sed 's/a/b/g' file.txt")
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        )

    def test_awk_not_in_read_only_family(self) -> None:
        r = inspect_command("awk '{print $1}' file.txt")
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        )


class TestReadOnlySearch:
    @pytest.mark.parametrize(
        "cmd",
        [
            "grep foo file.txt",
            "grep -r foo src",
            "grep -rn --include='*.py' foo src",
            "egrep 'a|b' file",
            "fgrep literal file",
            "rg foo",
            "rg -n foo src",
            "ack pattern",
        ],
    )
    def test_emits_search(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:read_only:search" in r.capabilities, (
            f"{cmd!r} did not emit read_only:search; got {r.capabilities}"
        )


class TestReadOnlyProcessAndSystem:
    @pytest.mark.parametrize(
        "cmd",
        [
            "ps aux",
            "ps -ef",
            "top -b -n 1",
            "lsof -i :8080",
            "pgrep python",
            "pidof bash",
            "uptime",
            "w",
        ],
    )
    def test_emits_process_inspect(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:read_only:process_inspect" in r.capabilities, (
            f"{cmd!r} did not emit read_only:process_inspect; got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            "uname -a",
            "whoami",
            "id",
            "hostname",
            "date",
            "pwd",
            "env",
            "printenv PATH",
            "echo hello world",
            "which python",
            "whereis git",
            "type ls",
            "history",
            "readlink /usr/bin/python",
            "basename /foo/bar",
            "dirname /foo/bar/baz",
            "realpath .",
        ],
    )
    def test_emits_system_info(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:read_only:system_info" in r.capabilities, (
            f"{cmd!r} did not emit read_only:system_info; got {r.capabilities}"
        )


class TestReadOnlyGit:
    @pytest.mark.parametrize(
        "cmd",
        [
            "git status",
            "git log",
            "git log --oneline -n 20",
            "git diff",
            "git diff HEAD~1",
            "git show HEAD",
            "git branch",
            "git branch -a",
            "git remote -v",
            "git rev-parse HEAD",
            "git ls-files",
            "git describe",
            "git blame README.md",
            "git config --get user.email",
            "git config --list",
        ],
    )
    def test_emits_vcs_inspect(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:read_only:vcs_inspect" in r.capabilities, (
            f"{cmd!r} did not emit read_only:vcs_inspect; got {r.capabilities}"
        )

    def test_git_config_set_not_read_only(self) -> None:
        # Plain `git config user.email foo@bar` writes — no read-only tag.
        r = inspect_command("git config user.email foo@bar")
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        )


class TestReadOnlyGate:
    """The structural gate must reject anything whose composition
    is not wholly read-only, and must NOT emit the specific-family
    sub-tags (filesystem_list / filesystem_read / search / …) for
    any composition — those tags are reserved for bare single-head
    invocations.  Pure-read-only compositions emit the dedicated
    ``capability:read_only:composition`` aggregate tag instead; that
    contract is covered in ``test_classifier_read_only_composition``.
    """

    @pytest.mark.parametrize(
        "cmd",
        [
            "ls & disown",
            "cat foo.py | python -",
            "cat foo.py > /tmp/dest",
            "cat foo.py >> /tmp/dest",
            "cat foo.py 2> /tmp/err",
            "ls > /tmp/out",
            "grep foo file | tee out",
            "echo $(whoami)",
            "echo `whoami`",
            "cat $FILE",
            "cat <(echo hi)",
            "bash -c 'ls'",
            "python -c 'print(1)'",
        ],
    )
    def test_dangerous_composition_blocks_read_only(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        ), f"{cmd!r} should not emit read_only; got {r.capabilities}"

    @pytest.mark.parametrize(
        "cmd",
        [
            "ls | wc -l",
            "ls; echo done",
            "ls && echo done",
            "ls || echo missing",
            "ps aux | grep python",
        ],
    )
    def test_pure_read_only_composition_emits_only_composition_tag(
        self, cmd: str
    ) -> None:
        # These compositions ARE read-only as a whole, so they get the
        # aggregate ``capability:read_only:composition`` tag — but they
        # must NOT receive any specific-family sub-tag, because the
        # family sub-tags are a single-head-only contract.
        r = inspect_command(cmd)
        read_only_caps = [
            c for c in r.capabilities if c.startswith("capability:read_only:")
        ]
        assert read_only_caps == ["capability:read_only:composition"], (
            f"{cmd!r} expected only composition tag; got {read_only_caps}"
        )

    def test_quoted_pipe_in_grep_does_not_block(self) -> None:
        # `grep "foo|bar" file.txt` has the `|` inside quotes — bashlex
        # sees one command, shlex produces no bare `|` token.  The
        # read-only gate should therefore let it through.
        r = inspect_command('grep "foo|bar" file.txt')
        assert "capability:read_only:search" in r.capabilities
        assert "capability:filesystem_write" not in r.capabilities

    def test_read_only_never_changes_verdict(self) -> None:
        r = inspect_command("ls -la")
        assert r.verdict is Verdict.SAFE
        assert "capability:read_only:filesystem_list" in r.capabilities


class TestFilesystemWrite:
    @pytest.mark.parametrize(
        "cmd",
        [
            "echo hi > /tmp/out",
            "echo hi >> /tmp/out.log",
            "echo hi >/tmp/out",
            "ls 2> /tmp/err",
            "ls 2>> /tmp/err.log",
            "ls &> /tmp/all",
            "date | tee /tmp/when",
        ],
    )
    def test_emits_filesystem_write(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:filesystem_write" in r.capabilities, (
            f"{cmd!r} did not emit filesystem_write; got {r.capabilities}"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            "ls > /dev/null",
            "ls 2> /dev/null",
            "ls &> /dev/null",
            "echo hi > /dev/stdout",
            "echo err > /dev/stderr",
            "echo hi > /dev/fd/1",
        ],
    )
    def test_dev_sinks_not_flagged(self, cmd: str) -> None:
        r = inspect_command(cmd)
        assert "capability:filesystem_write" not in r.capabilities, (
            f"{cmd!r} should not emit filesystem_write; got {r.capabilities}"
        )

    def test_quoted_gt_does_not_emit(self) -> None:
        # `grep "a>b" file.txt` has `>` inside quotes → no redirect.
        r = inspect_command('grep "a>b" file.txt')
        assert "capability:filesystem_write" not in r.capabilities

    def test_write_suppresses_read_only(self) -> None:
        # Even though `ls` alone would be filesystem_list, the presence
        # of `> /tmp/x` suppresses read-only and emits filesystem_write.
        r = inspect_command("ls -la > /tmp/out")
        assert "capability:filesystem_write" in r.capabilities
        assert not any(
            c.startswith("capability:read_only:") for c in r.capabilities
        )
