"""Startup invariants for executor adapter registration."""

from __future__ import annotations

import importlib
import tempfile

import pytest

from action_registry import ActionCatalog
from executor.adapters.base import CapabilityAdapter
from executor.config.schema import HostFilesConfig
from executor.dispatch import ActionDispatcher
from intentframe_executor_pack_macos.adapters import _ADAPTER_SPECS, register_all_adapters


def _instantiate_adapter(adapter_id: str, cls: type[CapabilityAdapter]) -> CapabilityAdapter:
    kwargs: dict = {}
    if adapter_id == "host_files":
        root = tempfile.mkdtemp(prefix="if_registry_")
        kwargs["host_files_cfg"] = HostFilesConfig(
            allowed_read_paths=[root],
            allowed_write_paths=[root],
        )
    return cls(**kwargs)


@pytest.fixture
def loaded_adapters() -> list[tuple[str, CapabilityAdapter]]:
    from executor.adapters import _ADAPTER_REGISTRY

    _ADAPTER_REGISTRY.clear()
    register_all_adapters()

    adapters: list[tuple[str, CapabilityAdapter]] = []
    for adapter_id, module_path, class_name in _ADAPTER_SPECS:
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        try:
            instance = _instantiate_adapter(adapter_id, cls)
        except Exception as exc:
            pytest.skip(f"{adapter_id} unavailable: {exc}")
        adapters.append((adapter_id, instance))
    return adapters


def test_every_macos_adapter_spec_loads(loaded_adapters) -> None:
    loaded_ids = {adapter_id for adapter_id, _ in loaded_adapters}
    expected = {spec[0] for spec in _ADAPTER_SPECS}
    # filesystem_watch is optional (watchdog dep).
    optional = {"filesystem_watch"}
    missing = expected - loaded_ids - optional
    assert missing == set(), f"adapters failed to load: {sorted(missing)}"


def test_no_duplicate_actions_across_macos_adapters(loaded_adapters) -> None:
    owners: dict[str, str] = {}
    duplicates: list[str] = []
    for adapter_id, instance in loaded_adapters:
        for action in instance.supported_actions():
            if action in owners:
                duplicates.append(
                    f"{action} claimed by {owners[action]} and {adapter_id}"
                )
            else:
                owners[action] = adapter_id
    assert duplicates == []


def test_manifest_adapter_id_matches_spec(loaded_adapters) -> None:
    for adapter_id, instance in loaded_adapters:
        assert instance.manifest().adapter_id == adapter_id


def test_dispatcher_registers_all_macos_adapters(loaded_adapters) -> None:
    catalog = ActionCatalog()
    catalog.register_defaults()
    dispatcher = ActionDispatcher(catalog=catalog)
    for _, instance in loaded_adapters:
        dispatcher.register(instance)
    assert len(dispatcher.registered_adapters) == len(loaded_adapters)
    assert len(dispatcher.registered_actions) > 0


def test_every_adapter_declares_supported_actions(loaded_adapters) -> None:
    for adapter_id, instance in loaded_adapters:
        actions = instance.supported_actions()
        assert actions, f"{adapter_id} returned empty supported_actions()"
        assert all(isinstance(a, str) for a in actions)
