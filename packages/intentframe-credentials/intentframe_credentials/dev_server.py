"""Start the credential vault in dev mode with pre-seeded credentials.

Reads secrets from a ``.env`` file co-located with this module, seeds
the in-memory ``env`` backend and metadata store, then starts the
FastAPI vault service.

Usage::

    # UDS transport (mirrors production)
    uv run python -m intentframe_credentials.dev_server

    # TCP transport (easier for curl / browser dev-tools)
    uv run python -m intentframe_credentials.dev_server --tcp

Environment variables loaded from .env::

    EMAIL_<LABEL>_ADDRESS   → email address for the account
    EMAIL_<LABEL>_PASSWORD  → app password / OAuth token

    OPENAI_API_KEY          → seeded as openai / api_key  (runtime_env)
    ANTHROPIC_API_KEY       → seeded as anthropic / api_key  (runtime_env)

Email accounts are discovered automatically from ADDRESS/PASSWORD pairs —
no code changes needed to add a new account, just add lines to .env.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import uvicorn

from intentframe_credentials.backends.env_backend import EnvVault  # noqa: F401 (triggers registration)
from intentframe_credentials.metadata import MetadataStore
from intentframe_credentials.models import CredentialRecord, DeliveryMode, mask_value
from intentframe_credentials.protocol import create_vault

_SCRIPT_DIR = Path(__file__).resolve().parent

SOCKET_PATH = Path("~/.intentframe/run/credential-vault.sock").expanduser()
DEV_TCP_PORT = 9400

# ── .env loader ──────────────────────────────────────────────────────────────


def _load_dotenv(path: Path | None = None) -> dict[str, str]:
    """Parse a .env file into a flat dict.

    Handles:
      - blank lines and ``# comments``
      - values with or without surrounding quotes (single or double)
      - inline comments after a quoted value are NOT stripped (keep it simple)
    """
    env_file = path or (_SCRIPT_DIR / ".env")
    if not env_file.exists():
        print(f"[dev_server] WARNING: {env_file} not found — no credentials seeded")
        return {}

    env: dict[str, str] = {}
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            env[key] = value

    print(f"[dev_server] Loaded {len(env)} variable(s) from {env_file}")
    return env


# ── Credential map builder ───────────────────────────────────────────────────


def _build_credential_map(dotenv: dict[str, str]) -> dict[str, dict]:
    """Return a map of env-var-name → vault spec.

    Static entries (LLM keys, etc.) are hard-coded below.
    Email accounts are discovered dynamically from EMAIL_<LABEL>_ADDRESS /
    EMAIL_<LABEL>_PASSWORD pairs.
    """
    cmap: dict[str, dict] = {}

    # ── Static service keys ──────────────────────────────────────
    STATIC: dict[str, dict] = {
        "OPENAI_API_KEY": {
            "namespace": "openai",
            "key": "api_key",
            "delivery_mode": DeliveryMode.RUNTIME_ENV,
            "env_name": "OPENAI_API_KEY",
            "allowed_consumers": ["uwe", "jarvis"],
        },
        "ANTHROPIC_API_KEY": {
            "namespace": "anthropic",
            "key": "api_key",
            "delivery_mode": DeliveryMode.RUNTIME_ENV,
            "env_name": "ANTHROPIC_API_KEY",
            "allowed_consumers": ["uwe", "jarvis"],
        },
    }
    cmap.update(STATIC)

    # ── Dynamic email accounts ───────────────────────────────────
    # Discover EMAIL_<LABEL>_ADDRESS keys, find matching PASSWORD
    label_re = re.compile(r"^EMAIL_(.+)_ADDRESS$")
    for env_var, address in dotenv.items():
        m = label_re.match(env_var)
        if not m:
            continue
        label = m.group(1)
        password_var = f"EMAIL_{label}_PASSWORD"

        # Namespace uses dots — "email.user@gmail.com" is valid
        ns = f"email.{address}"

        cmap[password_var] = {
            "namespace": ns,
            "key": "password",
            "delivery_mode": DeliveryMode.EXECUTOR_ONLY,
            "allowed_consumers": ["edi"],
            "_label": label,
            "_address": address,
        }

    return cmap


# ── Seed ─────────────────────────────────────────────────────────────────────


async def _seed(
    vault: EnvVault,
    meta: MetadataStore,
    dotenv: dict[str, str],
) -> None:
    await meta.open()

    cmap = _build_credential_map(dotenv)
    seeded, skipped = 0, 0

    for env_var, spec in cmap.items():
        value = dotenv.get(env_var)
        if value is None:
            print(f"  SKIP  {env_var} (not in .env)")
            skipped += 1
            continue

        ns = spec["namespace"]
        key = spec["key"]

        await vault.store(ns, key, value)

        record = CredentialRecord(
            namespace=ns,
            key=key,
            delivery_mode=spec.get("delivery_mode", DeliveryMode.EXECUTOR_ONLY),
            allowed_consumers=spec.get("allowed_consumers", []),
            env_name=spec.get("env_name"),
            masked_preview=mask_value(value),
        )
        await meta.upsert(record)

        label = spec.get("_address") or ns
        print(f"  OK    {env_var}  →  {ns}.{key}  [{record.delivery_mode}]  ({label})")
        seeded += 1

    print(f"\n  {seeded} seeded, {skipped} skipped\n")


# ── Entry point ──────────────────────────────────────────────────────────────


def main() -> None:
    from intentframe_credentials import server

    dotenv = _load_dotenv()

    vault = create_vault("env")
    meta = MetadataStore()

    # Wire the dev instances directly — bypasses the lifespan keyring init
    server._vault = vault  # type: ignore[attr-defined]
    server._meta = meta  # type: ignore[attr-defined]

    print("\nSeeding dev credentials...")
    asyncio.run(_seed(vault, meta, dotenv))

    use_tcp = "--tcp" in sys.argv
    if use_tcp:
        print(f"Vault dev server → http://localhost:{DEV_TCP_PORT}")
        print("  Health:      GET  /health")
        print("  All creds:   GET  /v1/credentials")
        print("  Runtime env: GET  /v1/runtime-env\n")
        uvicorn.run(server.app, host="127.0.0.1", port=DEV_TCP_PORT, log_level="info")
    else:
        SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
        print(f"Vault dev server → {SOCKET_PATH}")
        uvicorn.run(server.app, uds=str(SOCKET_PATH), log_level="info")


if __name__ == "__main__":
    main()
