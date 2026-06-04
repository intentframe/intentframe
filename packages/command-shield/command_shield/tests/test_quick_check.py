"""Tests for quick_check — the executor's last-resort floor."""

from __future__ import annotations

from command_shield import quick_check


class TestQuickCheck:
    def test_catches_catastrophic(self) -> None:
        assert quick_check("sudo rm -rf /").is_catastrophic

    def test_catches_mkfs(self) -> None:
        assert quick_check("mkfs.ext4 /dev/sda1").is_catastrophic

    def test_catches_obfuscated(self) -> None:
        assert quick_check('su""do reboot').is_catastrophic

    def test_passes_safe_echo(self) -> None:
        assert not quick_check("echo hello").is_catastrophic

    def test_passes_ls(self) -> None:
        assert not quick_check("ls -la /tmp").is_catastrophic

    def test_empty_input_safe(self) -> None:
        assert not quick_check("").is_catastrophic
