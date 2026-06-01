"""Phase 6 audit — native action bundles must not hold module-level clients."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTIONS_ROOT = REPO_ROOT / "intentframe_native_kit" / "intentframe_native_bundles" / "actions"

# Bundles audited for external client ownership; email is the only one with aclose today.
CLIENT_BUNDLE_IDS = frozenset({"email", "browser", "api", "host_files", "terminal"})


def _action_py_files() -> list[Path]:
    return sorted(ACTIONS_ROOT.rglob("*.py"))


def _module_level_none_assignments(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.startswith("_") and target.id.endswith("_client"):
                hits.append(f"{path.relative_to(REPO_ROOT)}:{target.id}")
    return hits


def _global_statements(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            for name in node.names:
                if name.startswith("_"):
                    rel = path.relative_to(REPO_ROOT)
                    hits.append(f"{rel}: global {name}")
    return hits


def test_no_module_level_client_globals_under_actions() -> None:
    violations: list[str] = []
    for path in _action_py_files():
        violations.extend(_module_level_none_assignments(path))
        violations.extend(_global_statements(path))
    assert not violations, "module-level client globals found:\n" + "\n".join(violations)


@pytest.mark.parametrize("bundle_id", sorted(CLIENT_BUNDLE_IDS))
def test_candidate_bundles_have_bundle_module(bundle_id: str) -> None:
    bundle_path = ACTIONS_ROOT / bundle_id / "bundle.py"
    assert bundle_path.is_file(), f"missing bundle module for {bundle_id!r}"


def test_only_contacts_bundles_declare_aclose() -> None:
    """Bundles that hold a PlatformContactsClient must implement aclose."""
    pattern = re.compile(r"async def aclose\(")
    bundles_with_aclose: list[str] = []
    for path in sorted(ACTIONS_ROOT.glob("*/bundle.py")):
        if pattern.search(path.read_text(encoding="utf-8")):
            bundles_with_aclose.append(path.parent.name)
    assert bundles_with_aclose == ["email", "message"]
