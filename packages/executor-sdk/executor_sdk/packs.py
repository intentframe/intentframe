"""
Executor pack plugin contract and discovery constants.

An *executor pack* bundles the platform/deployment-specific implementations
the executor wires up at startup: transports, auth verifiers, credential
backends, storage backends, and capability adapters.

Contract
--------
A pack is any importable module that exposes a module-level callable::

    def register_all() -> None:
        '''Register this pack's implementations into the executor_sdk
        registries (transport / auth / credential / storage / adapters).
        Must be idempotent. Importing the module must NOT register as a
        side effect -- registration only happens when register_all() runs.'''

The executor resolves and loads packs once at startup (see
``executor/server.py``); there is no hot reloading.

Third-party discovery
----------------------
Packs shipped as installed distributions can advertise themselves under the
entry-point group :data:`ENTRY_POINT_GROUP` so deployments can reference them
by a short name in ``executor.yaml`` without importing IntentFrame internals::

    # pyproject.toml of an external org's pack
    [project.entry-points."intentframe.executor_packs"]
    acme = "acme_intentframe_pack:register_all"

The entry-point value points directly at the ``register_all`` callable.
"""

from __future__ import annotations

ENTRY_POINT_GROUP = "intentframe.executor_packs"

__all__ = ["ENTRY_POINT_GROUP"]
