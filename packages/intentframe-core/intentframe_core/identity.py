"""Runtime identity helpers shared across substrate services and native packs.

These helpers resolve the *owning user's* HOME directory in a way that works
whether the process runs as a normal user or as root via ``sudo``.  Both the
resource-registry deny floor and the macOS executor sandbox venv resolver
need the same semantics so ``~`` expansion stays consistent under root-demo.
"""

from __future__ import annotations

import logging
import os
import pwd

logger = logging.getLogger(__name__)

__all__ = ["owner_home"]


def owner_home() -> str | None:
    """Return the HOME of the intended runtime identity, or ``None``.

    ``None`` means the executor is running as bare root with no
    ``SUDO_USER`` hint, i.e. there is no well-defined owning user for
    ``~`` expansion. Callers must treat this as an error when a
    user-scoped path is required.
    """
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            return pwd.getpwnam(sudo_user).pw_dir
        except KeyError:
            logger.warning(
                "SUDO_USER=%r set but no such user; falling back to uid-based "
                "HOME resolution",
                sudo_user,
            )

    uid = os.getuid()
    if uid == 0:
        return None

    try:
        return pwd.getpwuid(uid).pw_dir
    except KeyError:
        return None
