"""Virtual filesystem (VFS) file family — canonical owner of file-write tooling.

This package owns VFS actions (``READ_FILE``, ``LIST_DIRECTORY``,
``WRITE_FILE``, ``APPEND_ROW``, ``DELETE_FILE``) and the shared write-
payload pipeline used when mutating file content:

- ``file_intel`` / ``pre_pipeline`` — deterministic FileIntel collection
- ``ai_context`` / ``prompts_ae`` — AE prompt material for write intents
- ``checker`` — ``FileConstraints`` enforcement on virtual paths
- ``deterministic`` — VFS sensitive-path BLOCK floors

``host_files/`` may import these modules for ``WRITE_HOST_FILE`` because
both families share write-payload semantics. Path enforcement and floor
gates stay in each family's own checker and ``deterministic`` modules —
virtual vs real path vocabularies must not be mixed.

Third-party plugins should either depend on this package for file-write
primitives or publish their own family-local helpers; the Bundle SDK does
not yet provide a shared kit abstraction (see ``ActionBundle`` docstring).
"""
