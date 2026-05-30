#!/usr/bin/env python
"""Standalone CRUD smoke test for the HashiCorp Vault backend.

Unlike the pytest suite (tests/test_hashicorp_backend.py), this is a
plain script you can run by hand against a live Vault to confirm the
backend works end-to-end. It exercises the full CredentialVault contract
(store / get / has / list_keys / delete) and prints a pass/fail line per
check, exiting non-zero on the first failure.

Prerequisites
-------------
A reachable Vault and auth in the environment (see scripts/vault_dev_setup.sh)::

    eval "$(./scripts/vault_dev_setup.sh)"   # sets VAULT_ADDR + AppRole creds
    # ...or point at any Vault:
    #   export VAULT_ADDR=http://127.0.0.1:8200
    #   export VAULT_TOKEN=dev-root-token

Run
---
    uv run python scripts/vault_smoke_test.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

# Disable the renewal loop — this is a short-lived CRUD check.
os.environ.setdefault("VAULT_RENEW", "false")

from intentframe_credentials.backends.hashicorp_backend import HashiCorpVault

_checks = 0
_failures = 0


def check(label: str, actual: object, expected: object) -> None:
    global _checks, _failures
    _checks += 1
    ok = actual == expected
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}: got {actual!r}, expected {expected!r}")
    if not ok:
        _failures += 1


async def main() -> int:
    if not os.environ.get("VAULT_ADDR"):
        print("VAULT_ADDR not set — run: eval \"$(./scripts/vault_dev_setup.sh)\"")
        return 2

    ns = f"smoke.{uuid.uuid4().hex[:12]}"
    print(f"HashiCorp Vault smoke test (namespace={ns})\n")

    vault = HashiCorpVault()

    print("store + get")
    await vault.store(ns, "password", "hunter2")
    check("get stored value", await vault.get(ns, "password"), "hunter2")

    print("missing key")
    check("get missing returns None", await vault.get(ns, "nope"), None)

    print("has")
    check("has missing", await vault.has(ns, "username"), False)
    await vault.store(ns, "username", "user@example.com")
    check("has present", await vault.has(ns, "username"), True)

    print("list_keys")
    check("two keys present", set(await vault.list_keys(ns)), {"password", "username"})

    print("overwrite preserves siblings")
    await vault.store(ns, "password", "second")
    check("overwritten value", await vault.get(ns, "password"), "second")
    check("sibling preserved", await vault.get(ns, "username"), "user@example.com")

    print("delete one field keeps others")
    await vault.delete(ns, "password")
    check("deleted field gone", await vault.get(ns, "password"), None)
    check("other field kept", await vault.get(ns, "username"), "user@example.com")

    print("delete last field removes secret")
    await vault.delete(ns, "username")
    check("namespace empty", await vault.list_keys(ns), [])

    print("delete missing is a no-op")
    await vault.delete(ns, "ghost")  # must not raise
    check("no-op delete survived", True, True)

    await vault.close()

    print(f"\n{_checks - _failures}/{_checks} checks passed")
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
