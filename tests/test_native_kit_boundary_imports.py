"""Native kit must not import intentframe_core directly.

Plugin author code imports wire types from intentframe_bundle_sdk (bundles,
action_registry, resource_registry) or executor_sdk (executor packs). Core
remains an internal dependency of those SDKs.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_IMPORT_PREFIXES = ("intentframe_core",)

STRICT_ROOTS = (REPO_ROOT / "intentframe_native_kit",)


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
        for imported in _collect_imports(path):
            if any(imported.startswith(prefix) for prefix in FORBIDDEN_IMPORT_PREFIXES):
                rel = path.relative_to(REPO_ROOT)
                violations.append(f"{rel}: imports {imported!r}")
    return violations


def test_native_kit_does_not_import_intentframe_core() -> None:
    violations = _violations_for_root(STRICT_ROOTS[0])
    assert not violations, (
        "native kit must import wire types from intentframe_bundle_sdk or "
        "executor_sdk, not intentframe_core:\n" + "\n".join(violations)
    )
