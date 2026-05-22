"""Record when YAML constraints exist but no CONSTRAINT_CHECKERS entry is wired."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from intentframe_bundle_sdk.types import BundleContext

logger = logging.getLogger(__name__)


def note_missing_constraint_checker(
    ctx: BundleContext,
    constraint_type: type,
    *,
    phase: str,
    verbose: bool = False,
) -> None:
    """Constraint defined in policy but no checker in manifest/bundle — do not BLOCK.

    Does not stop the pipeline: DG continues → typically UNDECIDED → AE + Guardian.
    Sets ``constraint_checker_skipped`` on ``ctx`` for audit; logs a warning.
    """
    name = constraint_type.__name__
    ctx.constraint_checker_skipped = name
    logger.warning(
        "Constraint type %s has no entry in CONSTRAINT_CHECKERS (%s); "
        "constraint check skipped — not BLOCKed deterministically",
        name,
        phase,
    )
    if verbose:
        print(f"    │  ⚠ constraint checker skipped: {name} ({phase})")
