"""YAML-driven policy seeds — loader + identity helpers.

Single source of truth for "load a policy YAML into a validated
:class:`UserPolicy`".  Used by:

* ``intentframe_gateway.bootstrap.Bootstrapper`` (runtime seeder)
* ``jarvis_pa.seed_policies`` (dev CLI)
* ``demo.tests.policy_loader`` and ``demo.tests.root_demo.root_policy_loader``
  (test loaders)
* External agent installers / CLIs

Customisation
-------------
End users override any agent's policy by dropping a YAML file at
``~/.intentframe/policies/<agent_id>.yaml``.  The override file uses
the exact same schema as the packaged builtin shipped by the agent
(e.g. ``jarvis_pa/policies/jarvis.yaml``).

Public API
----------
* :func:`load_policy_seed` — parse a YAML into a validated :class:`UserPolicy`.
* :func:`resolve_user_id` — base ``INTENTFRAME_USER_ID`` env value
  (with ``JARVIS_USER_ID`` honoured as a one-release fallback).
* :func:`resolve_agent_id` — base ``INTENTFRAME_AGENT_ID`` env value
  (caller supplies a default for in-process bootstrapping).
* :func:`resolve_seed_path` — first-existing of override path → caller-supplied builtin.
* :func:`override_path` — absolute path to ``~/.intentframe/policies/<agent_id>.yaml``.
* :class:`PolicySchemaVersionError` — raised on missing/stale schema version.

Capability constants live in :mod:`policy_registry.seeds.capabilities`
and are re-exported here for convenience.
"""

from __future__ import annotations

from policy_registry.seeds.capabilities import (
    DEFAULT_TERMINAL_DENY_CAPABILITIES,
    PYTHON_SHELL_ONLY_DENY_CAPABILITIES,
    SENSITIVE_SURFACE_DENY_CAPABILITIES,
)
from policy_registry.seeds.loader import (
    PolicySchemaVersionError,
    load_policy_seed,
)
from policy_registry.seeds.resolver import (
    OVERRIDE_DIR,
    override_path,
    resolve_agent_id,
    resolve_seed_path,
    resolve_user_id,
)

__all__ = [
    "DEFAULT_TERMINAL_DENY_CAPABILITIES",
    "OVERRIDE_DIR",
    "PYTHON_SHELL_ONLY_DENY_CAPABILITIES",
    "PolicySchemaVersionError",
    "SENSITIVE_SURFACE_DENY_CAPABILITIES",
    "load_policy_seed",
    "override_path",
    "resolve_agent_id",
    "resolve_seed_path",
    "resolve_user_id",
]
