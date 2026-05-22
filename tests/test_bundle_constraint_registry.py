"""Startup invariants for bundle constraint-type wiring."""

from __future__ import annotations

from policy_registry.constraints import (
    ApiConstraints,
    BrowserConstraints,
    CalendarConstraints,
    EmailConstraints,
    FileConstraints,
    HostFileConstraints,
    MessageConstraints,
    TerminalConstraints,
)

ALL_ACTION_CONSTRAINT_TYPES: frozenset[type] = frozenset({
    ApiConstraints,
    BrowserConstraints,
    CalendarConstraints,
    EmailConstraints,
    FileConstraints,
    HostFileConstraints,
    MessageConstraints,
    TerminalConstraints,
})

# Documented gap — see TODO/refactor-abstract/deterministic-enforcement-map.md
KNOWN_UNMAPPED_CONSTRAINT_TYPES: frozenset[type] = frozenset({
    CalendarConstraints,
})

WIRED_CONSTRAINT_TYPES: frozenset[type] = (
    ALL_ACTION_CONSTRAINT_TYPES - KNOWN_UNMAPPED_CONSTRAINT_TYPES
)


def test_every_action_constraint_type_has_checker_or_known_gap() -> None:
    """Each ``ConstraintTypes`` member maps to CONSTRAINT_CHECKERS or is allowlisted."""
    from intentframe_action_bundle.bundles.register import ensure_bundles_registered
    from intentframe_action_bundle.manifest import constraint_checkers

    ensure_bundles_registered()
    checker_types = frozenset(constraint_checkers().keys())

    unmapped = ALL_ACTION_CONSTRAINT_TYPES - checker_types
    assert unmapped == KNOWN_UNMAPPED_CONSTRAINT_TYPES, (
        "constraint types missing from CONSTRAINT_CHECKERS: "
        f"{sorted(t.__name__ for t in unmapped - KNOWN_UNMAPPED_CONSTRAINT_TYPES)}; "
        "wire a checker/bundle or add to KNOWN_UNMAPPED_CONSTRAINT_TYPES"
    )
    assert checker_types == WIRED_CONSTRAINT_TYPES


def test_checker_by_type_matches_constraint_checkers() -> None:
    """Bundle registry and CONSTRAINT_CHECKERS stay in sync for wired types."""
    from intentframe_action_bundle.bundles.register import ensure_bundles_registered
    from intentframe_action_bundle.manifest import constraint_checkers
    from intentframe_bundle_sdk.registry import registered_checker_constraint_types

    ensure_bundles_registered()
    checker_types = frozenset(constraint_checkers().keys())
    bundle_types = registered_checker_constraint_types()

    assert bundle_types == WIRED_CONSTRAINT_TYPES
    assert checker_types == bundle_types
