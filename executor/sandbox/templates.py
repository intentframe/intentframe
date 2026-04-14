"""Sandbox template definitions and capability lattice.

Templates form an ordered lattice from narrowest (PURE_COMPUTE) to broadest
(UNRESTRICTED).  Each template declares which capabilities it grants.  The
planner picks the narrowest template that covers all capabilities a command
requires.
"""

from __future__ import annotations

from enum import Enum

from executor.sandbox.capabilities import Capability


class SandboxTemplate(str, Enum):
    PURE_COMPUTE = "pure_compute"
    FILE_READ_ONLY = "file_read_only"
    FILE_READ_WRITE = "file_read_write"
    NETWORK_OUTBOUND = "network_outbound"
    NETWORK_FULL = "network_full"
    UNRESTRICTED = "unrestricted"


TEMPLATE_ORDER: tuple[SandboxTemplate, ...] = (
    SandboxTemplate.PURE_COMPUTE,
    SandboxTemplate.FILE_READ_ONLY,
    SandboxTemplate.FILE_READ_WRITE,
    SandboxTemplate.NETWORK_OUTBOUND,
    SandboxTemplate.NETWORK_FULL,
    SandboxTemplate.UNRESTRICTED,
)

TEMPLATE_CAPABILITIES: dict[SandboxTemplate, frozenset[Capability]] = {
    SandboxTemplate.PURE_COMPUTE: frozenset(),
    SandboxTemplate.FILE_READ_ONLY: frozenset({
        Capability.FILE_READ,
    }),
    SandboxTemplate.FILE_READ_WRITE: frozenset({
        Capability.FILE_READ,
        Capability.FILE_WRITE,
    }),
    SandboxTemplate.NETWORK_OUTBOUND: frozenset({
        Capability.FILE_READ,
        Capability.FILE_WRITE,
        Capability.NETWORK_OUTBOUND,
        Capability.PACKAGE_INSTALL,
    }),
    SandboxTemplate.NETWORK_FULL: frozenset({
        Capability.FILE_READ,
        Capability.FILE_WRITE,
        Capability.NETWORK_OUTBOUND,
        Capability.NETWORK_BIND,
        Capability.PACKAGE_INSTALL,
        Capability.BACKGROUND_PROCESS,
    }),
    SandboxTemplate.UNRESTRICTED: frozenset({
        Capability.FILE_READ,
        Capability.FILE_WRITE,
        Capability.NETWORK_OUTBOUND,
        Capability.NETWORK_BIND,
        Capability.PACKAGE_INSTALL,
        Capability.BACKGROUND_PROCESS,
        Capability.PROCESS_SIGNAL,
        Capability.OPAQUE_EXECUTION,
    }),
}

# ---------------------------------------------------------------------------
# Non-negotiable deny lists -- enforced by every template, including
# UNRESTRICTED.  Paths containing ~ are expanded at profile-build time.
# ---------------------------------------------------------------------------

NON_NEGOTIABLE_DENY_WRITE: tuple[str, ...] = (
    "/System",
    "/usr",
    "/bin",
    "/sbin",
    "/Library/LaunchDaemons",
    "/Library/LaunchAgents",
    "~/Library/LaunchAgents",
)

NON_NEGOTIABLE_DENY_ACCESS: tuple[str, ...] = (
    "~/.intentframe",
)


def minimum_template(capabilities: frozenset[Capability]) -> SandboxTemplate | None:
    """Return the narrowest template that covers *capabilities*, or ``None``."""
    for tmpl in TEMPLATE_ORDER:
        if capabilities <= TEMPLATE_CAPABILITIES[tmpl]:
            return tmpl
    return None
