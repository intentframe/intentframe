"""Unit tests for ``jarvis_pa.jarvis.tools.memory_get`` and its helper.

``memory_get`` is the only Jarvis tool that reads agent-runtime state
directly from disk (``~/.jarvis/workspace/``) instead of going through
the IntentFrame actor pipeline.  Because it bypasses the guardian's
path checks, the confinement it *does* apply is the only wall between
a compromised LLM and ``/etc/passwd`` — these tests pin down that
wall.

Covered:

- Happy-path read (UTF-8, full file and line ranges).
- Line-slicing edge cases (1-based indexing, out-of-bounds, inversions).
- Path-traversal via ``..``.
- Absolute path escaping the workspace root.
- Symlink escape via ``.resolve()``.
- Non-existent file, directory-not-file, non-UTF-8 bytes.
- End-to-end via ``memory_get.on_invoke_tool`` to verify the
  ``@function_tool`` wrapper plumbs ``config.workspace_dir`` through.

All tests use ``tmp_path``; none touch ``~/.jarvis`` or real Jarvis
state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from agents.tool_context import ToolContext

from jarvis.tools import _read_memory_lines, memory_get


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Fresh, isolated workspace root (absolute, already resolved)."""
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    return root


def _write(root: Path, name: str, content: str) -> Path:
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ═══════════════════════════════════════════════════════════════════════
# Happy-path reads
# ═══════════════════════════════════════════════════════════════════════


class TestHappyPath:
    def test_reads_full_file_when_range_covers_all_lines(self, workspace: Path):
        _write(workspace, "SOUL.md", "alpha\nbeta\ngamma\n")
        out = _read_memory_lines(workspace, "SOUL.md", 1, 3)
        assert out == "alpha\nbeta\ngamma"

    def test_reads_single_line(self, workspace: Path):
        _write(workspace, "MEMORY.md", "alpha\nbeta\ngamma\n")
        out = _read_memory_lines(workspace, "MEMORY.md", 2, 2)
        assert out == "beta"

    def test_reads_nested_path_inside_workspace(self, workspace: Path):
        _write(workspace, "memory/2026-01-15.md", "line1\nline2\nline3")
        out = _read_memory_lines(workspace, "memory/2026-01-15.md", 1, 2)
        assert out == "line1\nline2"

    def test_reads_unicode_content(self, workspace: Path):
        _write(workspace, "USER.md", "café\n日本語\n🚀 rocket")
        out = _read_memory_lines(workspace, "USER.md", 1, 3)
        assert out == "café\n日本語\n🚀 rocket"

    def test_empty_file_returns_empty_string(self, workspace: Path):
        _write(workspace, "empty.md", "")
        assert _read_memory_lines(workspace, "empty.md", 1, 10) == ""


# ═══════════════════════════════════════════════════════════════════════
# Line-slice edge cases
# ═══════════════════════════════════════════════════════════════════════


class TestLineSlicing:
    def test_start_line_zero_clamps_to_first_line(self, workspace: Path):
        _write(workspace, "f.md", "a\nb\nc")
        assert _read_memory_lines(workspace, "f.md", 0, 2) == "a\nb"

    def test_start_line_negative_clamps_to_first_line(self, workspace: Path):
        _write(workspace, "f.md", "a\nb\nc")
        assert _read_memory_lines(workspace, "f.md", -5, 2) == "a\nb"

    def test_end_line_beyond_file_returns_tail(self, workspace: Path):
        _write(workspace, "f.md", "a\nb\nc")
        assert _read_memory_lines(workspace, "f.md", 2, 999) == "b\nc"

    def test_start_greater_than_end_returns_empty(self, workspace: Path):
        _write(workspace, "f.md", "a\nb\nc")
        assert _read_memory_lines(workspace, "f.md", 3, 1) == ""

    def test_range_fully_past_eof_returns_empty(self, workspace: Path):
        _write(workspace, "f.md", "a\nb\nc")
        assert _read_memory_lines(workspace, "f.md", 10, 20) == ""

    def test_trailing_newline_does_not_add_phantom_line(self, workspace: Path):
        # ``str.splitlines()`` drops the trailing empty string, so a file
        # ending in ``\n`` must have the same line count as one without.
        _write(workspace, "f.md", "a\nb\nc\n")
        assert _read_memory_lines(workspace, "f.md", 1, 999) == "a\nb\nc"


