"""
WRITE_FILE classification heuristics — destination predicates.

Pure, synchronous, side-effect-free functions.  No IO, no logging, no
state.  Given the same inputs they return the same answer every time.

Public helper:

  ``is_sensitive_write_path(target)``
    Case-insensitive substring match against virtual-path fragments
    for sensitive system locations (shell startup files, credential
    stores, privilege config, persistence plists, Python runtime
    hooks, etc.).  Consumed by :class:`DeterministicGuardian` as a
    BLOCK rule for WRITE_FILE — the virtual-path peer of the VFS
    floor at ``resource_registry.floor.DENY_WRITE_PREFIXES``, which
    enforces the same families on the canonicalized real path at
    I/O time.
"""

from __future__ import annotations

# ────────────────────────────────────────────────────────────────
# Destination classification
# ────────────────────────────────────────────────────────────────

# Virtual-path fragments that indicate the destination is a sensitive
# system location — shell startup files, credential stores, privilege
# config, persistence / daemon plists, Python runtime hooks.  These
# are substring fragments because the pipeline sees virtual paths
# (e.g. ``/home/.zshrc``, ``/library/launchagents/foo.plist``) whose
# real paths are enforced separately by ``resource_registry.floor``.
# The floor blocks the actual write at the VFS layer; this list is the
# routing hint that fires *before* the floor, at DG/AE time.
SENSITIVE_WRITE_PATH_FRAGMENTS: tuple[str, ...] = (
    # Shell startup files
    "/.zshrc",
    "/.zshenv",
    "/.zprofile",
    "/.bashrc",
    "/.bash_profile",
    "/.profile",
    # Launchd / persistence daemons
    "/launchagents",
    "/launchdaemons",
    # SSH / credentials
    "/.ssh/",
    "/.gnupg/",
    # Git config / hooks
    "/.gitconfig",
    "/.git/hooks/",
    # Privilege / auth
    "/etc/sudoers",
    "/etc/ssh",
    "/etc/pam.d",
    # Python runtime hooks
    ".pth",
    "sitecustomize.py",
    "usercustomize.py",
)


def is_sensitive_write_path(target: str | None) -> bool:
    """Return True when the virtual destination is a sensitive system location.

    Case-insensitive substring match — deliberately loose because the
    pipeline has already virtualized the path and the floor at the VFS
    layer owns the hard enforcement.  False positives here cost one AE
    LLM call on a more thorough prompt; false negatives cost nothing
    structural because the floor still blocks a real write.
    """
    if not target:
        return False
    lowered = target.lower()
    for frag in SENSITIVE_WRITE_PATH_FRAGMENTS:
        if frag in lowered:
            return True
    return False

