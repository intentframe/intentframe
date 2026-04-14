"""Canonical path normalization for sandbox profiles.

Every path that enters an ``ExecutionPlan`` must go through
``canonical_sandbox_path`` so that Seatbelt rules match what the
kernel actually sees.  On macOS this resolves symlinks like
``/var`` → ``/private/var`` and ``/tmp`` → ``/private/tmp``.
"""

from __future__ import annotations

import os


def canonical_sandbox_path(raw: str) -> str:
    """Expand, absolutize, and resolve a path to its canonical form.

    Pipeline: expanduser → expandvars → abspath → realpath

    If the path does not exist on disk, ``realpath`` still resolves
    known symlink prefixes (e.g. ``/var`` → ``/private/var``).
    """
    expanded = os.path.expandvars(os.path.expanduser(raw))
    return os.path.realpath(expanded)
