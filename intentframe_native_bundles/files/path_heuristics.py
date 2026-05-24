"""
WRITE_FILE destination classification helpers.

Pure, synchronous, side-effect-free functions.  No I/O, no logging, no
state.

``is_sensitive_write_path(target)`` returns a boolean derived from
case-insensitive substring matching against a fragment list.

``classify_path_category(target)`` returns one of the
``FILE_PATH_CATEGORY`` literals, falling back to ``"unknown"``.

Both helpers are derived from the same ordered fragment table.
"""

from __future__ import annotations

from intentframe_action_bundle.files.evidence import FILE_PATH_CATEGORY

# ────────────────────────────────────────────────────────────────
# Destination classification
# ────────────────────────────────────────────────────────────────

# Ordered category → fragments table.  Order matters: the first
# matching entry wins, so more specific categories are listed before
# broader ones (e.g. ``credential_store`` before ``system_config``).
# Fragments are compared case-insensitively against the target string;
# they are substring matches because the pipeline sees either virtual
# paths (``/home/.zshrc``) or raw host paths (``/Users/x/.zshrc``) and
# the substring form lets one vocabulary cover both.
#
# Category labels:
# ``shell_init``, ``launch_agent``, ``credential_store``,
# ``persistence_hook``, ``system_config``, ``dev_workspace``,
# ``cache_or_tmp``, ``user_document``, ``unknown``.
_CATEGORY_FRAGMENTS: tuple[tuple[FILE_PATH_CATEGORY, tuple[str, ...]], ...] = (
    (
        "credential_store",
        (
            "/.ssh/",
            "/.gnupg/",
            # Match both the common host-path and virtual-path forms.
            "~/Library/Keychains",
            "/library/keychains",
        ),
    ),
    (
        "launch_agent",
        ("/launchagents", "/launchdaemons"),
    ),
    (
        "shell_init",
        (
            "/.zshrc",
            "/.zshenv",
            "/.zprofile",
            "/.bashrc",
            "/.bash_profile",
            "/.profile",
        ),
    ),
    (
        "persistence_hook",
        (
            ".pth",
            "sitecustomize.py",
            "usercustomize.py",
            "/.git/hooks/",
            # ``.gitconfig`` is grouped with other automatically loaded
            # hook/config files.
            "/.gitconfig",
        ),
    ),
    (
        "system_config",
        (
            "/etc/sudoers",
            "/etc/ssh",
            "/etc/pam.d",
        ),
    ),
    (
        "dev_workspace",
        (
            "/.github/",
        ),
    ),
    (
        "user_document",
        (
            "/documents/",
            "/desktop/",
            "/downloads/",
        ),
    ),
)


# Subset of categories included in ``SENSITIVE_WRITE_PATH_FRAGMENTS``.
_DG_SENSITIVE_CATEGORIES: frozenset[FILE_PATH_CATEGORY] = frozenset({
    "credential_store",
    "launch_agent",
    "shell_init",
    "persistence_hook",
    "system_config",
})


SENSITIVE_WRITE_PATH_FRAGMENTS: tuple[str, ...] = tuple(
    frag
    for category, frags in _CATEGORY_FRAGMENTS
    if category in _DG_SENSITIVE_CATEGORIES
    for frag in frags
)
"""Flat tuple of fragments derived from ``_CATEGORY_FRAGMENTS``."""


def is_sensitive_write_path(target: str | None) -> bool:
    """Return ``True`` when *target* matches a sensitive-path fragment."""
    if not target:
        return False
    lowered = target.lower()
    for frag in SENSITIVE_WRITE_PATH_FRAGMENTS:
        if frag.lower() in lowered:
            return True
    return False


def classify_path_category(target: str | None) -> FILE_PATH_CATEGORY:
    """Return the semantic category of *target*, falling back to ``"unknown"``.

    Ordering of ``_CATEGORY_FRAGMENTS`` is significant — the first
    matching category wins.  ``None`` / empty target and unmatched
    targets both return ``"unknown"``.
    """
    if not target:
        return "unknown"
    lowered = target.lower()
    for category, frags in _CATEGORY_FRAGMENTS:
        for frag in frags:
            if frag.lower() in lowered:
                return category
    return "unknown"
