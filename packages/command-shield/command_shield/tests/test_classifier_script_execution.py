"""Coverage for the `capability:script_execution:*` family.

The script_execution family lets policy distinguish *which* interpreter
a command will run.  A python+shell-only profile, for example, denies
``capability:script_execution:{node,ruby,perl,java,...}`` while leaving
``script_execution:python`` and ``script_execution:shell`` untouched.

This module validates:

  - positive emission for every sub-tag we promise the policy layer
    (python / shell / node / ruby / perl / java / go / dotnet / php /
    lua / r / julia / swift / deno_bun / awk / local_binary)
  - inline-eval forms (``-e`` / ``--eval`` / ``-r``) are tagged the
    same as file-form for non-python interpreters, so deny lists hold
  - help / version flags do NOT trigger script-execution tags (no
    ``awk --version`` false positive)
  - tags that should NOT fire don't (``go build`` is compilation,
    ``go install`` is package_install, ``javac`` is compilation,
    ``python -c`` deliberately stays untagged in this family)
"""

from __future__ import annotations

import pytest

from command_shield import inspect_command


def _has_script_exec(cmd: str, suffix: str) -> bool:
    return f"capability:script_execution:{suffix}" in inspect_command(cmd).capabilities


# ── existing rules: regression coverage ─────────────────────────────


class TestPython:
    @pytest.mark.parametrize(
        "cmd",
        [
            "python script.py",
            "python3 script.py",
            "python /opt/app/main.py",
            "python3 -u tests/run.py",
        ],
    )
    def test_emits_python(self, cmd: str) -> None:
        assert _has_script_exec(cmd, "python")


class TestShell:
    @pytest.mark.parametrize(
        "cmd",
        [
            "bash deploy.sh",
            "sh install.sh",
            "zsh setup.zsh",
            "ksh foo.sh",
            "dash run.sh",
        ],
    )
    def test_emits_shell(self, cmd: str) -> None:
        assert _has_script_exec(cmd, "shell")


class TestNodeFile:
    @pytest.mark.parametrize(
        "cmd",
        [
            "node app.js",
            "node app.mjs",
            "node app.cjs",
            "node app.ts",
            "node /srv/app/server.js",
        ],
    )
    def test_emits_node(self, cmd: str) -> None:
        assert _has_script_exec(cmd, "node")


class TestRubyFile:
    @pytest.mark.parametrize(
        "cmd",
        [
            "ruby foo.rb",
            "ruby /opt/app/main.rb",
        ],
    )
    def test_emits_ruby(self, cmd: str) -> None:
        assert _has_script_exec(cmd, "ruby")


class TestPerlFile:
    @pytest.mark.parametrize(
        "cmd",
        [
            "perl foo.pl",
            "perl -w bar.pl",
        ],
    )
    def test_emits_perl(self, cmd: str) -> None:
        assert _has_script_exec(cmd, "perl")


class TestLocalBinary:
    @pytest.mark.parametrize(
        "cmd",
        [
            "./mybinary",
            "./mybinary --flag",
            "./bin/tool arg1 arg2",
            "ls; ./evil",
        ],
    )
    def test_emits_local_binary(self, cmd: str) -> None:
        assert _has_script_exec(cmd, "local_binary")


# ── new rules: long-tail file form ──────────────────────────────────


class TestJava:
    @pytest.mark.parametrize(
        "cmd",
        [
            "java -jar app.jar",
            "java -jar /srv/app.jar",
            "java -cp libs/x.jar com.example.Main",
            "java Foo.class",
            "java -Xmx2g -jar evil.jar",
        ],
    )
    def test_emits_java(self, cmd: str) -> None:
        assert _has_script_exec(cmd, "java"), inspect_command(cmd).capabilities

    def test_javac_does_not_emit_script_exec(self) -> None:
        caps = inspect_command("javac Foo.java").capabilities
        assert "capability:script_execution:java" not in caps
        assert "capability:compilation" in caps


class TestGoRun:
    @pytest.mark.parametrize(
        "cmd",
        [
            "go run main.go",
            "go run ./cmd/server",
            "go run -race ./...",
        ],
    )
    def test_emits_go(self, cmd: str) -> None:
        assert _has_script_exec(cmd, "go")

    def test_go_build_does_not_emit_script_exec(self) -> None:
        caps = inspect_command("go build ./...").capabilities
        assert "capability:script_execution:go" not in caps
        assert "capability:compilation" in caps

    def test_go_install_does_not_emit_script_exec(self) -> None:
        caps = inspect_command("go install golang.org/x/tools/...").capabilities
        assert "capability:script_execution:go" not in caps
        assert "capability:package_install:go" in caps


class TestDotnet:
    @pytest.mark.parametrize(
        "cmd",
        [
            "dotnet app.dll",
            "dotnet /opt/app/app.dll",
            "dotnet --some-flag app.dll",
        ],
    )
    def test_emits_dotnet(self, cmd: str) -> None:
        assert _has_script_exec(cmd, "dotnet")


