"""Runtime-side context enrichers.

Each enricher is a deterministic pre-analysis step that resolves
metadata from trusted system sources (local DB, filesystem, etc.)
and merges it into the IntentFrame before it enters the AI pipeline.

This mirrors how ``command_shield`` runs pre-pipeline: a fast,
deterministic gate that gives AE/Guardian richer context without
any AI calls.
"""
