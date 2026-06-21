#!/usr/bin/env python3
"""Set one version across every packages/ distribution and pin intra-workspace deps.

Usage:
  python scripts/release/set_version.py 0.2.0
  python scripts/release/set_version.py 0.1.1 --check   # CI: exit 1 if drifted
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG_DIR = REPO_ROOT / "packages"
NAME_RE = re.compile(r'^name\s*=\s*"([^"]+)"', re.M)
VERSION_RE = re.compile(r'^(version\s*=\s*")[^"]+(")', re.M)


def first_party_names() -> set[str]:
    names: set[str] = set()
    for pyproject in PKG_DIR.glob("*/pyproject.toml"):
        match = NAME_RE.search(pyproject.read_text())
        if match:
            names.add(match.group(1))
    return names


def dep_pattern(names: set[str]) -> re.Pattern[str]:
    alt = "|".join(sorted((re.escape(name) for name in names), key=len, reverse=True))
    return re.compile(
        rf'"(?P<name>{alt})(?P<extras>\[[^\]]*\])?(?:[<>=!~][^"]*)?"'
    )


def rewrite(text: str, version: str, deps: re.Pattern[str]) -> str:
    text = VERSION_RE.sub(rf"\g<1>{version}\g<2>", text, count=1)
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("name = ") or stripped.startswith("name="):
            out.append(line)
            continue
        out.append(
            deps.sub(
                lambda match: (
                    f'"{match.group("name")}{match.group("extras") or ""}=={version}"'
                ),
                line,
            )
        )
    return "".join(out)


def main() -> int:
    args = [arg for arg in sys.argv[1:] if not arg.startswith("-")]
    check = "--check" in sys.argv
    if len(args) != 1:
        print("usage: set_version.py <version> [--check]", file=sys.stderr)
        return 2

    version = args[0]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        print(f"invalid version (expected X.Y.Z): {version}", file=sys.stderr)
        return 2

    deps = dep_pattern(first_party_names())
    drifted: list[Path] = []

    for pyproject in sorted(PKG_DIR.glob("*/pyproject.toml")):
        old = pyproject.read_text()
        new = rewrite(old, version, deps)
        if new != old:
            drifted.append(pyproject.relative_to(REPO_ROOT))
            if not check:
                pyproject.write_text(new)

    if check:
        if drifted:
            print("version/pins drifted:")
            for path in drifted:
                print(f"  {path}")
            return 1
        print(f"all packages pinned to {version}")
        return 0

    print(f"set {version}; updated {len(drifted)} file(s) (review git diff)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
