"""Non-negotiable deny-write floor for file-tool actions.

Analogue of ``executor.sandbox.templates.NON_NEGOTIABLE_DENY_WRITE`` for
WRITE_FILE / DELETE_FILE / APPEND_ROW.  The sandbox's deny list only
protects ``RUN_COMMAND`` (via the Seatbelt profile at
``executor/sandbox/platforms/macos.py``); file-tool actions go through
``executor/platforms/macos/virtual_filesystem.py`` and bypass the
kernel-level floor entirely.  This module gives the VFS a symmetric
floor so ``WRITE_FILE`` to a launchd plist / shell rc file /
``~/.ssh/*`` / sudoers file is rejected deterministically regardless of
how broad the agent's ``allowed_paths`` policy is.

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
