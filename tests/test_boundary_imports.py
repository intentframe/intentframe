"""Substrate must not import plugin implementation modules.

Also enforces native-bundles layering:

- ``actions/<A>/`` must not import ``actions/<B>/`` when A ≠ B.
- ``shared/<topic>/`` must not import any ``actions/<bundle>/`` module.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_IMPORT_PREFIXES = (
    "intentframe_native_bundles",
)

STRICT_ROOTS = (
    REPO_ROOT / "intentframe_server",
    REPO_ROOT / "intentframe_bundle_sdk",
)

ALLOWLISTED_IMPORTS: dict[Path, frozenset[str]] = {
    # Known optional decouple — onboarding copy lives in native_bundles.
    # Every other component import of intentframe_native_bundles must fail CI.
    REPO_ROOT / "intentframe_components" / "onboarding" / "engine.py": frozenset({
        "intentframe_native_bundles.onboarding",
    }),
}


def _collect_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _violations_for_root(root: Path) -> list[str]:
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if path.name.startswith("test_"):
            continue
        allowed = ALLOWLISTED_IMPORTS.get(path, frozenset())
        for imported in _collect_imports(path):
            if imported in allowed:
                continue
            if any(imported.startswith(prefix) for prefix in FORBIDDEN_IMPORT_PREFIXES):
                rel = path.relative_to(REPO_ROOT)
                violations.append(f"{rel}: imports {imported!r}")
    return violations


def test_intentframe_server_does_not_import_native_bundles() -> None:
    violations = _violations_for_root(STRICT_ROOTS[0])
    assert not violations, "substrate boundary violations:\n" + "\n".join(violations)


def test_bundle_sdk_does_not_import_native_bundles() -> None:
    violations = _violations_for_root(STRICT_ROOTS[1])
    assert not violations, "SDK boundary violations:\n" + "\n".join(violations)


def test_no_cross_bundle_action_imports() -> None:
    """No file under actions/<bundle_a>/ may import from actions/<bundle_b>/."""
    actions_root = REPO_ROOT / "intentframe_native_bundles" / "actions"
    violations: list[str] = []
    for path in sorted(actions_root.rglob("*.py")):
        bundle = path.parent.name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mod: str | None = None
            if isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("intentframe_native_bundles.actions."):
                        mod = alias.name
            if not mod:
                continue
            prefix = "intentframe_native_bundles.actions."
            if not mod.startswith(prefix):
                continue
            parts = mod[len(prefix):].split(".")
            imported_bundle = parts[0] if parts else ""
            if imported_bundle and imported_bundle != bundle:
                rel = path.relative_to(REPO_ROOT)
                violations.append(f"{rel}: imports {mod!r}")
    assert not violations, "cross-bundle imports detected:\n" + "\n".join(violations)


def test_shared_does_not_import_action_bundles() -> None:
    """No file under shared/<topic>/ may import from actions/<bundle>/."""
    shared_root = REPO_ROOT / "intentframe_native_bundles" / "shared"
    prefix = "intentframe_native_bundles.actions."
    violations: list[str] = []
    for path in sorted(shared_root.rglob("*.py")):
        for imported in _collect_imports(path):
            if imported.startswith(prefix):
                rel = path.relative_to(REPO_ROOT)
                violations.append(f"{rel}: imports {imported!r}")
    assert not violations, "shared→actions imports detected:\n" + "\n".join(violations)


def test_intentframe_components_imports_are_allowlisted_only() -> None:
    root = REPO_ROOT / "intentframe_components"
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if path.name.startswith("test_"):
            continue
        allowed = ALLOWLISTED_IMPORTS.get(path, frozenset())
        for imported in _collect_imports(path):
            if not any(imported.startswith(prefix) for prefix in FORBIDDEN_IMPORT_PREFIXES):
                continue
            if imported not in allowed:
                rel = path.relative_to(REPO_ROOT)
                violations.append(f"{rel}: unallowlisted import {imported!r}")
    assert not violations, "component boundary violations:\n" + "\n".join(violations)
