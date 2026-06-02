"""Gateway profile path resolution helpers."""

from __future__ import annotations

import os
from pathlib import Path


def resolve_core_config_path() -> str:
    """Resolve the intentframe-core profile for first-party gateway launches."""

    override = os.environ.get("INTENTFRAME_CORE_CONFIG")
    if override:
        return override

    import intentframe_native_kit

    return str(Path(intentframe_native_kit.__file__).parent / "core.yaml")


__all__ = ["resolve_core_config_path"]
