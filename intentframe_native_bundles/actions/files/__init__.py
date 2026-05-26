"""Virtual filesystem (VFS) file family.

Owns VFS actions: ``READ_FILE``, ``LIST_DIRECTORY``, ``WRITE_FILE``,
``APPEND_ROW``, ``DELETE_FILE``.

Bundle-local modules (virtual-path logic only):
- ``constraints``          — ``FileConstraints`` on virtual paths
- ``deterministic``        — VFS sensitive-path BLOCK floors
- ``onboarding_guardrails``

Shared write-payload modules live in
``intentframe_native_bundles.shared.files`` and are consumed by both
this bundle and ``actions/host_files/``.
"""