class TestPhp:
    @pytest.mark.parametrize(
        "cmd",
        [
            "php script.php",
            "php /var/www/index.php",
            "php -d display_errors=1 app.php",
        ],
    )
    def test_emits_php_file(self, cmd: str) -> None:
        assert _has_script_exec(cmd, "php")


class TestLua:
    @pytest.mark.parametrize(
        "cmd",
        [
            "lua exploit.lua",
            "lua /opt/lua/run.lua",
            "lua -e nope.lua",  # `-e` flag form — file-form rule still matches via .lua
        ],
    )
    def test_emits_lua(self, cmd: str) -> None:
        assert _has_script_exec(cmd, "lua")


class TestRscript:
    @pytest.mark.parametrize(
        "cmd",
        [
            "Rscript analysis.R",
            "Rscript pipeline.r",
            "Rscript --vanilla foo.R",
        ],
    )
    def test_emits_r(self, cmd: str) -> None:
        assert _has_script_exec(cmd, "r")


class TestJulia:
    @pytest.mark.parametrize(
        "cmd",
        [
            "julia foo.jl",
            "julia --threads 4 sim.jl",
        ],
    )
    def test_emits_julia(self, cmd: str) -> None:
        assert _has_script_exec(cmd, "julia")


class TestSwift:
    @pytest.mark.parametrize(
        "cmd",
        [
            "swift run",
            "swift run my-target",
            "swift script.swift",
        ],
    )
    def test_emits_swift(self, cmd: str) -> None:
        assert _has_script_exec(cmd, "swift")


class TestDenoBun:
    @pytest.mark.parametrize(
        "cmd",
        [
            "deno run x.ts",
            "deno run --allow-net app.ts",
            "deno test",
            "bun run app.ts",
            "bun run start",
            "bun test",
        ],
    )
    def test_emits_deno_bun(self, cmd: str) -> None:
        assert _has_script_exec(cmd, "deno_bun")


# ── new rules: inline-eval forms for non-python/shell ───────────────


class TestInlineEvalForms:
    @pytest.mark.parametrize(
        "cmd, suffix",
        [
            ("node -e console.log(1)", "node"),
            ("node --eval 1+1", "node"),
            ("ruby -e puts 1", "ruby"),
            ("perl -e print 1", "perl"),
            ("php -r echo 1;", "php"),
        ],
    )
    def test_emits_for_inline_eval(self, cmd: str, suffix: str) -> None:
        assert _has_script_exec(cmd, suffix), inspect_command(cmd).capabilities


class TestAwk:
    @pytest.mark.parametrize(
        "cmd",
        [
            "awk { print $1 } file",
            "awk -F: { print $1 } /etc/passwd",
            "awk BEGIN { system(rm -rf /) }",
            "awk -v x=1 { print x }",
            "gawk { print } file",
            "mawk { print }",
            "awk -f script.awk",
        ],
    )
    def test_emits_awk(self, cmd: str) -> None:
        assert _has_script_exec(cmd, "awk"), inspect_command(cmd).capabilities

    @pytest.mark.parametrize(
        "cmd",
        [
            "awk --version",
            "awk --help",
            "awk -V",
            "awk -h",
            "gawk --version",
        ],
    )
    def test_help_version_not_tagged(self, cmd: str) -> None:
        caps = inspect_command(cmd).capabilities
        assert "capability:script_execution:awk" not in caps, caps


# ── deliberate non-tags ─────────────────────────────────────────────


class TestPythonNotTaggedForInline:
    """python -c is intentionally NOT a script_execution tag.

    Rationale: the python+shell-only profile allows python.  Tagging
    `python -c '...'` with `script_execution:python` would still pass
    that profile (since python isn't in the deny list) but would be
    indistinguishable from `python script.py`.  Profiles that want
    to forbid inline python evaluation can layer that on top.
    """

    @pytest.mark.parametrize(
        "cmd",
        [
            "python -c print(1)",
            "python3 -c import os",
            "python3 --version",
        ],
    )
    def test_python_inline_untagged(self, cmd: str) -> None:
        caps = inspect_command(cmd).capabilities
        assert "capability:script_execution:python" not in caps


class TestNonExecutionUntagged:
    """Allowed-language commands that should NOT produce a denied tag."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "ls -la",
            "cat /etc/hosts",
            "echo hello",
            "pwd",
            "python3 -m pip install requests",  # tagged package_install:pip only
        ],
    )
    def test_no_non_python_shell_script_exec(self, cmd: str) -> None:
        caps = inspect_command(cmd).capabilities
        denied_suffixes = {
            "node", "ruby", "perl", "java", "go", "dotnet",
            "php", "lua", "r", "julia", "swift", "deno_bun",
            "awk", "local_binary",
        }
        leaked = [
            c for c in caps
            if any(c == f"capability:script_execution:{s}" for s in denied_suffixes)
        ]
        assert not leaked, f"{cmd!r} leaked tags: {leaked}"
