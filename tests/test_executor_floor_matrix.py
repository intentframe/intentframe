"""Parametric floor checks — executor-side deterministic walls."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from action_registry import ActionType
from executor_sdk.config.schema import HostFilesConfig
from intentframe_executor_pack_macos.adapters.host_files import HostFilesAdapter
from resource_registry.floor import DENY_WRITE_PREFIXES


def _run(adapter: HostFilesAdapter, action: str, params: dict):
    return asyncio.run(adapter.safe_execute(action, params))


@pytest.fixture
def permissive_adapter() -> HostFilesAdapter:
    """Adapter whose YAML ceiling includes every floor prefix (operator mistake)."""
    cfg = HostFilesConfig(
        allowed_read_paths=["/"],
        allowed_write_paths=["/"],
    )
    return HostFilesAdapter(host_files_cfg=cfg)


@pytest.mark.parametrize(
    "target",
    [
        pytest.param(prefix, id=prefix.replace("/", "_").strip("_") or "root")
        for prefix in DENY_WRITE_PREFIXES
        if not prefix.startswith("/var/")  # skip macOS-only /private/var aliases in CI
    ],
)
def test_host_files_floor_blocks_write_to_deny_prefix(
    permissive_adapter: HostFilesAdapter,
    target: str,
) -> None:
    result = _run(
        permissive_adapter,
        ActionType.WRITE_HOST_FILE.value,
        {"path": f"{target}/matrix_probe.txt", "content": "x"},
    )
    assert not result.success, f"expected floor block for write to {target!r}"
    assert "floor" in (result.error or "").lower()


@pytest.mark.parametrize(
    "target",
    [
        pytest.param(prefix, id=f"del_{prefix.replace('/', '_').strip('_') or 'root'}")
        for prefix in DENY_WRITE_PREFIXES
        if not prefix.startswith("/var/")
    ],
)
def test_host_files_floor_blocks_delete_to_deny_prefix(
    permissive_adapter: HostFilesAdapter,
    target: str,
) -> None:
    result = _run(
        permissive_adapter,
        ActionType.DELETE_HOST_FILE.value,
        {"path": f"{target}/matrix_probe.txt"},
    )
    assert not result.success, f"expected floor block for delete to {target!r}"
    assert "floor" in (result.error or "").lower()


def test_floor_fires_before_ceiling_on_host_files(tmp_path: Path) -> None:
    """Floor wins even when YAML allowlist is wide open."""
    cfg = HostFilesConfig(
        allowed_read_paths=["/etc"],
        allowed_write_paths=["/etc"],
    )
    adapter = HostFilesAdapter(host_files_cfg=cfg)
    result = _run(
        adapter,
        ActionType.WRITE_HOST_FILE.value,
        {"path": "/etc/sudoers", "content": "probe"},
    )
    assert not result.success
    assert "floor" in (result.error or "").lower()
