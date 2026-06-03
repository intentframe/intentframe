#!/usr/bin/env python3
"""Reference admin script — load a policy YAML and upsert it into policy-registry.

Orchestration only (not part of ``policy_registry``):

  1. ``load_policy_seed`` — YAML structure + schema version
  2. ``validate_policy_with_bundles`` — constraint semantics (optional but recommended)
  3. ``PolicyRegistryClient.set_user_policy`` — HTTP over UDS or edge URL

Transport is chosen automatically:

  * Local supervisor: UDS at ``~/.intentframe/run/policy-registry.sock``
  * Deploy/dev edge:  ``export INTENTFRAME_POLICY_URL=http://localhost:8443``

Prerequisites
-------------
Supervisor must be running with ``policy-registry`` up.

Examples
--------
From repo root (after ``uv sync``):

  # Demo attack policy (same shape as ``demo/tests/policy_loader.py``)
  uv run python scripts/admin/seed_policy.py \\
    --policy demo/config/test_policy.yaml \\
    --user-id attack_tester \\
    --agent-id stub_pipeline_agent \\
    --bundle intentframe_native_kit.intentframe_native_bundles

  # Jarvis user variant (packaged builtin; override via ~/.intentframe/policies/jarvis.yaml)
  uv run python scripts/admin/seed_policy.py \\
    --policy jarvis_pa/jarvis/policies/jarvis.yaml \\
    --user-id jarvis_default \\
    --agent-id jarvis \\
    --bundle intentframe_native_kit.intentframe_native_bundles

  # Skip POST when the (user_id, agent_id) slot already exists
  uv run python scripts/admin/seed_policy.py ... --skip-if-exists

  # Structure-only (no bundle validation — not recommended for production seeds)
  uv run python scripts/admin/seed_policy.py ... --no-validate-bundles

Copy and edit this file for custom installers; keep bundle validation in the orchestrator.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Allow ``uv run python scripts/admin/seed_policy.py`` from repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from intentframe_bundle_sdk.loader import validate_policy_with_bundles
from policy_registry.client import PolicyRegistryClient
from policy_registry.models import UserPolicy
from policy_registry.seeds import load_policy_seed

DEFAULT_BUNDLE = "intentframe_native_kit.intentframe_native_bundles"


def seed_policy(
    *,
    yaml_path: str | Path,
    user_id: str,
    agent_id: str,
    bundle_packages: list[str] | None,
    metadata: dict[str, Any] | None = None,
    skip_if_exists: bool = False,
    policy_url: str | None = None,
    socket_path: str | None = None,
) -> UserPolicy:
    """Load YAML, optionally validate against bundles, upsert via registry client."""
    policy = load_policy_seed(
        yaml_path,
        user_id=user_id,
        agent_id=agent_id,
        metadata=metadata,
    )

    if bundle_packages:
        validate_policy_with_bundles(policy, bundle_packages)

    client_kwargs: dict[str, Any] = {}
    if policy_url is not None:
        client_kwargs["base_url"] = policy_url
    if socket_path is not None:
        client_kwargs["socket_path"] = socket_path

    with PolicyRegistryClient(**client_kwargs) as client:
        if skip_if_exists:
            try:
                client.get_user_policy(user_id, agent_id)
                print(
                    f"Policy already exists for user={user_id!r} agent={agent_id!r} — skipping"
                )
                return policy
            except KeyError:
                pass

        client.set_user_policy(policy)
        print(f"Policy seeded for user={user_id!r} agent={agent_id!r}")
        _print_summary(policy)

    return policy


def _print_summary(policy: UserPolicy) -> None:
    safe_n = sum(1 for p in policy.allowed_actions.values() if p.safe)
    unsafe_n = len(policy.allowed_actions) - safe_n
    print(f"  Allowed actions: {len(policy.allowed_actions)} ({safe_n} safe, {unsafe_n} other)")
    print(f"  Intent limits:   {len(policy.intent_limits)}")
    for lim in policy.intent_limits:
        print(f"    - [{lim.domain}] {lim.description} → {lim.effect}")


def _parse_metadata(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise argparse.ArgumentTypeError("--metadata must be a JSON object")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Load a policy YAML and upsert it into policy-registry (UDS or HTTP).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--policy",
        type=Path,
        required=True,
        help="Path to policy YAML (e.g. demo/config/test_policy.yaml)",
    )
    parser.add_argument("--user-id", required=True, help="Registry user_id / operator id")
    parser.add_argument("--agent-id", required=True, help="Registry agent_id slot")
    parser.add_argument(
        "--bundle",
        action="append",
        dest="bundles",
        help=(
            "Bundle package ref for validate_policy_with_bundles. "
            f"Repeatable; default: {DEFAULT_BUNDLE!r}"
        ),
    )
    parser.add_argument(
        "--no-validate-bundles",
        action="store_true",
        help="Skip bundle constraint validation (structure-only seed)",
    )
    parser.add_argument(
        "--skip-if-exists",
        action="store_true",
        help="Do not POST if GET /policies/{user}/{agent} already returns 200",
    )
    parser.add_argument(
        "--metadata",
        type=_parse_metadata,
        help='JSON object merged into policy metadata, e.g. \'{"note":"my seed"}\'',
    )
    parser.add_argument(
        "--policy-url",
        help="Override INTENTFRAME_POLICY_URL (edge / remote registry)",
    )
    parser.add_argument(
        "--socket",
        dest="socket_path",
        help="Override policy-registry UDS path (default: ~/.intentframe/run/policy-registry.sock)",
    )
    args = parser.parse_args(argv)

    yaml_path = args.policy.expanduser()
    if not yaml_path.is_file():
        print(f"Error: policy file not found: {yaml_path}", file=sys.stderr)
        return 1

    bundles: list[str] | None = None
    if not args.no_validate_bundles:
        bundles = args.bundles if args.bundles else [DEFAULT_BUNDLE]

    try:
        seed_policy(
            yaml_path=yaml_path,
            user_id=args.user_id,
            agent_id=args.agent_id,
            bundle_packages=bundles,
            metadata=args.metadata,
            skip_if_exists=args.skip_if_exists,
            policy_url=args.policy_url,
            socket_path=args.socket_path,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
