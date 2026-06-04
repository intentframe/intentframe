#!/usr/bin/env bash
# Build, metadata-check, and clean-room install every packages/ distribution to
# validate a PyPI release before publishing.
#
# Usage:
#   ./scripts/release/validate_publish.sh
#   ./scripts/release/validate_publish.sh --publish-test   # upload to TestPyPI
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

DIST_DIR="${REPO_ROOT}/dist/publish"
PY_VERSION="3.14"
PUBLISH_TEST=0
if [ "${1:-}" = "--publish-test" ]; then
  PUBLISH_TEST=1
fi

echo "==> verify lockstep version pins"
python3 scripts/release/set_version.py "$(grep -m1 '^version = ' packages/intentframe-core/pyproject.toml | sed 's/version = "//;s/"//')" --check

echo "==> clean ${DIST_DIR}"
rm -rf "${DIST_DIR}"
mkdir -p "${DIST_DIR}"

echo "==> build sdist+wheel for every packages/* distribution"
count=0
for pkg_dir in packages/*/; do
  if [ ! -f "${pkg_dir}pyproject.toml" ]; then
    continue
  fi
  echo "    ${pkg_dir}"
  uv build --out-dir "${DIST_DIR}" "${pkg_dir}"
  count=$((count + 1))
done
echo "    built ${count} distributions"

echo "==> twine metadata check"
uvx twine check "${DIST_DIR}"/*

echo "==> verify wheels bundle LICENSE and expected data files"
python3 - "${DIST_DIR}" <<'PY'
import re
import sys
import zipfile
from pathlib import Path

dist = Path(sys.argv[1])
wheels = sorted(dist.glob("*.whl"))
if not wheels:
    raise SystemExit("no wheels built")

problems: list[str] = []
for whl in wheels:
    match = re.match(r"^(.+?)-(\d+\.\d+\.\d+(?:\.\d+)?(?:[a-zA-Z0-9]+)?)-", whl.name)
    dist_name = match.group(1) if match else whl.name
    with zipfile.ZipFile(whl) as archive:
        names = archive.namelist()
    if not any("LICENSE" in name for name in names):
        problems.append(f"{whl.name}: no LICENSE in wheel")
    if dist_name == "intentframe_supervisor" and not any(
        name.endswith("supervisor/config/supervisor.yaml") for name in names
    ):
        problems.append(f"{whl.name}: missing supervisor/config/supervisor.yaml")
    if dist_name == "intentframe_native_kit" and not any(
        name.endswith(".yaml") for name in names
    ):
        problems.append(f"{whl.name}: no .yaml profiles bundled")

for problem in problems:
    print("  FAIL", problem)
if problems:
    raise SystemExit(1)
print(f"  OK: checked {len(wheels)} wheels")
PY

echo "==> clean-room install from local dist (closed first-party graph)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
uv venv "${TMP}/venv" --python "${PY_VERSION}"
VPY="${TMP}/venv/bin/python"
# First-party wheels come from DIST_DIR; third-party deps resolve from the index.
uv pip install --python "${VPY}" --find-links "${DIST_DIR}" \
  "intentframe-supervisor[native]==$(grep -m1 '^version = ' packages/intentframe-supervisor/pyproject.toml | sed 's/version = "//;s/"//')" \
  "intentframe-edge==$(grep -m1 '^version = ' packages/intentframe-edge/pyproject.toml | sed 's/version = "//;s/"//')" \
  "intentframe-actor==$(grep -m1 '^version = ' packages/intentframe-actor/pyproject.toml | sed 's/version = "//;s/"//')"

echo "==> import every shipped module"
"${VPY}" - <<'PY'
import importlib

mods = [
    "intentframe_core",
    "policy_registry",
    "executor",
    "intentframe_server",
    "intentframe_components",
    "supervisor",
    "intentframe_native_kit",
    "intentframe_edge",
    "intentframe_proxy",
    "intentframe_credentials",
    "intentframe_bundle_sdk",
    "executor_sdk",
    "executor_client",
    "intentframe_client",
    "intentframe_actor",
    "command_shield",
    "intentframe_prompt_library",
]
for mod in mods:
    importlib.import_module(mod)
print("imports ok:", len(mods), "modules")
PY

echo "==> console scripts respond"
"${TMP}/venv/bin/intentframe" --help >/dev/null
"${TMP}/venv/bin/intentframe-edge" --help >/dev/null
echo "    scripts ok"

if [ "${PUBLISH_TEST}" = "1" ]; then
  echo "==> upload to TestPyPI (requires TWINE_* / trusted publishing credentials)"
  uvx twine upload --repository testpypi "${DIST_DIR}"/*
fi

echo "==> OK: ${count} distributions validated"
