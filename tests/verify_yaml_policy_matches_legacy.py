"""One-shot parity verification: new YAML vs the pre-refactor hardcoded policy.

Loads bootstrap.py from commit 7ad2bd3 (last commit before the YAML-seed
refactor) and runs its `_build_policy(profile)`
function, then runs the new `_build_jarvis_policy(variant)` against the
relocated `jarvis_pa/jarvis/policies/<jarvis|jarvis_root>.yaml`.

The structural fields we *intentionally* added/removed are stripped from
both sides before comparison:

    Added by refactor (new only)
        + agent_id
        + intentframe_schema_version

    Removed by refactor (legacy only)
        - metadata.profile     (was a free-form audit tag, now agent_id)

    Different by design
        ~ metadata.note        (overlay text differs)
        ~ user_id              (legacy suffixed `_root`; new does not.
                                we compare with the same explicit user_id)

What MUST match exactly:

    * allowed_actions  (every action key, every safe flag, every constraint dict)
    * intent_limits    (full list, in order)
    * remaining metadata fields after dropping `note` and `profile`
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path("/Users/prince/GitHub/orgs/intentframe/intentframe")


def load_head_bootstrap():
    """Import HEAD's bootstrap.py as a fresh module and return it."""
    # Pinned to the last commit before the YAML-seed refactor.
    # Do NOT replace with HEAD — HEAD will move as new commits land.
    LEGACY_COMMIT = "7ad2bd3"
    head_src = subprocess.check_output(
        ["git", "-C", str(REPO), "show", f"{LEGACY_COMMIT}:intentframe_gateway/bootstrap.py"],
        text=True,
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, dir="/tmp"
    ) as fh:
        fh.write(head_src)
        path = Path(fh.name)

    spec = importlib.util.spec_from_file_location("legacy_bootstrap", path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO))
    spec.loader.exec_module(mod)
    return mod


def canonicalise(policy: dict) -> dict:
    """Round-trip through Pydantic so both sides land in the same canonical form.

    Defends against three known representation diffs:

    * `deny_capabilities` insertion order vs `sorted(...)` order — Pydantic
      coerces to `frozenset` then dumps to a sorted list.
    * Missing optional keys vs explicit-default ones (e.g. legacy raw dict
      omits `allowed_commands`; YAML round-trip emits `allowed_commands: []`).
    * Refactor-added fields (`agent_id`, `intentframe_schema_version`)
      and refactor-removed fields (`metadata.profile`).  We strip these
      AFTER canonicalisation so the rest is byte-comparable.
    """
    from policy_registry.models import UserPolicy

    # Both legacy and new dicts are missing some refactor fields.  Inject
    # safe placeholders before validation so Pydantic accepts them; we
    # strip them again below.
    raw = json.loads(json.dumps(policy, default=str))
    raw.setdefault("agent_id", "_compare_")
    raw.setdefault("intentframe_schema_version", 1)
    canonical = UserPolicy.model_validate(raw).model_dump(
        mode="json", exclude={"created_at"}
    )
    canonical.pop("agent_id", None)
    canonical.pop("intentframe_schema_version", None)
    canonical.pop("user_id", None)
    md = canonical.get("metadata") or {}
    md.pop("note", None)
    md.pop("profile", None)
    canonical["metadata"] = md
    return canonical


def sort_string_lists(obj):
    """Recursively sort every list-of-strings so set-shaped fields compare equal.

    `deny_capabilities`, `blocked_patterns`, `allowed_host_paths`, etc. are
    semantically sets — we don't care about ordering, only membership.
    Lists containing dicts (e.g. `intent_limits`, `recipient_sources`) are
    NOT sorted — their order is meaningful.
    """
    if isinstance(obj, dict):
        return {k: sort_string_lists(v) for k, v in obj.items()}
    if isinstance(obj, list):
        if obj and all(isinstance(x, str) for x in obj):
            return sorted(obj)
        return [sort_string_lists(x) for x in obj]
    return obj


def diff_keys(a: dict, b: dict, path: str = "") -> list[str]:
    """Tiny structural diff that returns every concrete mismatch path."""
    diffs: list[str] = []
    if type(a) is not type(b):
        return [f"{path}: type {type(a).__name__} vs {type(b).__name__}"]
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                diffs.append(f"{path}.{k}: missing on legacy side")
            elif k not in b:
                diffs.append(f"{path}.{k}: missing on new side")
            else:
                diffs.extend(diff_keys(a[k], b[k], f"{path}.{k}"))
    elif isinstance(a, list):
        if len(a) != len(b):
            diffs.append(f"{path}: list len {len(a)} vs {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            diffs.extend(diff_keys(x, y, f"{path}[{i}]"))
    else:
        if a != b:
            diffs.append(f"{path}: {a!r} vs {b!r}")
    return diffs


def main() -> int:
    sys.path.insert(0, str(REPO))
    legacy = load_head_bootstrap()

    # New side — re-import from the working tree.
    from intentframe_gateway import bootstrap as new

    # Match map: legacy_profile → new_variant.
    pairs = [("user", "user"), ("root", "root")]

    overall_ok = True
    for legacy_profile, new_variant in pairs:
        print(f"\n=== Comparing legacy profile={legacy_profile!r} "
              f"vs new variant={new_variant!r} ===")
        legacy_policy = legacy._build_policy(legacy_profile)
        new_policy = new._build_jarvis_policy(new_variant)

        # Sanity prints so the diff is interpretable.
        print(f"  legacy user_id  = {legacy_policy['user_id']!r}")
        print(f"  new    user_id  = {new_policy['user_id']!r}")
        print(f"  new    agent_id = {new_policy['agent_id']!r}")
        print(f"  new    schema_v = {new_policy['intentframe_schema_version']}")

        legacy_norm = sort_string_lists(canonicalise(legacy_policy))
        new_norm = sort_string_lists(canonicalise(new_policy))

        diffs = diff_keys(legacy_norm, new_norm)
        if diffs:
            overall_ok = False
            print(f"\n  ✘  {len(diffs)} mismatch(es):")
            for d in diffs[:50]:
                print(f"      {d}")
            if len(diffs) > 50:
                print(f"      ... and {len(diffs) - 50} more")
        else:
            print("  ✔  Exact parity on allowed_actions + intent_limits + metadata.")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
