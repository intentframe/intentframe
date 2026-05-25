"""Anchor this repo's ``tests`` package on ``sys.path``.

Without this file, ``import tests.*`` resolves to
``external_data_ingestion/tests`` (uv workspace sibling) instead of
``intentframe/tests``.  Required for ``from tests.deterministic_accuracy…``
imports in top-level test modules.
"""
