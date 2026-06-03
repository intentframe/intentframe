"""Host filesystem file family — real-path actions only.

Owns ``READ_HOST_FILE``, ``LIST_HOST_DIRECTORY``, ``WRITE_HOST_FILE``,
and ``DELETE_HOST_FILE``. Host-specific logic lives here:

- ``checker`` — ``HostFileConstraints`` on canonicalized real paths
- ``deterministic`` — deny-floor BLOCK gates for host mutations

Write-payload tooling (FileIntel pre-pipeline, AE context, prompt bodies)
is imported from ``intentframe_native_kit.intentframe_native_bundles.actions.files`` — that package is the
canonical owner; this family reuses it rather than duplicating it.

Do not move virtual-path helpers into this package, and do not call
``normalize_virtual_path`` from host-file checkers.
"""
