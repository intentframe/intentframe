"""Packaged Jarvis policy YAMLs.

Contains the default IntentFrame policies for the Jarvis personal-
assistant agent.  Two YAMLs ship out of the box:

* ``jarvis.yaml``      — user-mode policy (``agent_id: jarvis``)
* ``jarvis_root.yaml`` — root-mode policy (``agent_id: jarvis_root``)

Loaded at gateway startup by :mod:`intentframe_gateway.bootstrap`,
which resolves which YAML to seed (user-mode by default; root-mode
when ``JARVIS_VARIANT=root`` is set), honours
``~/.intentframe/policies/<agent_id>.yaml`` overrides, and registers
the result against the ``(user_id, agent_id)`` slot in the policy
registry.

Use :func:`builtin_policy_path` to resolve a YAML path from anywhere
without hard-coding ``Path(__file__)`` arithmetic.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Literal

JarvisVariant = Literal["user", "root"]

_FILENAMES: dict[str, str] = {
    "user": "jarvis.yaml",
    "root": "jarvis_root.yaml",
}

#: Default ``agent_id`` for each variant.  Mirrors the ``agent_id``
#: field declared inside the corresponding YAML.
JARVIS_AGENT_IDS: dict[str, str] = {
    "user": "jarvis",
    "root": "jarvis_root",
}


def builtin_policy_path(variant: JarvisVariant = "user") -> Path:
    """Absolute path to a packaged Jarvis policy YAML.

    Args:
        variant: ``"user"`` (default) or ``"root"``.

    Returns:
        Filesystem path to the YAML inside the installed wheel /
        editable checkout.

    Raises:
        ValueError: ``variant`` is not one of the known keys.
    """
    try:
        filename = _FILENAMES[variant]
    except KeyError as exc:
        raise ValueError(
            f"Unknown Jarvis policy variant {variant!r}; "
            f"expected one of {tuple(_FILENAMES)!r}"
        ) from exc
    return Path(str(resources.files(__package__).joinpath(filename)))


__all__ = [
    "JARVIS_AGENT_IDS",
    "JarvisVariant",
    "builtin_policy_path",
]
