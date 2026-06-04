#!/usr/bin/env python3
"""Build and publish one or more packages/ distributions to (Test)PyPI.

Independent of GitHub Actions. Resolves selectors against each package's
distribution name, directory name, or short alias (without the intentframe-
prefix), builds the chosen packages, then uploads with twine --skip-existing.

Examples:
  # one package to TestPyPI
  python scripts/release/publish.py core --target testpypi

  # several at once
  python scripts/release/publish.py core edge intentframe-proxy --target pypi

  # a predefined group of 6 (1, 2, or 3)
  python scripts/release/publish.py --group 1 --target pypi

  # everything
  python scripts/release/publish.py --all --target pypi

  # build + twine check only, no upload
  python scripts/release/publish.py --all --target pypi --dry-run

Auth (token never passed on the command line):
  TestPyPI -> $TEST_PYPI_API_TOKEN   PyPI -> $PYPI_API_TOKEN
  (falls back to $TWINE_PASSWORD, then ~/.pypirc / interactive twine)
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG_DIR = REPO_ROOT / "packages"
DIST_DIR = REPO_ROOT / "dist" / "publish"
NAME_RE = re.compile(r'^name\s*=\s*"([^"]+)"', re.M)

# Leaf-first groups of six, mirroring the buckets documented in
# .github/workflows/release.yml. PyPI rate-limits first-time project
# registration, so a fresh release uploads these groups separately.
GROUPS: dict[str, list[str]] = {
    "1": [
        "intentframe-core", "intentframe-policy-registry", "command-shield",
        "intentframe-prompt-library", "intentframe-bundle-sdk",
        "intentframe-executor-sdk",
    ],
    "2": [
        "intentframe-executor-client", "intentframe-credentials",
        "intentframe-client", "intentframe-actor", "intentframe-components",
        "intentframe-executor",
    ],
    "3": [
        "intentframe-server", "intentframe-runtime", "intentframe-supervisor",
        "intentframe-native-kit", "intentframe-proxy", "intentframe-edge",
    ],
}

TARGETS = {
    "testpypi": {
        "url": "https://test.pypi.org/legacy/",
        "token_env": "TEST_PYPI_API_TOKEN",
    },
    "pypi": {
        "url": "https://upload.pypi.org/legacy/",
        "token_env": "PYPI_API_TOKEN",
    },
}


def discover() -> dict[str, Path]:
    """Map distribution name -> package directory."""
    packages: dict[str, Path] = {}
    for pyproject in sorted(PKG_DIR.glob("*/pyproject.toml")):
        match = NAME_RE.search(pyproject.read_text())
        if match:
            packages[match.group(1)] = pyproject.parent
    return packages


def alias_index(packages: dict[str, Path]) -> dict[str, str]:
    """Map every accepted selector form -> canonical distribution name."""

    def norm(text: str) -> str:
        return text.strip().lower().replace("_", "-")

    index: dict[str, str] = {}
    for dist_name, directory in packages.items():
        keys = {
            norm(dist_name),
            norm(directory.name),
            norm(dist_name.removeprefix("intentframe-")),
        }
        for key in keys:
            index.setdefault(key, dist_name)
    return index


def resolve(selectors: list[str], packages: dict[str, Path]) -> list[str]:
    index = alias_index(packages)
    chosen: list[str] = []
    unknown: list[str] = []
    for selector in selectors:
        key = selector.strip().lower().replace("_", "-")
        dist = index.get(key)
        if dist is None:
            unknown.append(selector)
        elif dist not in chosen:
            chosen.append(dist)
    if unknown:
        print(f"unknown package selector(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"known: {', '.join(sorted(packages))}", file=sys.stderr)
        raise SystemExit(2)
    return chosen


def run(cmd: list[str], **kwargs) -> None:
    print("  $", " ".join(cmd))
    subprocess.run(cmd, check=True, **kwargs)


def files_for(dist_names: list[str]) -> list[Path]:
    found: list[Path] = []
    for dist in dist_names:
        prefix = dist.replace("-", "_") + "-"
        matches = sorted(p for p in DIST_DIR.glob(f"{prefix}*") if p.is_file())
        if not matches:
            raise SystemExit(f"no built artifacts for {dist} in {DIST_DIR}")
        found.extend(matches)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("packages", nargs="*", help="package selectors (name / dir / short)")
    parser.add_argument("--target", choices=sorted(TARGETS), required=True)
    parser.add_argument("--group", choices=sorted(GROUPS), help="upload a predefined group of 6")
    parser.add_argument("--all", action="store_true", help="select every packages/ distribution")
    parser.add_argument("--no-build", action="store_true", help="upload existing dist/publish files")
    parser.add_argument("--dry-run", action="store_true", help="build + twine check, no upload")
    args = parser.parse_args()

    packages = discover()

    selectors = list(args.packages)
    if args.group:
        selectors += GROUPS[args.group]
    if args.all:
        selectors = list(packages)
    if not selectors:
        parser.error("select packages, or pass --group N / --all")

    dist_names = resolve(selectors, packages)
    print(f"target: {args.target}")
    print(f"packages ({len(dist_names)}): {', '.join(dist_names)}")

    if not args.no_build:
        DIST_DIR.mkdir(parents=True, exist_ok=True)
        for dist in dist_names:
            print(f"==> build {dist}")
            run(["uv", "build", "--out-dir", str(DIST_DIR), str(packages[dist])])

    artifacts = files_for(dist_names)
    print(f"==> {len(artifacts)} artifacts staged")

    print("==> twine check")
    run(["uvx", "twine", "check", *map(str, artifacts)])

    if args.dry_run:
        print("dry-run: skipping upload")
        return 0

    env = os.environ.copy()
    token = env.get(TARGETS[args.target]["token_env"]) or env.get("TWINE_PASSWORD")
    if token:
        env["TWINE_USERNAME"] = "__token__"
        env["TWINE_PASSWORD"] = token

    print(f"==> upload to {args.target}")
    run(
        [
            "uvx", "twine", "upload",
            "--repository-url", TARGETS[args.target]["url"],
            "--skip-existing",
            *map(str, artifacts),
        ],
        env=env,
    )
    print("==> done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())