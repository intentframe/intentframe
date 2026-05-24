"""Non-negotiable deny-write floor + shared real-path canonicalization.

Analogue of ``executor.sandbox.templates.NON_NEGOTIABLE_DENY_WRITE`` for
mutating file-tool actions (WRITE_FILE / DELETE_FILE / APPEND_ROW, plus
WRITE_HOST_FILE / DELETE_HOST_FILE for the host-file family).  The
sandbox's deny list only protects ``RUN_COMMAND`` (via the Seatbelt
profile at ``executor/sandbox/platforms/macos.py``); file-tool actions
go through the VFS / host-file adapters and bypass the kernel-level
floor entirely.  This module gives both families a symmetric floor so
writes/deletes to a launchd plist / shell rc file / ``~/.ssh/*`` /
sudoers file are rejected deterministically regardless of how broad the
agent's ``allowed_paths`` / ``allowed_host_paths`` policy is.

In addition to the floor list, this module exposes
:func:`canonicalize_real_path` — the single canonicalization primitive
the Deterministic Guardian, ``HostFileChecker``, and ``HostFilesAdapter``
all share so their deny-prefix comparisons always speak the same
canonical form.

Design choices:

- **Resource-registry home, not executor.**  The floor is semantically
  "what no workspace can opt out of" — the natural companion to
  ``ResourceMount.writable`` (which is per-mount consent).  Keeping it
  here preserves the extraction-as-microservice story of the registry
  and keeps executor code unchanged.
- **Pre-expanded tuple.**  ``~`` is expanded at module-load time using
  :func:`executor.sandbox.venv.owner_home` so the floor honours
  ``SUDO_USER`` under root-via-sudo — the same identity-aware HOME the
  executor venv uses.  No per-call expansion.
- **Canonicalized via realpath.**  Matches the sandbox's
  ``canonical_sandbox_path`` convention so both layers compare against
  the same kernel-visible form (e.g. ``/tmp`` → ``/private/tmp`` on
  macOS).
- **Prefix compare, not fnmatch.**  The floor is about directories and
  whole trees.  ``match_deny_prefix`` returns the matched prefix string
  for audit logging; callers treat a non-None result as "deny".

The list is a deliberate superset of
``executor.sandbox.templates.NON_NEGOTIABLE_DENY_WRITE`` covering the
root-demo hardening categories named in
``TODO/root-demo-policy-driven-sandbox.md``:

- auto-load / persistence: LaunchAgents/LaunchDaemons, shell rc files,
  ``~/.ssh``, ``~/.gnupg``, git workflow / hook directories;
- privilege: ``/etc/sudoers*``, ``/etc/sshd_config``, ``/etc/pam.d``;
- kexts: ``/Library/Extensions``, ``/System/Library/Extensions``;
- secrets / user content: ``~/Library/Keychains``, ``~/Library/Messages``,
  ``~/Library/Mail``;
- system tree: ``/System``, ``/usr``, ``/bin``, ``/sbin``;
- product internals: ``~/.intentframe``.

A symmetry test in ``tests/test_vfs_floor.py`` asserts that the
sandbox's narrower list is a subset of this one so drift is caught at
test time.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

# Identity-aware HOME resolution lives in executor.sandbox.venv today.
# Importing it does NOT edit sandbox code — it's a read-only dependency
# that lets us share the "respect SUDO_USER" behaviour without
# duplicating the pwd.getpwnam logic.  If the resource-registry is ever
# extracted as a microservice, lift owner_home() to a neutral location
# (intentframe_core.identity) and update both sides in one go.
from executor.sandbox.venv import owner_home

logger = logging.getLogger(__name__)

__all__ = [
    "DENY_WRITE_PREFIXES",
    "canonicalize_real_path",
    "match_deny_prefix",
]


# Raw prefix patterns — may contain ``~`` to denote the owning user's
# HOME.  Expansion happens once at module load via ``_expand_prefix``.
_RAW_DENY_WRITE_PREFIXES: tuple[str, ...] = (
    # ── System tree ─────────────────────────────────────────────
    "/System",
    "/usr",
    "/bin",
    "/sbin",
    # ── Launchd (persistence) ──────────────────────────────────
    "/Library/LaunchDaemons",
    "/Library/LaunchAgents",
    "~/Library/LaunchAgents",
    # ── Shell rc (auto-load on new shells) ─────────────────────
    "~/.zshrc",
    "~/.bashrc",
    "~/.zprofile",
    "~/.bash_profile",
    "~/.zshenv",
    "~/.profile",
    # ── Secrets / credentials ──────────────────────────────────
    "~/.ssh",
    "~/.gnupg",
    "~/.gitconfig",
    # ── Privilege / auth configs ───────────────────────────────
    "/etc/sudoers",
    "/etc/sudoers.d",
    "/etc/sshd_config",
    "/etc/pam.d",
    # ── Kernel extensions ──────────────────────────────────────
    "/Library/Extensions",
    "/System/Library/Extensions",
    # ── User content stores (Keychain / Messages / Mail) ───────
    "~/Library/Keychains",
    "~/Library/Messages",
    "~/Library/Mail",
    # ── Product internals ──────────────────────────────────────
    "~/.intentframe",
)


def _expand_prefix(raw: str) -> str | None:
    """Expand ``~`` via identity-aware HOME, then canonicalize.

    Returns ``None`` when the raw prefix contains ``~`` and no owning
    user can be determined (bare root with no ``SUDO_USER``).  Such
    entries are dropped from the expanded list so the floor stays
    well-formed; the dropped entry is logged at warning level so
    deployments running as bare root can audit the gap.

    Non-``~`` prefixes are always canonicalized and returned.
    """
    if raw.startswith("~"):
        home = owner_home()
        if home is None:
            logger.warning(
                "resource_registry.floor: dropping %r — running as bare root "
                "with no SUDO_USER, cannot expand ~",
                raw,
            )
            return None
        expanded = home + raw[1:]
    else:
        expanded = raw

    # ``realpath`` resolves known symlink prefixes (``/tmp`` →
    # ``/private/tmp``) even when the path doesn't exist.
    return os.path.realpath(expanded)


def _build_prefixes() -> tuple[str, ...]:
    expanded: list[str] = []
    for raw in _RAW_DENY_WRITE_PREFIXES:
        resolved = _expand_prefix(raw)
        if resolved is not None:
            expanded.append(resolved)
    return tuple(expanded)


DENY_WRITE_PREFIXES: tuple[str, ...] = _build_prefixes()
"""Canonicalized, pre-expanded deny-write prefixes.

