"""Capability enum and classifier output model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class Capability(Enum):
    """Deterministic capability categories inferred from command syntax."""

    FILE_READ = auto()
    FILE_WRITE = auto()
    NETWORK_OUTBOUND = auto()
    NETWORK_BIND = auto()
    BACKGROUND_PROCESS = auto()
    PROCESS_SIGNAL = auto()
    PACKAGE_INSTALL = auto()
    OPAQUE_EXECUTION = auto()


@dataclass(frozen=True)
class CapabilityReport:
    """Output of the deterministic command classifier.

    ``opaque`` means the classifier could not confidently derive a narrow
    capability set -- the planner should use the opaque fallback template.
    """

    capabilities: frozenset[Capability]
    opaque: bool = False
