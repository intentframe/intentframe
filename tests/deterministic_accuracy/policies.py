"""Policy profiles exercised in the DG accuracy matrix.

Each profile returns a ``UserContext`` with real ``TerminalConstraints``
(no mocks).  Profiles are expressed in terms of user intent, not DG
internals, so new ones can be added without understanding the gates.

Shared floor: every profile includes the system-floor blocked_patterns.
In production these come from :data:`policy_registry.registry.
SYSTEM_TERMINAL_BLOCKED_PATTERNS` after merging.  Here we embed a small
representative subset so the tests do not depend on the merge layer —
the merge layer is covered separately in
``tests/test_terminal_blocklist.py``.
"""

from __future__ import annotations

from typing import Callable

from intentframe_core.types import UserContext
from intentframe_gateway.bootstrap import (
    DEFAULT_TERMINAL_DENY_CAPABILITIES,
    PYTHON_SHELL_ONLY_DENY_CAPABILITIES,
)
from policy_registry.constraints.terminal import TerminalConstraints
from policy_registry.models import ActionPermission


# Representative subset of SYSTEM_TERMINAL_BLOCKED_PATTERNS.  Keeping the
# list small and local means a floor-merge change in the registry cannot
# silently flip accuracy-matrix outcomes.
_BASE_BLOCKED: list[str] = ["sudo ", "rm -rf /", "mkfs", "dd if=", "chmod 777"]


def _user(constraints: TerminalConstraints) -> UserContext:
    return UserContext(
        user_id="dg-accuracy",
        agent_id="dg-accuracy-agent",
        allowed_actions={
            "RUN_COMMAND": ActionPermission(safe=False, constraints=constraints),
        },
    )


def permissive() -> UserContext:
    """RUN_COMMAND allowed, system-floor patterns only.

    Used to establish a baseline: commands that ALLOW here but BLOCK in
    stricter profiles reveal which gate fires in each.
    """
    return _user(TerminalConstraints(blocked_patterns=list(_BASE_BLOCKED)))


def developer() -> UserContext:
    """Typical dev loop: pip/npm/git allowed, network listeners denied.

    The ``network_bind`` family is emitted bare today (``capability:
    network_bind``) but may be refined into sub-tags in the future
    (``...:listener``, ``...:http_server``).  Listing both the bare
    form and the ``:*`` glob keeps the policy robust across the
    refactor \u2014 any future sub-tag is still denied, and the current
    bare emission is matched exactly.
    """
    return _user(
        TerminalConstraints(
            blocked_patterns=list(_BASE_BLOCKED),
            deny_capabilities=frozenset(
                {
                    "capability:network_bind",
                    "capability:network_bind:*",
                }
            ),
        )
    )


def data_analyst() -> UserContext:
    """Notebook user: no package installs, no network listeners.

    See :func:`developer` for why ``network_bind`` is listed twice.
    """
    return _user(
        TerminalConstraints(
            blocked_patterns=list(_BASE_BLOCKED),
            deny_capabilities=frozenset(
                {
                    "capability:package_install",
                    "capability:package_install:*",
                    "capability:network_bind",
                    "capability:network_bind:*",
                }
            ),
        )
    )


def locked_down() -> UserContext:
    """Observation-only: every capability tag must be read_only:*."""
    return _user(
        TerminalConstraints(
            blocked_patterns=list(_BASE_BLOCKED),
            allow_capabilities=frozenset({"capability:read_only:*"}),
        )
    )


def python_shell_only() -> UserContext:
    """Python/shell command profile plus the sensitive-surface clamp.

    Pulls the canonical deny set from
    :data:`intentframe_gateway.bootstrap.DEFAULT_TERMINAL_DENY_CAPABILITIES`
    (union of :data:`PYTHON_SHELL_ONLY_DENY_CAPABILITIES` and
    :data:`SENSITIVE_SURFACE_DENY_CAPABILITIES`) so the accuracy corpus
    automatically tracks future changes to the default deny set.
    """
    return _user(
        TerminalConstraints(
            blocked_patterns=list(_BASE_BLOCKED),
            deny_capabilities=DEFAULT_TERMINAL_DENY_CAPABILITIES,
        )
    )


def no_run_command() -> UserContext:
    """RUN_COMMAND not in allowed_actions \u2014 permission-gate BLOCK on everything."""
    return UserContext(
        user_id="dg-accuracy-no-rc",
        agent_id="dg-accuracy-agent",
        allowed_actions={},
    )


PROFILES: dict[str, Callable[[], UserContext]] = {
    "permissive": permissive,
    "developer": developer,
    "data_analyst": data_analyst,
    "locked_down": locked_down,
    "python_shell_only": python_shell_only,
    "no_run_command": no_run_command,
}
