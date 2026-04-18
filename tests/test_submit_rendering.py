"""Tests for Jarvis ``_render_result`` and ``_submit`` result handling.

The renderer is what the LLM actually sees after every tool call:

    actor.submit()  ->  ExecutionResult  ->  _render_result()  ->  string

Before this contract, the failure branch threw away ``result.data`` and
only forwarded ``f"Error: {stderr}"``, which meant commands like
``ls -la ~`` (where ``~/.intentframe`` triggers an EPERM and pushes
``rc`` to 1) lost their entire stdout listing before reaching the LLM.
These tests lock in:

* success and failure now produce the same JSON shape
* known-big string fields (``stdout``, ``stderr``, ``content``) are
  truncated head+tail with truthful markers
* non-dict payloads still degrade gracefully
* ``result.error`` is only added when it carries information beyond
  what ``stderr`` already contains
* the ``_submit`` wrapper keeps swallowing actor-level exceptions
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis.tools import (
    MAX_ERROR_CHARS,
    MAX_STDERR_CHARS,
    MAX_STDOUT_CHARS,
    _render_result,
    _submit,
    _truncate,
)
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result(
    success: bool,
    data=None,
    error: str | None = None,
) -> SimpleNamespace:
    """Build a minimal duck-typed ExecutionResult for renderer tests.

    ``_render_result`` only reads ``.success``, ``.data``, ``.error`` —
    a plain namespace is clearer than constructing the real Pydantic
    model with all its optional fields.
    """
    return SimpleNamespace(success=success, data=data, error=error)


class _DummyAction(BaseModel):
    action: str = "RUN_COMMAND"
    command: str = "echo hi"
    reason: str = "test"


def _run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════
# _truncate unit tests
# ═══════════════════════════════════════════════════════════════════════════


class TestTruncate:
    def test_short_text_untouched(self) -> None:
        text, was = _truncate("hello world", 100)
        assert text == "hello world"
        assert was is False

    def test_exact_limit_untouched(self) -> None:
        """A string equal to the limit must NOT be flagged truncated —
        otherwise every payload sitting on the boundary would get a
        spurious ``*_truncated`` annotation."""
        s = "x" * 50
        text, was = _truncate(s, 50)
        assert text == s
        assert was is False

    def test_head_and_tail_preserved(self) -> None:
        """The start (for listings) AND end (for trailing error lines)
        must both survive truncation — a head-only strategy would hide
        the final line that usually carries the real diagnostic."""
        body = "START" + ("x" * 100) + "END"
        text, was = _truncate(body, 20)
        assert was is True
        assert text.startswith("START")
        assert text.endswith("END")
        assert "truncated" in text

    def test_truncation_marker_reports_dropped_count(self) -> None:
        body = "a" * 500
        text, was = _truncate(body, 100)
        assert was is True
        assert "[400 chars truncated]" in text


# ═══════════════════════════════════════════════════════════════════════════
# _render_result — dict data
# ═══════════════════════════════════════════════════════════════════════════


class TestRenderSuccess:
    def test_small_stdout_round_trips_verbatim(self) -> None:
        """Clean success must not introduce truncation metadata — that
        would pollute every tool call with unnecessary fields."""
        data = {
            "stdout": "total 0\nfile.txt\n",
            "stderr": "",
            "return_code": 0,
            "command": "ls -la",
        }
        rendered = json.loads(_render_result(_result(True, data=data)))
        assert rendered["success"] is True
        assert rendered["stdout"] == data["stdout"]
        assert rendered["return_code"] == 0
        assert rendered["command"] == "ls -la"
        assert "stdout_truncated" not in rendered
        assert "error" not in rendered

    def test_oversized_stdout_is_truncated_with_markers(self) -> None:
        """A 20 KB listing must be cut down AND annotated with the
        original size so the LLM knows it's working from a sample."""
        big = "L" + ("x" * (MAX_STDOUT_CHARS * 2)) + "E"
        data = {"stdout": big, "stderr": "", "return_code": 0}

        rendered = json.loads(_render_result(_result(True, data=data)))

        assert rendered["stdout_truncated"] is True
        assert rendered["stdout_total_chars"] == len(big)
        assert rendered["stdout"].startswith("L")
        assert rendered["stdout"].endswith("E")
        assert "truncated" in rendered["stdout"]

    def test_non_string_big_field_is_not_truncated(self) -> None:
        """Only *string* values of ``stdout``/``stderr``/``content`` are
        truncated. If an adapter ever puts a structured value under one
        of those keys, it must pass through untouched rather than crash
        or stringify unexpectedly."""
        data = {"stdout": {"structured": [1, 2, 3]}, "return_code": 0}
        rendered = json.loads(_render_result(_result(True, data=data)))
        assert rendered["stdout"] == {"structured": [1, 2, 3]}
        assert "stdout_truncated" not in rendered

    def test_content_field_gets_same_truncation_treatment(self) -> None:
        """``read_file`` returns its payload under ``content``, not
        ``stdout``. It must cap through the same path."""
        from jarvis.tools import MAX_CONTENT_CHARS

        big = "A" + ("y" * (MAX_CONTENT_CHARS * 3)) + "Z"
        data = {"content": big, "path": "/tmp/big.txt"}
        rendered = json.loads(_render_result(_result(True, data=data)))
        assert rendered["content_truncated"] is True
        assert rendered["content_total_chars"] == len(big)
        assert rendered["path"] == "/tmp/big.txt"


