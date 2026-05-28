"""Pin the RUN_COMMAND result shape both executor-client paths emit.

The terminal adapter returns ``{stdout, stderr, return_code, command}``.
We deliberately collapse that to the historical ``{"content": stdout}``
shape (unchanged — the LLM and demo harnesses were already reading it)
plus ``stderr`` added alongside — success or failure.

Why not also forward ``return_code`` and ``command``?  An earlier
revision did exactly that, and the LLM started summarising tool output
("output above", "returned results above") instead of quoting stdout
back to the user.  The richer structured payload looked to the model
like a terminal-session transcript it didn't need to repeat.  Trimming
back to ``{content, stderr}`` restores the verbatim-quoting behaviour
while still surfacing silent failures (non-empty stderr with rc=0,
e.g. ``ps aux --sort=-%cpu | head`` on macOS).

These tests pin the shape so a refactor doesn't silently drift either
direction:

  - drop stderr → silent failures return to being invisible
  - reintroduce return_code / command / duplicate stdout → LLM stops
    quoting output and tells the user "see above"
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from executor_client.bridge import ExecutorBridge
from executor_client.http_client import _RESULT_MAP


def _adapter_run_command_data() -> dict:
    """Shape emitted by intentframe_executor_pack_macos/adapters/terminal.py."""
    return {
        "stdout": "",
        "stderr": "ps: illegal option -- -\nusage: ps ...\n",
        "return_code": 0,
        "command": "ps aux --sort=-%cpu | head -n 20",
    }


def _expected_keys() -> set[str]:
    """Exactly what RUN_COMMAND translators must emit — no more, no less."""
    return {"content", "stderr"}


def test_http_client_run_command_shape_is_content_plus_stderr() -> None:
    translator = _RESULT_MAP["RUN_COMMAND"]
    out = translator(_adapter_run_command_data())

    assert set(out.keys()) == _expected_keys(), (
        f"unexpected RUN_COMMAND keys: {sorted(out.keys())} "
        "(expected exactly content + stderr)"
    )
    assert out["content"] == ""
    assert out["stderr"].startswith("ps: illegal option")


def test_bridge_run_command_shape_is_content_plus_stderr() -> None:
    translator = ExecutorBridge._RESULT_MAP["RUN_COMMAND"]
    out = translator(_adapter_run_command_data())

    assert set(out.keys()) == _expected_keys(), (
        f"unexpected RUN_COMMAND keys: {sorted(out.keys())} "
        "(expected exactly content + stderr)"
    )
    assert out["content"] == ""
    assert out["stderr"].startswith("ps: illegal option")


def test_success_with_stdout_also_carries_empty_stderr() -> None:
    """Happy-path: non-empty stdout, empty stderr.  ``stderr`` must
    still be present (empty string) so downstream branches on
    ``stderr`` without needing ``.get``.
    """
    data = {
        "stdout": "line1\nline2\n",
        "stderr": "",
        "return_code": 0,
        "command": "echo hi",
    }

    http_out = _RESULT_MAP["RUN_COMMAND"](data)
    bridge_out = ExecutorBridge._RESULT_MAP["RUN_COMMAND"](data)

    for out in (http_out, bridge_out):
        assert out["content"] == "line1\nline2\n"
        assert out["stderr"] == ""


def test_return_code_and_command_are_not_forwarded() -> None:
    """Guard against the regression where we forwarded the whole
    adapter dict.  ``return_code`` / ``command`` / duplicate ``stdout``
    primed the LLM to treat the tool result as a terminal transcript
    and stop quoting output back to the user.
    """
    data = _adapter_run_command_data()

    for translator in (_RESULT_MAP["RUN_COMMAND"], ExecutorBridge._RESULT_MAP["RUN_COMMAND"]):
        out = translator(data)
        assert "return_code" not in out
        assert "command" not in out
        assert "stdout" not in out


def test_llm_tool_rendering_surfaces_stderr_and_content() -> None:
    """End-to-end: ``jarvis.tools._render_result`` surfaces the trimmed
    shape to the LLM.  With ``stderr`` present and non-empty, the model
    has a reliable signal that the command produced a diagnostic even
    when rc=0 and stdout is empty.
    """
    from jarvis.tools import _render_result

    translated = _RESULT_MAP["RUN_COMMAND"](_adapter_run_command_data())
    result = SimpleNamespace(success=True, data=translated, error=None)

    rendered = json.loads(_render_result(result))

    assert rendered["success"] is True
    assert rendered["content"] == ""
    assert "ps: illegal option" in rendered["stderr"]
    assert "return_code" not in rendered
    assert "command" not in rendered
    assert "stdout" not in rendered
