"""System config loader — reads ``~/.intentframe/gateway.yaml`` for non-sensitive
env vars to inject into child processes.

This is the middle layer between hardcoded defaults and the credential vault:

    hardcoded defaults  (source code)
      ↑ overridden by
    ~/.intentframe/gateway.yaml  (this module — non-sensitive)
      ↑ overridden by
    credential vault runtime_env  (secrets — always win)

``build_config_env()`` returns a flat ``{ENV_NAME: value}`` dict, ready to be
merged with the vault's ``build_runtime_env()`` output before passing to child
processes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_SYSTEM_CONFIG_YAML = Path("~/.intentframe/gateway.yaml").expanduser()

WELL_KNOWN_CONFIG: dict[str, str] = {
    "identity.user_id": "JARVIS_USER_ID",
    "telegram.allowed_user_id": "JARVIS_TELEGRAM_ALLOWED_USER_ID",
}


def build_config_env(path: Path | None = None) -> dict[str, str]:
    """Read system config YAML and return ``{env_name: value}`` for child processes.

    Merges two sources within the file:
    1. Well-known structured keys (``identity.user_id`` → ``JARVIS_USER_ID``)
    2. Explicit ``env:`` section (passthrough, literal env var names)

    Explicit ``env:`` entries take precedence over well-known mappings.
    """
    yaml_path = path or _SYSTEM_CONFIG_YAML
    if not yaml_path.exists():
        logger.debug("System config not found at %s — using defaults", yaml_path)
        return {}

    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.warning("Could not parse system config %s", yaml_path, exc_info=True)
        return {}

    env: dict[str, str] = {}

    for dotted_key, env_name in WELL_KNOWN_CONFIG.items():
        section, field = dotted_key.split(".", 1)
        value = (raw.get(section) or {}).get(field)
        if value is not None:
            env[env_name] = str(value)

    for k, v in (raw.get("env") or {}).items():
        env[k] = str(v)

    if env:
        logger.info("System config: loaded %d env variable(s) from %s", len(env), yaml_path)
    return env


def read_config_yaml(path: Path | None = None) -> dict[str, Any]:
    """Return the raw parsed YAML (or empty dict if missing/invalid)."""
    yaml_path = path or _SYSTEM_CONFIG_YAML
    if not yaml_path.exists():
        return {}
    try:
        return yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.warning("Could not parse system config %s", yaml_path, exc_info=True)
        return {}


def write_config_yaml(data: dict[str, Any], path: Path | None = None) -> None:
    """Write *data* to the system config YAML (creates parent dirs)."""
    yaml_path = path or _SYSTEM_CONFIG_YAML
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def set_config_value(dotted_key: str, value: str, path: Path | None = None) -> dict[str, Any]:
    """Set a single value by dotted key (e.g. ``identity.user_id``) and persist.

    Also handles the flat ``env.SOME_VAR`` form for the ``env:`` section.
    Returns the updated config dict.
    """
    data = read_config_yaml(path)
    parts = dotted_key.split(".", 1)
    if len(parts) == 2:
        section, field = parts
        data.setdefault(section, {})[field] = value
    else:
        data[dotted_key] = value
    write_config_yaml(data, path)
    return data


def delete_config_value(dotted_key: str, path: Path | None = None) -> bool:
    """Delete a value by dotted key. Returns True if something was removed."""
    data = read_config_yaml(path)
    parts = dotted_key.split(".", 1)
    if len(parts) == 2:
        section, field = parts
        sec = data.get(section)
        if isinstance(sec, dict) and field in sec:
            del sec[field]
            if not sec:
                del data[section]
            write_config_yaml(data, path)
            return True
    elif dotted_key in data:
        del data[dotted_key]
        write_config_yaml(data, path)
        return True
    return False
