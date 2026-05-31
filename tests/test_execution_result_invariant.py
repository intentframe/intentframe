"""ExecutionResult auditability invariant: failures always carry a reason."""

from __future__ import annotations

from intentframe_core.types import ExecutionResult


def test_failure_without_error_gets_default_reason() -> None:
    result = ExecutionResult(success=False)
    assert result.error
    assert "without an error" in result.error


def test_failure_with_blank_error_gets_default_reason() -> None:
    result = ExecutionResult(success=False, error="   ")
    assert result.error.strip()


def test_failure_with_explicit_error_is_preserved() -> None:
    result = ExecutionResult(success=False, error="boom")
    assert result.error == "boom"


def test_success_error_is_left_untouched() -> None:
    assert ExecutionResult(success=True).error is None
    assert ExecutionResult(success=True, data={"ok": 1}).error is None
