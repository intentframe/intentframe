#!/usr/bin/env python
"""Fetch runtime_env secrets from the vault, then exec the supervisor.

This is the container's supervisor bootstrap. The vault is the source of truth
for secrets, so we resolve every ``runtime_env`` credential into a
{env_name: value} dict and merge it into the environment before handing off to
the supervisor.

The supervisor inherits this process's environment and forwards it to every
supervised service, so the OpenAI key reaches intentframe-core. The supervisor
also reads INTENTFRAME_SUPERVISOR_CONFIG from this inherited env to pick its
service-graph profile (minimal default unless the kit profile is exported).

We deliberately drop any inherited ``OPENAI_API_KEY`` first, so the value the
supervisor sees provably comes from the vault fetch — not the container env.

Run order (see entrypoint.dev.sh): vault up -> seed_vault.py -> THIS -> supervisor.

Dependencies: only ``intentframe_credentials`` (the vault client). The
``runtime_env`` resolution below is inlined rather than reusing the gateway's
``CredentialGate`` so this bootstrap stays decoupled from the consumer gateway
and works whether IntentFrame is installed as a repo checkout or as pip packages.
"""

from __future__ import annotations

import asyncio
import os
import sys

from intentframe_credentials.client import VaultClient

SUPERVISOR_CMD = [sys.executable, "-m", "supervisor.main", "start"]

# Secrets that should arrive only via the vault, never inherited from the
# container env. Dropped before the fetch so the vault is the sole source.
_VAULT_ONLY_ENV = ("OPENAI_API_KEY",)


async def _build_runtime_env() -> dict[str, str]:
    """Resolve every ``runtime_env`` credential into {env_name: value}.

    Reads the metadata list (``GET /v1/runtime-env``) then fetches each value
    individually — the same contract the supervisor/gateway expect, but with no
    dependency outside ``intentframe_credentials``.
    """
    sock = os.environ.get("INTENTFRAME_VAULT_SOCKET") or None
    env: dict[str, str] = {}
    async with VaultClient(sock) as vault:
        for record in await vault.list_runtime_env():
            env_name = record.get("env_name")
            if not env_name:
                continue
            value = await vault.get(record["namespace"], record["key"])
            if value:
                env[env_name] = value
    return env


def main() -> int:
    for name in _VAULT_ONLY_ENV:
        os.environ.pop(name, None)

    runtime_env = asyncio.run(_build_runtime_env())
    os.environ.update(runtime_env)

    # Log names only — never values.
    names = sorted(runtime_env)
    print(f"[bootstrap] injected {len(names)} runtime_env var(s) from vault: {names}")
    if not runtime_env:
        print(
            "[bootstrap] WARNING: no runtime_env credentials in vault; "
            "intentframe-core may fail its mandatory credential check",
            file=sys.stderr,
        )

    # Replace this process with the supervisor, inheriting the injected env.
    os.execvpe(SUPERVISOR_CMD[0], SUPERVISOR_CMD, os.environ)


if __name__ == "__main__":
    raise SystemExit(main())