Every entry is an absolute path with ``~`` resolved against the owning
user's HOME.  Compare against a canonicalized real path via
:func:`match_deny_prefix`.
"""


def canonicalize_real_path(raw: str) -> str:
    """Return the canonical real-path string form of *raw*.

    Single canonicalization primitive shared between:

    - :class:`intentframe_components.guardian.deterministic.DeterministicGuardian`
      (host-file floor gates)
    - :class:`intentframe_action_bundle.host_files.bundle.HostFilesActionBundle`
      (per-action allowlist match)
    - :class:`executor.platforms.macos.adapters.host_files.HostFilesAdapter`
      (pre-I/O enforcement)

    All three must agree on the canonical string form before calling
    :func:`match_deny_prefix`, otherwise a symlink escape could match
    one canonicalization but not another.

    Semantics mirror
    :func:`executor.platforms.macos.virtual_filesystem._canonical_real_path`
    (re-implemented here rather than imported so ``resource_registry``
    stays free of ``executor`` deps):

    - ``~`` is expanded via :func:`os.path.expanduser`.
    - ``Path.resolve(strict=False)`` resolves existing symlink prefixes
      (e.g. ``/tmp`` → ``/private/tmp`` on macOS).
    - For nonexistent leaves (typical ``WRITE_HOST_FILE`` target), we
      fall back to resolving the parent and re-joining the literal leaf
      name so "about to be created" paths still canonicalize correctly.

    The empty string is returned unchanged so callers can distinguish
    "no target" from a canonical empty path.
    """
    if not raw:
        return raw
    expanded = os.path.expanduser(raw)
    p = Path(expanded)
    try:
        return str(p.resolve(strict=False))
    except OSError:
        parent = p.parent.resolve(strict=False)
        return str(parent / p.name)


def match_deny_prefix(real_path: str) -> str | None:
    """Return the matched prefix if *real_path* is under the floor, else None.

    The caller is expected to pass a canonical real path — typically the
    result of ``Path(raw).resolve()`` (when the file exists) or
    ``Path(raw).parent.resolve() / Path(raw).name`` (when the file is
    being created).  This function does NOT canonicalize its input; the
    floor prefixes are already canonical and comparing two non-canonical
    strings would miss symlink-based escapes.

    A match means one of:
      - ``real_path`` equals a floor prefix exactly, or
      - ``real_path`` is under a floor prefix (``real_path == prefix``
        or ``real_path.startswith(prefix + os.sep)``).

    Returns the matched prefix string so callers can include it in audit
    messages (``matched_gate="floor: /etc/sudoers"``).
    """
    if not real_path:
        return None

    # Treat the input as opaque text for prefix matching — the caller is
    # responsible for canonicalization.  We still strip a trailing
    # separator so ``/etc/sudoers.d/`` matches the ``/etc/sudoers.d``
    # prefix cleanly.
    candidate = real_path.rstrip(os.sep) or real_path

    for prefix in DENY_WRITE_PREFIXES:
        if candidate == prefix:
            return prefix
        if candidate.startswith(prefix + os.sep):
            return prefix
    return None
