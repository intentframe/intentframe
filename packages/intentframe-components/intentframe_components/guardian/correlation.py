"""
Guardian Correlation Service

Stateful data service that tracks temporal patterns across intents.
Guardian queries this for historical context when making decisions.

Provides:
- Velocity tracking (intents per time window)
- Accumulation tracking (e.g. total spend per day)
- Sequence tracking (ordered action history per agent)
- Drift detection (behavioral baseline comparison)
- Anomaly scoring

Does NOT make decisions — Guardian owns that.
"""

# TODO: Implement correlation service