# ═══════════════════════════════════════════════════════════════════════
# Path-confinement wall
# ═══════════════════════════════════════════════════════════════════════


class TestPathConfinement:
    def test_dotdot_traversal_rejected(self, workspace: Path):
        outside = workspace.parent / "secret.txt"
        outside.write_text("classified", encoding="utf-8")
        out = _read_memory_lines(workspace, "../secret.txt", 1, 1)
        assert "escapes Jarvis memory workspace" in out
        assert "classified" not in out

    def test_deep_dotdot_traversal_rejected(self, workspace: Path):
        out = _read_memory_lines(
            workspace, "../../../../etc/passwd", 1, 1,
        )
        assert "escapes Jarvis memory workspace" in out

    def test_absolute_path_outside_workspace_rejected(self, workspace: Path, tmp_path: Path):
        outside = tmp_path / "outside.txt"
        outside.write_text("nope", encoding="utf-8")
        # Absolute path: ``workspace_root / "/abs/path"`` collapses to
        # ``/abs/path`` under pathlib semantics, so the resolved target
        # is clearly outside workspace_root.
        out = _read_memory_lines(workspace, str(outside), 1, 1)
        assert "escapes Jarvis memory workspace" in out
        assert "nope" not in out

    def test_symlink_to_outside_rejected(self, workspace: Path, tmp_path: Path):
        outside = tmp_path / "real_secret.txt"
        outside.write_text("secret-bytes", encoding="utf-8")
        link = workspace / "link.md"
        link.symlink_to(outside)

        out = _read_memory_lines(workspace, "link.md", 1, 1)
        assert "escapes Jarvis memory workspace" in out
        assert "secret-bytes" not in out

    def test_symlink_inside_workspace_is_followed(self, workspace: Path):
        real = _write(workspace, "real.md", "inside-ok")
        link = workspace / "alias.md"
        link.symlink_to(real)

        out = _read_memory_lines(workspace, "alias.md", 1, 1)
        assert out == "inside-ok"

    def test_reading_workspace_root_itself_rejects_as_not_file(self, workspace: Path):
        # ``""`` resolves to workspace_root -> exists, but is a directory.
        out = _read_memory_lines(workspace, ".", 1, 1)
        assert "not a file" in out


# ═══════════════════════════════════════════════════════════════════════
# Error surfaces — bad inputs, not-a-file, decoding failures
# ═══════════════════════════════════════════════════════════════════════


class TestErrorSurfaces:
    def test_missing_file_returns_does_not_exist(self, workspace: Path):
        out = _read_memory_lines(workspace, "nope.md", 1, 10)
        assert "does not exist" in out
        assert "nope.md" in out

    def test_directory_returns_not_a_file(self, workspace: Path):
        (workspace / "subdir").mkdir()
        out = _read_memory_lines(workspace, "subdir", 1, 10)
        assert "not a file" in out

    def test_non_utf8_bytes_return_error_not_exception(self, workspace: Path):
        # Latin-1 bytes that are invalid UTF-8 continuation sequences.
        (workspace / "binary.bin").write_bytes(b"\xff\xfe\x00\x01garbage")
        out = _read_memory_lines(workspace, "binary.bin", 1, 1)
        assert out.startswith("Error reading binary.bin:")
        # Surfacing the codec error details to the LLM is intentional —
        # the message should mention either the codec or the byte.
        assert "utf-8" in out.lower() or "0xff" in out.lower() or "decode" in out.lower()


