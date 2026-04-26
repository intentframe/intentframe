"""
Routing — deterministic classification of intents for specialised pipelines.

This package is the single source of truth for how intents are partitioned
across AE / Guardian specialisation lanes.  It contains **no AI logic**
and **no I/O** — just frozen sets and small helpers keyed off
:class:`action_registry.types.ActionType`.

Why a separate package?
-----------------------
The criticality set is consumed by :mod:`intentframe_components.prompt.strategy`
(to pick AE / Guardian prompt ids) and may be consumed in the future by
pipeline routing (separate engine instances, telemetry, dashboards).  It
is the conceptual **inverse** of
:attr:`AIAnalysisEngine._PASSIVE_READ_ACTIONS` — but those two sets have
different owners and different consumers, so we keep them decoupled.

Invariant:
    ``CRITICAL_ACTIONS & AIAnalysisEngine._PASSIVE_READ_ACTIONS == frozenset()``

A drift guard test in ``tests/test_prompt_strategy.py`` pins this.
"""

from intentframe_components.routing.criticality import (
    CRITICAL_ACTIONS,
    is_critical,
)

__all__ = ["CRITICAL_ACTIONS", "is_critical"]
