"""Executor substrate must not import plugin adapter implementations.

Mirrors tests/test_boundary_imports.py for the upcoming executor SDK +
native_adapters extraction.  CI-enforced before the move so the refactor
cannot re-introduce substrate → plugin imports silently.
"""

from __future__ import annotations

import ast
from pathlib import Path

import executor
import intentframe_native_kit

REPO_ROOT = Path(__file__).resolve().parents[1]
_EXECUTOR_ROOT = Path(executor.__file__).resolve().parent
_NATIVE_KIT_ROOT = Path(intentframe_native_kit.__file__).resolve().parent

FORBIDDEN_IMPORT_PREFIXES = (
    "intentframe_native_adapters",
    # Core executor must not import the native kit at all: packs (incl. the
    # macOS pack's TCC permission check) are loaded purely via config-driven
    # register_all() / entry points, never by direct import from executor/.
    "intentframe_native_kit",
)

STRICT_ROOTS = (
    _EXECUTOR_ROOT,
)

ALLOWLISTED_IMPORTS: dict[Path, frozenset[str]] = {}

# Executor packs must not import action bundles — floor checks use
# resource_registry.floor and command_shield directly.
PACK_FORBIDDEN_IMPORT_PREFIXES = (
    "intentframe_native_kit.intentframe_native_bundles",
)
PACK_STRICT_ROOTS = (
    _NATIVE_KIT_ROOT / "intentframe_executor_pack_posix",
    _NATIVE_KIT_ROOT / "intentframe_executor_pack_macos",
    _NATIVE_KIT_ROOT / "intentframe_executor_pack_console",
)


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


def _pack_violations() -> list[str]:
    violations: list[str] = []
    for root in PACK_STRICT_ROOTS:
        for path in sorted(root.rglob("*.py")):
            if path.name.startswith("test_"):
                continue
            for imported in _collect_imports(path):
                if any(
                    imported.startswith(prefix)
                    for prefix in PACK_FORBIDDEN_IMPORT_PREFIXES
                ):
                    rel = path.relative_to(REPO_ROOT)
                    violations.append(f"{rel}: imports {imported!r}")
    return violations


def test_executor_packs_do_not_import_native_bundles() -> None:
    violations = _pack_violations()
    assert not violations, "executor pack boundary violations:\n" + "\n".join(violations)
