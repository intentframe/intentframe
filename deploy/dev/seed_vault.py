#!/usr/bin/env python
"""Seed runtime_env secrets into the credential vault (dev/container bootstrap).

Reads secrets from the container environment and stores them in the vault with
``delivery_mode=runtime_env`` so the supervisor bootstrap (inject_and_exec.py)
can later fetch and inject them into the supervised services.

Why re-seed on every container start?
  The secret *value* lives in the vault backend (HashiCorp), but the
  ``runtime_env`` *metadata* (delivery_mode, env_name) lives in a local SQLite
  store (``~/.intentframe/data/credentials.db``). A fresh container has an empty
  SQLite store even if the value still exists in HashiCorp, so ``list_runtime_env``
  would return nothing. ``store`` writes both halves and is idempotent, so
  seeding each start keeps the two stores consistent.

Currently seeds:
  OPENAI_API_KEY  ->  vault: openai/api_key  (env_name=OPENAI_API_KEY)

Add more entries to ``SECRETS`` as needed. Missing env vars are skipped.
"""

from __future__ import annotations

import os
import sys

from intentframe_credentials.client import VaultClientSync
from intentframe_credentials.models import DeliveryMode

# (env var read from container) -> (vault namespace, vault key, injected env_name)
SECRETS: list[tuple[str, str, str, str]] = [
    ("OPENAI_API_KEY", "openai", "api_key", "OPENAI_API_KEY"),
]


def main() -> int:
    sock = os.environ.get("INTENTFRAME_VAULT_SOCKET") or None
    vault = VaultClientSync(sock)

    seeded = 0
    for env_var, namespace, key, env_name in SECRETS:
        value = os.environ.get(env_var, "").strip()
        if not value:
            print(f"[seed] {env_var} not set; skipping", file=sys.stderr)
            continue
        vault.store(
            namespace,
            key,
            value,
            delivery_mode=DeliveryMode.RUNTIME_ENV,
            env_name=env_name,
        )
        print(f"[seed] stored {namespace}/{key} (runtime_env -> {env_name})")
        seeded += 1

    if seeded == 0:
        print(
            "[seed] no secrets seeded — the supervisor will start without any "
            "runtime_env credentials (set OPENAI_API_KEY to seed it)",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
