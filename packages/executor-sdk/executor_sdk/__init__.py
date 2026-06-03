"""IntentFrame Executor SDK — pack and adapter registration contract.

Plugin executor packs import from this package only (not ``intentframe_core``).
"""

from intentframe_core.identity import owner_home

__all__ = [
    "owner_home",
]
