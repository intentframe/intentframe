#!/usr/bin/env python
"""Live demonstration of the HashiCorp backend's token-renewal loop.

hvac does NOT renew tokens automatically — it only exposes one-shot
``renew_self`` / ``login`` calls. The backend runs its own background
loop that renews the token at ~half its TTL and falls back to an AppRole
re-login when the token hits ``token_max_ttl`` (or otherwise can't be
renewed). This script makes that behaviour observable.

It requires an AppRole with a SHORT, renewable TTL so renewals happen in
seconds. scripts/vault_dev_setup.sh configures exactly that
(token_ttl=20s, token_max_ttl=60s)::

    eval "$(./scripts/vault_dev_setup.sh)"
    uv run python scripts/vault_renewal_demo.py            # ~80s
    uv run python scripts/vault_renewal_demo.py --seconds 120

Watch the logs for:
    "renewed vault token"             → renew_self succeeded
    "vault token renewal failed ..."  → hit token_max_ttl
    "recovered vault session via AppRole re-login" → fallback worked

The token_ttl column should sawtooth (fall toward 0, jump back up on each
renew) while every periodic get() keeps returning the stored value —
proving credential access never breaks across a token rollover.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time

from intentframe_credentials.backends.hashicorp_backend import HashiCorpVault

_NS = "demo.renewal"


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # The renewal loop logs at DEBUG; surface just that logger.
    logging.getLogger(
        "intentframe_credentials.backends.hashicorp_backend",
    ).setLevel(logging.DEBUG)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seconds", type=int, default=80,
        help="how long to run the observation loop (default: 80)",
    )
    parser.add_argument(
        "--poll", type=int, default=7,
        help="seconds between token_ttl samples (default: 7)",
    )
    args = parser.parse_args()

    if not os.environ.get("VAULT_ADDR"):
        print("VAULT_ADDR not set — run: eval \"$(./scripts/vault_dev_setup.sh)\"")
        return 2
    if not (os.environ.get("VAULT_ROLE_ID") and os.environ.get("VAULT_SECRET_ID")):
        print(
            "This demo needs AppRole auth (VAULT_ROLE_ID + VAULT_SECRET_ID).\n"
            "A static VAULT_TOKEN cannot be re-logged-in, and a root token "
            "has no TTL so nothing to renew. Run the setup script and make "
            "sure VAULT_TOKEN is unset.",
        )
        return 2
    if os.environ.get("VAULT_TOKEN"):
        print(
            "WARNING: VAULT_TOKEN is set and takes precedence over AppRole. "
            "Unset it so the demo uses the short-lived AppRole token:\n"
            "    unset VAULT_TOKEN",
        )
        return 2

    _configure_logging()

    vault = HashiCorpVault()  # AppRole from env, renewal enabled by default
    print(f"can_relogin = {vault._can_relogin()}  (AppRole configured)\n")

    # First call starts the renewal loop and proves access works.
    await vault.store(_NS, "password", "hunter2")

    start = time.time()
    value: str | None = None
    last_value_ok = True
    while time.time() - start < args.seconds:
        info = await vault.token_info()
        value = await vault.get(_NS, "password")
        last_value_ok = value == "hunter2"
        elapsed = int(time.time() - start)
        print(
            f"  t+{elapsed:>3}s  token_ttl={info.get('ttl')}s "
            f"renewable={info.get('renewable')}  get_ok={last_value_ok}",
        )
        await asyncio.sleep(args.poll)

    await vault.close()

    print(f"\nfinal get -> {value!r}")
    print("PASS" if last_value_ok else "FAIL: credential access broke during rollover")
    return 0 if last_value_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
