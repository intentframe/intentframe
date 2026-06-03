"""Files bundle action ids.

``WRITE_FILE_ACTIONS`` lists actions that run the shared write-payload
pipeline (``pre_pipeline``, FileIntel). Includes ``WRITE_HOST_FILE`` so
host writes reuse the same tooling; routing/ownership remains in
``HostFilesActionBundle``.
"""

from __future__ import annotations

from intentframe_native_kit.action_registry.types import ActionType

WRITE_FILE_ACTIONS = frozenset({
    ActionType.WRITE_FILE.value,
    ActionType.WRITE_HOST_FILE.value,
})
