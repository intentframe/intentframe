"""Parametric terminal catastrophic floor — command_shield quick_check."""

from __future__ import annotations

import asyncio

import pytest

from intentframe_executor_pack_macos.adapters.terminal import TerminalAdapter

TERMINAL_CATASTROPHIC_COMMANDS: tuple[tuple[str, str], ...] = (
    ("sudo_reboot", "sudo reboot"),
    ("rm_rf_root", "rm -rf /"),
    ("mkfs", "mkfs.ext4 /dev/sda1"),
    ("dd_destroy", "dd if=/dev/zero of=/dev/sda"),
    ("dev_write", "echo x > /dev/sda"),
    ("chmod_777", "chmod 777 /etc/passwd"),
)


def _run(adapter: TerminalAdapter, command: str):
    return asyncio.run(adapter.safe_execute("RUN_COMMAND", {"command": command}))


@pytest.fixture
def terminal_adapter() -> TerminalAdapter:
    from intentframe_executor_pack_macos.sandbox.config import SandboxConfig

    return TerminalAdapter(sandbox_config=SandboxConfig(enabled=False))


@pytest.mark.parametrize("case_id,command", TERMINAL_CATASTROPHIC_COMMANDS)
def test_terminal_floor_blocks_catastrophic_command(
    terminal_adapter: TerminalAdapter,
    case_id: str,
    command: str,
) -> None:
    del case_id  # used as pytest id only
    result = _run(terminal_adapter, command)
    assert not result.success, f"expected floor block for {command!r}"
    assert "catastrophic" in (result.error or "").lower()


def test_terminal_floor_allows_safe_command(terminal_adapter: TerminalAdapter) -> None:
    result = _run(terminal_adapter, "echo matrix_floor_ok")
    assert result.success
    assert result.data is not None
    assert "matrix_floor_ok" in result.data.get("stdout", "")