class TestRenderFailure:
    def test_failure_still_forwards_stdout(self) -> None:
        """The headline fix: ``ls -la ~`` -> rc=1 + full listing + EPERM
        stderr. The LLM must receive stdout so it can actually report
        the listing, instead of losing everything behind ``Error: ...``."""
        data = {
            "stdout": "listing line 1\nlisting line 2\n",
            "stderr": "ls: .intentframe: Operation not permitted\n",
            "return_code": 1,
            "command": "/bin/ls -la ~",
        }
        rendered = json.loads(
            _render_result(_result(False, data=data, error=data["stderr"]))
        )
        assert rendered["success"] is False
        assert rendered["stdout"] == data["stdout"]
        assert rendered["stderr"] == data["stderr"]
        assert rendered["return_code"] == 1
        # stderr already carries the same text as result.error -> don't
        # duplicate it; that's the whole point of the dedup rule.
        assert "error" not in rendered

    def test_failure_with_distinct_error_includes_error_field(self) -> None:
        """Non-terminal adapters (email, calendar, …) don't emit
        ``stderr``. Their ``result.error`` is the only diagnostic we
        have, so it must survive into the rendered payload."""
        data = {"account_email": "a@b.com", "to": "c@d.com"}
        rendered = json.loads(
            _render_result(
                _result(False, data=data, error="SMTP auth failed")
            )
        )
        assert rendered["success"] is False
        assert rendered["error"] == "SMTP auth failed"
        assert rendered["account_email"] == "a@b.com"

    def test_failure_with_huge_error_is_truncated(self) -> None:
        """Even when ``error`` is distinct from stderr, it must respect
        its own cap so a runaway backend message can't torch context."""
        giant_error = "E" + ("!" * (MAX_ERROR_CHARS * 3)) + "E"
        rendered = json.loads(
            _render_result(_result(False, data={"x": 1}, error=giant_error))
        )
        assert rendered["error_truncated"] is True
        assert len(rendered["error"]) < len(giant_error)

    def test_stderr_is_capped_with_its_own_limit(self) -> None:
        """``stderr`` uses a tighter cap than ``stdout`` because error
        streams should be short — if they balloon it usually means
        noise, and the truncation marker is adequate context."""
        huge_stderr = "ERR" + ("!" * (MAX_STDERR_CHARS * 3)) + "end"
        data = {
            "stdout": "some output\n",
            "stderr": huge_stderr,
            "return_code": 1,
        }
        rendered = json.loads(
            _render_result(_result(False, data=data, error=huge_stderr))
        )
        assert rendered["stderr_truncated"] is True
        assert rendered["stderr_total_chars"] == len(huge_stderr)
        # error text matches stderr verbatim -> still no duplicate key
        assert "error" not in rendered


class TestRenderNonDictPayload:
    def test_non_dict_success_falls_back_to_str(self) -> None:
        """Some adapters (or stubs) return a scalar. The renderer must
        not crash trying to treat it as a dict — it falls back to the
        pre-existing ``str(data)`` behaviour."""
        rendered = _render_result(_result(True, data="ok-string"))
        assert rendered == "ok-string"

    def test_non_dict_none_success_returns_ok(self) -> None:
        rendered = _render_result(_result(True, data=None))
        assert rendered == "OK"

    def test_non_dict_failure_falls_back_to_error_string(self) -> None:
        rendered = _render_result(_result(False, data=None, error="boom"))
        assert rendered == "Error: boom"

    def test_non_dict_failure_without_error_uses_placeholder(self) -> None:
        """A failure with neither dict data nor an error message is a
        buggy adapter — we still must return a human-readable string so
        the LLM doesn't see ``None``."""
        rendered = _render_result(_result(False, data=None, error=None))
        assert rendered == "Error: unknown error"


# ═══════════════════════════════════════════════════════════════════════════
# _submit exception handling
# ═══════════════════════════════════════════════════════════════════════════


class TestSubmitExceptionPath:
    def test_actor_exception_returns_error_string(self) -> None:
        """Network hiccups / actor bugs must not crash the tool call —
        they must come back as a plain ``"Error: ..."`` string so the
        LLM can reason about retry/abort instead of raising out of the
        agent loop."""
        ctx = MagicMock()
        ctx.context.actor.submit = AsyncMock(side_effect=RuntimeError("boom"))

        out = _run(_submit(ctx, _DummyAction()))

        assert out.startswith("Error:")
        assert "boom" in out

    def test_actor_success_runs_through_renderer(self) -> None:
        """Sanity: the happy path calls ``_render_result`` (verified by
        the JSON shape) rather than any legacy string formatting."""
        ctx = MagicMock()
        ctx.context.actor.submit = AsyncMock(
            return_value=_result(True, data={"stdout": "hi\n", "return_code": 0})
        )

        out = _run(_submit(ctx, _DummyAction()))

        payload = json.loads(out)
        assert payload["success"] is True
        assert payload["stdout"] == "hi\n"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
