"""Executor substrate must not import plugin adapter implementations.

Mirrors tests/test_boundary_imports.py for the upcoming executor SDK +
native_adapters extraction.  CI-enforced before the move so the refactor
cannot re-introduce substrate → plugin imports silently.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_IMPORT_PREFIXES = (
    "intentframe_native_adapters",
    "intentframe_native_bundles",
)

STRICT_ROOTS = (
    REPO_ROOT / "executor",
)

# Substrate may reference bundle-owned floor helpers until executor SDK
# owns its own copy.  macOS pack files moved to intentframe_executor_pack_macos.
ALLOWLISTED_IMPORTS: dict[Path, frozenset[str]] = {}


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


def test_executor_does_not_import_native_adapters() -> None:
    violations = _violations_for_root(STRICT_ROOTS[0])
    assert not violations, "executor boundary violations:\n" + "\n".join(violations)


def test_executor_allowlisted_imports_are_explicit() -> None:
    """Every allowlisted import path must still exist on disk."""
    for path, allowed in ALLOWLISTED_IMPORTS.items():
        assert path.is_file(), f"allowlist references missing file: {path}"
        imports = _collect_imports(path)
        for mod in allowed:
            assert mod in imports, f"{path} no longer imports allowlisted {mod!r}"
