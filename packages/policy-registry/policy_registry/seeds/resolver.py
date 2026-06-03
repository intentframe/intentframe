"""Identity / override-path resolution for policy seeds.

The seeds module deliberately knows nothing about profiles or which
agent owns which YAML; it just exposes the small environment-aware
helpers everyone needs:

* :func:`resolve_user_id` — read ``INTENTFRAME_USER_ID`` (with the
  legacy ``JARVIS_USER_ID`` honoured as a fallback for one release).
* :func:`resolve_agent_id` — read ``INTENTFRAME_AGENT_ID``; returns the
  caller-supplied ``default`` when unset (so external agents can
  hard-require it while in-process callers like the gateway can supply
  a sensible default like ``"jarvis"``).
* :func:`override_path` — ``~/.intentframe/policies/<agent_id>.yaml``,
  the supported customisation knob for end users.
* :func:`resolve_seed_path` — first existing of ``override_path`` →
  the caller-supplied builtin path.

The Jarvis policy YAMLs live in :mod:`jarvis_pa.policies`; external
agents ship their own YAMLs.  This module never assumes either.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

OVERRIDE_DIR: Path = Path("~/.intentframe/policies").expanduser()


def resolve_user_id() -> str:
    """Resolve the operator/owner id from the environment.

    Reads ``INTENTFRAME_USER_ID`` first.  Falls back to the legacy
    ``JARVIS_USER_ID`` (deprecated; kept as a one-release alias so
    existing setup scripts keep working).  Falls back to
    ``"jarvis_default"`` if neither is set — fine for dev, never
    fine for a real install.
    """
    return (
        os.environ.get("INTENTFRAME_USER_ID")
        or os.environ.get("JARVIS_USER_ID")
        or "jarvis_default"
    )


def resolve_agent_id(default: str | None = None) -> str | None:
    """Resolve the agent id from ``INTENTFRAME_AGENT_ID``.

    Returns ``default`` when the env var is unset.  External agents
    should pass ``default=None`` and treat ``None`` as a hard error;
    in-process callers (e.g. the gateway bootstrapping Jarvis) may
    pass ``"jarvis"`` so a fresh install Just Works.
    """
    return os.environ.get("INTENTFRAME_AGENT_ID") or default


def override_path(agent_id: str) -> Path:
    """User-override location: ``~/.intentframe/policies/<agent_id>.yaml``.

    Always returns a Path; callers should test ``.exists()``.
    """
    if not agent_id:
        raise ValueError("override_path requires a non-empty agent_id")
    return OVERRIDE_DIR / f"{agent_id}.yaml"


def resolve_seed_path(agent_id: str, builtin_path: Path) -> Path:
    """Resolve which YAML to load for ``agent_id``.

    Order:
        1. ``~/.intentframe/policies/<agent_id>.yaml`` if present
           (user override).
        2. ``builtin_path`` supplied by the caller (typically a
           packaged YAML like ``jarvis_pa/policies/jarvis.yaml``).

    The user-override branch is the supported customisation knob:
    end users copy a builtin YAML to that path, edit it, restart the
    gateway, and the new policy is seeded on next bootstrap.
    """
    override = override_path(agent_id)
    if override.exists():
        logger.info(
            "Using user-override policy seed for agent_id=%r at %s",
            agent_id, override,
        )
        return override
    return builtin_path