# ═══════════════════════════════════════════════════════════════════════
# End-to-end through the @function_tool wrapper
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class _StubConfig:
    workspace_dir: Path


@dataclass
class _StubAgentContext:
    """Duck-typed stand-in for :class:`jarvis.types.AgentContext`.

    ``memory_get`` only reads ``ctx.context.config.workspace_dir``, so
    we don't need a real ``Actor`` or ``MemorySearcher`` — passing
    ``None`` for them would force us to drop dataclass type hints, so
    we just use a duck-typed stub instead.
    """
    config: _StubConfig
    actor: object = None
    searcher: object = None
    is_sub_agent: bool = False


def _make_tool_context(agent_ctx: _StubAgentContext, payload: str) -> ToolContext:
    """Build the ToolContext the agents SDK's ``on_invoke_tool`` expects.

    The SDK requires ``tool_name``, ``tool_call_id``, and
    ``tool_arguments`` to be explicitly passed — they're normally
    populated by the runner, but tests invoke ``on_invoke_tool``
    directly so we supply stable dummies.
    """
    return ToolContext(
        context=agent_ctx,
        tool_name="memory_get",
        tool_call_id="test-call-id",
        tool_arguments=payload,
    )


class TestFunctionToolWrapper:
    """Exercise the @function_tool wrapper end-to-end.

    This verifies the wrapper correctly computes
    ``workspace_dir / "workspace"`` and that JSON argument parsing
    hands ``path`` / ``start_line`` / ``end_line`` through intact.
    """

    async def test_wrapper_reads_file_via_config_workspace_dir(
        self, tmp_path: Path,
    ):
        jarvis_home = tmp_path / ".jarvis"
        (jarvis_home / "workspace").mkdir(parents=True)
        (jarvis_home / "workspace" / "SOUL.md").write_text(
            "line-a\nline-b\nline-c", encoding="utf-8",
        )

        payload = json.dumps({"path": "SOUL.md", "start_line": 1, "end_line": 2})
        ctx = _make_tool_context(
            _StubAgentContext(config=_StubConfig(workspace_dir=jarvis_home)),
            payload,
        )
        out = await memory_get.on_invoke_tool(ctx, payload)
        assert out == "line-a\nline-b"

    async def test_wrapper_rejects_traversal_end_to_end(self, tmp_path: Path):
        jarvis_home = tmp_path / ".jarvis"
        (jarvis_home / "workspace").mkdir(parents=True)
        # Seed a target outside ``workspace/`` but inside ``~/.jarvis``,
        # which must still be unreachable via ``..``.
        (jarvis_home / "sessions.db").write_text("sqlite-bytes", encoding="utf-8")

        payload = json.dumps(
            {"path": "../sessions.db", "start_line": 1, "end_line": 1},
        )
        ctx = _make_tool_context(
            _StubAgentContext(config=_StubConfig(workspace_dir=jarvis_home)),
            payload,
        )
        out = await memory_get.on_invoke_tool(ctx, payload)
        assert "escapes Jarvis memory workspace" in out
        assert "sqlite-bytes" not in out

    async def test_wrapper_expands_user_home_tilde(self, tmp_path: Path, monkeypatch):
        # ``memory_get`` calls ``.expanduser()`` on ``workspace_dir``.
        # Point ``$HOME`` at tmp_path and pass a tilde-prefixed config
        # to confirm the expansion actually happens in the wrapper.
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".jarvis" / "workspace").mkdir(parents=True)
        (tmp_path / ".jarvis" / "workspace" / "f.md").write_text(
            "hello", encoding="utf-8",
        )

        payload = json.dumps({"path": "f.md", "start_line": 1, "end_line": 1})
        ctx = _make_tool_context(
            _StubAgentContext(
                config=_StubConfig(workspace_dir=Path("~/.jarvis")),
            ),
            payload,
        )
        out = await memory_get.on_invoke_tool(ctx, payload)
        assert out == "hello"
