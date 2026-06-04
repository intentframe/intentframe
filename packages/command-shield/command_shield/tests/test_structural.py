"""Tests for normalize() / decompose()."""

from __future__ import annotations

from command_shield import inspect_command
from command_shield.structural import decompose, normalize


class TestNormalize:
    def test_strip_empty_quotes(self) -> None:
        assert "sudo" in normalize('su""do reboot')

    def test_strip_single_quotes(self) -> None:
        assert "sudo" in normalize("s'u'd\"o\" reboot")

    def test_preserves_simple(self) -> None:
        assert normalize("echo hello") == "echo hello"

    def test_catches_obfuscated_sudo_end_to_end(self) -> None:
        assert inspect_command('su""do reboot').is_catastrophic


class TestDecompose:
    def test_returns_triple(self) -> None:
        out = decompose("echo hi && echo bye")
        assert isinstance(out, tuple)
        assert len(out) == 3

    def test_returns_subcommands(self) -> None:
        subs, _sigs, _ind = decompose("echo hi && echo bye")
        assert any("echo hi" in s for s in subs)
        assert any("echo bye" in s for s in subs)

    def test_inline_indirection_surfaced(self) -> None:
        subs, sigs, indirections = decompose("python -c 'print(1)'")
        assert any("print(1)" in p for p in indirections)

    def test_empty_input_no_crash(self) -> None:
        subs, sigs, indirections = decompose("")
        assert not subs
        assert not indirections


class TestParseFailureDoesNotCrash:
    def test_malformed_command(self) -> None:
        r = inspect_command("echo 'unterminated")
        assert r.needs_review or r.verdict.value == "SAFE"

    def test_empty_command(self) -> None:
        assert inspect_command("").verdict.value == "SAFE"

    def test_whitespace_only(self) -> None:
        assert inspect_command("   ").verdict.value == "SAFE"
