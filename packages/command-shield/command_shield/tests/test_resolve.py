"""Tests for resolve.resolve_script — safe, opt-in file reading."""

from __future__ import annotations

import os
from pathlib import Path

from command_shield import Edge, ResolveSession
from command_shield.resolve import ResolveFailure, ResolvedScript, resolve_script


def _ref_edge(path: str, *, language: str = "python") -> Edge:
    return Edge(
        kind="referenced",
        language=language,
        body=None,
        path_arg=path,
        resolvable=True,
        unresolvable_reason=None,
        position=(0, 0),
    )


class TestResolveScript:
    def test_reads_existing_file(self, tmp_path: Path) -> None:
        p = tmp_path / "a.py"
        p.write_text("print(1)\n")
        session = ResolveSession(cwd=str(tmp_path))
        result = resolve_script(_ref_edge("a.py"), session)
        assert isinstance(result, ResolvedScript)
        assert result.path.endswith("a.py")
        assert result.content == b"print(1)\n"
        assert result.truncated is False

    def test_no_session_returns_failure(self) -> None:
        result = resolve_script(_ref_edge("a.py"), None)
        assert isinstance(result, ResolveFailure)
        assert result.reason == "no-session"

    def test_missing_file(self, tmp_path: Path) -> None:
        session = ResolveSession(cwd=str(tmp_path))
        result = resolve_script(_ref_edge("ghost.py"), session)
        assert isinstance(result, ResolveFailure)
        assert result.reason == "stat-failed"

    def test_unsafe_path_with_null(self) -> None:
        session = ResolveSession(cwd="/tmp")
        edge = _ref_edge("a\x00b.py")
        result = resolve_script(edge, session)
        assert isinstance(result, ResolveFailure)
        assert result.reason == "unsafe-path"

    def test_rejects_symlink_by_default(self, tmp_path: Path) -> None:
        real = tmp_path / "real.py"
        real.write_text("print(1)")
        link = tmp_path / "link.py"
        os.symlink(real, link)
        session = ResolveSession(cwd=str(tmp_path))
        result = resolve_script(_ref_edge("link.py"), session)
        assert isinstance(result, ResolveFailure)
        assert result.reason == "symlink"

    def test_follows_symlink_when_opted_in(self, tmp_path: Path) -> None:
        real = tmp_path / "real.py"
        real.write_text("print(1)")
        link = tmp_path / "link.py"
        os.symlink(real, link)
        session = ResolveSession(cwd=str(tmp_path), follow_symlinks=True)
        result = resolve_script(_ref_edge("link.py"), session)
        assert isinstance(result, ResolvedScript)

    def test_rejects_non_regular(self, tmp_path: Path) -> None:
        session = ResolveSession(cwd=str(tmp_path))
        edge = _ref_edge(".")
        result = resolve_script(edge, session)
        assert isinstance(result, ResolveFailure)
        assert result.reason == "not-regular-file"

    def test_allow_roots_blocks_outside(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside.py"
        outside.write_text("x = 1")
        other = tmp_path / "other"
        other.mkdir()
        session = ResolveSession(cwd=str(tmp_path), allow_roots=(str(other),))
        result = resolve_script(_ref_edge("outside.py"), session)
        assert isinstance(result, ResolveFailure)
        assert result.reason == "outside-allow-roots"

    def test_allow_roots_permits_inside(self, tmp_path: Path) -> None:
        inside = tmp_path / "inside.py"
        inside.write_text("x = 1")
        session = ResolveSession(cwd=str(tmp_path), allow_roots=(str(tmp_path),))
        result = resolve_script(_ref_edge("inside.py"), session)
        assert isinstance(result, ResolvedScript)

    def test_truncation(self, tmp_path: Path) -> None:
        p = tmp_path / "big.py"
        p.write_text("x" * 500)
        session = ResolveSession(cwd=str(tmp_path))
        result = resolve_script(_ref_edge("big.py"), session, max_bytes=100)
        assert isinstance(result, ResolvedScript)
        assert result.truncated is True
        assert len(result.content) == 100

    def test_unresolvable_edge(self, tmp_path: Path) -> None:
        session = ResolveSession(cwd=str(tmp_path))
        bad_edge = Edge(
            kind="dynamic",
            language="python",
            body=None,
            path_arg="$X",
            resolvable=False,
            unresolvable_reason="variable-expansion",
            position=(0, 0),
        )
        result = resolve_script(bad_edge, session)
        assert isinstance(result, ResolveFailure)
        assert result.reason == "not-resolvable"
