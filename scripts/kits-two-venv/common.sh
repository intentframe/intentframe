# Shared paths and helpers for the kits two-venv local harness.
# Source this file; do not execute directly.
#
# Two-venv model:
#   RUNTIME_VENV  — substrate + edge/proxy (+ kit wheels after bootstrap); UDS under RUN_DIR
#   CLIENT_VENV   — full repo via uv sync (demo tests only)
#
# Internals use ~/.intentframe/run/*.sock. External tests use EDGE_BASE_URL HTTP.
#
# Helpers:
#   _kits_require_repo / _runtime_venv / _client_venv / _runtime_constraints
#   _kits_freeze_runtime_constraints  — importlib.metadata name==version pins
#   _kits_primary_wheels              — KIT_WHEELS or intentframe_native_kit-*.whl
#   _kits_kit_parent                    — installed kit dir for profile YAML paths

if [[ -z "${BASH_VERSION:-}" ]]; then
  echo "common.sh must be sourced from bash" >&2
  return 1 2>/dev/null || exit 1
fi

_KITS_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${_KITS_SCRIPT_DIR}/../.." && pwd)"

RUNTIME_VENV="${RUNTIME_VENV:-${REPO_ROOT}/.venv-runtime}"
CLIENT_VENV="${CLIENT_VENV:-${REPO_ROOT}/.venv}"
INTENTFRAME_KITS_DIR="${INTENTFRAME_KITS_DIR:-${REPO_ROOT}/.intentframe/kits}"

RUNTIME_PYTHON="${RUNTIME_VENV}/bin/python"
CLIENT_PYTHON="${CLIENT_VENV}/bin/python"

# Pins every runtime-venv distribution after setup_runtime_venv (substrate + edge/proxy);
# kit installs must not override these.
RUNTIME_CONSTRAINTS="${RUNTIME_CONSTRAINTS:-${REPO_ROOT}/.intentframe/runtime-constraints.txt}"

# Runtime processes intentionally use the product defaults.
# Internals communicate over ~/.intentframe/run/*.sock; tests reach them only
# through the edge via INTENTFRAME_*_URL.
RUN_DIR="${HOME}/.intentframe/run"
EDGE_HOST="${INTENTFRAME_EDGE_HOST:-0.0.0.0}"
EDGE_PORT="${INTENTFRAME_EDGE_PORT:-8443}"
EDGE_BASE_URL="http://127.0.0.1:${EDGE_PORT}"

# Operator-owned executor profile (not shipped inside the bare runtime venv).
EXECUTOR_CONFIG="${EXECUTOR_CONFIG:-${REPO_ROOT}/demo/config/executor_hashicorp.yaml}"

PID_DIR="${REPO_ROOT}/.intentframe/kits-two-venv"
SUPERVISOR_PID_FILE="${PID_DIR}/supervisor.pid"
EDGE_PID_FILE="${PID_DIR}/edge.pid"

_kits_require_repo() {
  if [[ ! -f "${REPO_ROOT}/pyproject.toml" ]]; then
    echo "REPO_ROOT does not look like the intentframe repo: ${REPO_ROOT}" >&2
    return 1
  fi
}

_kits_require_runtime_venv() {
  if [[ ! -x "${RUNTIME_PYTHON}" ]]; then
    echo "Runtime venv missing. Run: ${REPO_ROOT}/scripts/kits-two-venv/setup_runtime_venv.sh" >&2
    return 1
  fi
}

_kits_require_client_venv() {
  if [[ ! -x "${CLIENT_PYTHON}" ]]; then
    echo "Client venv missing. From repo root run: uv sync" >&2
    return 1
  fi
}

_kits_require_runtime_constraints() {
  if [[ ! -f "${RUNTIME_CONSTRAINTS}" ]]; then
    echo "Runtime constraints missing. Re-run setup_runtime_venv.sh: ${RUNTIME_CONSTRAINTS}" >&2
    return 1
  fi
}

# Freeze the bare runtime venv so kit installs cannot upgrade/downgrade pinned runtime deps.
# uv pip freeze includes editable/file:// lines that are invalid as --constraints; pin
# every installed distribution as name==version instead.
_kits_freeze_runtime_constraints() {
  if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required" >&2
    return 1
  fi
  mkdir -p "$(dirname "${RUNTIME_CONSTRAINTS}")"
  "${RUNTIME_PYTHON}" - <<'PY' > "${RUNTIME_CONSTRAINTS}"
import importlib.metadata as m

seen: set[str] = set()
for dist in sorted(m.distributions(), key=lambda d: (d.metadata.get("Name") or "").lower()):
    name = dist.metadata.get("Name")
    if not name or name in seen:
        continue
    seen.add(name)
    print(f"{name}=={dist.version}")
PY
  echo "[kits] wrote runtime constraints ($(wc -l < "${RUNTIME_CONSTRAINTS}" | tr -d ' ') packages) -> ${RUNTIME_CONSTRAINTS}"
}

# Primary kit wheels to install (deps resolved by uv; other wheels in KITS_DIR are find-links only).
_kits_primary_wheels() {
  if [[ -n "${KIT_WHEELS:-}" ]]; then
    # shellcheck disable=SC2206
    local wheels=( ${KIT_WHEELS} )
    printf '%s\n' "${wheels[@]}"
    return 0
  fi
  shopt -s nullglob
  local wheels=( "${INTENTFRAME_KITS_DIR}"/intentframe_native_kit-*.whl )
  shopt -u nullglob
  if [[ ${#wheels[@]} -eq 0 ]]; then
    return 1
  fi
  printf '%s\n' "${wheels[@]}"
}

_kits_kit_parent() {
  "${RUNTIME_PYTHON}" -c 'import intentframe_native_kit as k, pathlib; print(pathlib.Path(k.__file__).parent)'
}
