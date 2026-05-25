"""Cross-bundle onboarding sections registered by plugin packages."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OnboardingManifest:
    """Plugin-authored cross-cutting onboarding copy (always appended to middle)."""

    sections: tuple[str, ...] = ()
