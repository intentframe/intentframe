"""Mirror-invariant test: ``jarvis_pa/executor.yaml`` ↔ ``intentframe_gateway/bootstrap.py``.

The executor YAML's ``host_files.allowed_write_paths`` is the adapter's
hard ceiling.  ``intentframe_gateway/bootstrap.py`` is the runtime
policy seeder (invoked by ``Bootstrapper.reconcile`` on every gateway
startup) and authors the user's per-action
``HostFileConstraints.allowed_host_paths`` that the guardian checks
earlier in the pipeline.  If the two drift apart:

- **Policy wider than executor**  → guardian ALLOWs a path the adapter
  then refuses.  Users see inconsistent "approved then failed" flows.
- **Policy narrower than executor** → guardian BLOCKs a path the
  executor would have permitted.  Agents get surprise denials on
  paths the operator intentionally opened.

This test canonicalizes both allowlists through the shared
:func:`resource_registry.floor.canonicalize_real_path` and asserts
strict set equality (reads and writes both).  The invariant is relaxed
only if the policy later grows finer-grained sub-allowlists (out of
scope for this plan).

Note: ``jarvis_pa/seed_policies.py`` is a hand-runnable mirror of this
same policy across both profiles (``user`` and ``root``), kept in
lockstep with bootstrap intentionally.  This test pins the *runtime*
path — the gateway bootstrap against ``jarvis_pa/executor.yaml`` (user
profile) — so drift there cannot slip past CI.  Bootstrap-vs-seeder
parity (including the root profile) is covered by the ``Mirror check``
snippet in ``docs/action-family-wiring.md``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from intentframe_gateway import bootstrap
from resource_registry.floor import canonicalize_real_path


REPO_ROOT = Path(__file__).resolve().parent.parent
JARVIS_EXECUTOR_YAML = REPO_ROOT / "jarvis_pa" / "executor.yaml"


def _normalize_root(raw: str) -> str:
    """Reduce a pattern to its effective directory root for comparison.

    The executor YAML uses directory-prefix form (``~/``) and the policy
    uses glob form (``~/*``).  Both admit the same tree, but their
    canonical strings differ (``~/`` → ``/Users/me``; ``~/*`` →
    ``/Users/me/*``).  For the mirror invariant we only care that both
    sides point at the same *root directory*, so strip any trailing
    ``/*`` glob marker and trailing separator, then canonicalize.
    """
    stripped = raw
    if stripped.endswith("/*"):
        stripped = stripped[:-2]
    stripped = stripped.rstrip(os.sep) or stripped
    return canonicalize_real_path(stripped)


@pytest.fixture(scope="module")
def executor_scopes() -> tuple[set[str], set[str]]:
    with JARVIS_EXECUTOR_YAML.open() as fh:
        cfg = yaml.safe_load(fh)
    host_files = cfg.get("host_files") or {}
    reads = {_normalize_root(p) for p in host_files.get("allowed_read_paths", [])}
    writes = {_normalize_root(p) for p in host_files.get("allowed_write_paths", [])}
    return reads, writes


@pytest.fixture(scope="module")
def policy_host_paths() -> set[str]:
    policy = bootstrap._build_default_policy()
    allowed = policy["allowed_actions"]
    patterns: set[str] = set()
    for action in (
        "READ_HOST_FILE",
        "WRITE_HOST_FILE",
        "DELETE_HOST_FILE",
        "LIST_HOST_DIRECTORY",
    ):
        entry = allowed.get(action)
        assert entry is not None, f"seed policy missing {action}"
        constraints = entry.get("constraints") or {}
        # Disjoint-field invariant: the policy key must be ``allowed_host_paths``,
        # NOT ``allowed_paths`` — otherwise pydantic smart-union dispatches
        # the payload to ``FileConstraints`` and routes through the
        # virtual-path ``FileChecker``.  See tests/test_policy_host_constraints_roundtrip.py.
        assert "allowed_paths" not in constraints, (
            f"{action} uses the FileConstraints key (allowed_paths); "
            "must use HostFileConstraints.allowed_host_paths instead"
        )
        patterns.update(
            _normalize_root(p)
            for p in constraints.get("allowed_host_paths", [])
        )
    return patterns


class TestScopeMirror:
    def test_policy_subset_of_executor_writes(self, executor_scopes, policy_host_paths):
        _reads, writes = executor_scopes
        # Policy is applied to *all* four actions (reads + writes),
        # but writes are the hard ceiling: policy MUST NOT open a write
        # path the executor doesn't also grant.
        assert policy_host_paths <= writes, (
            "jarvis policy allowed_host_paths escapes executor.yaml "
            f"allowed_write_paths.\n  policy: {sorted(policy_host_paths)!r}"
            f"\n  executor writes: {sorted(writes)!r}"
        )

    def test_policy_subset_of_executor_reads(self, executor_scopes, policy_host_paths):
        reads, _writes = executor_scopes
        assert policy_host_paths <= reads, (
            "jarvis policy allowed_host_paths escapes executor.yaml "
            f"allowed_read_paths.\n  policy: {sorted(policy_host_paths)!r}"
            f"\n  executor reads: {sorted(reads)!r}"
        )

    def test_policy_and_executor_are_non_empty(self, executor_scopes, policy_host_paths):
        # The seed intent for Jarvis is home-level host-file access.
        # If either side becomes empty without the other updating, the
        # mirror invariant becomes trivially true but the configured
        # capability is silently gone — catch that here.
        reads, writes = executor_scopes
        assert reads, "jarvis_pa/executor.yaml host_files.allowed_read_paths is empty"
        assert writes, "jarvis_pa/executor.yaml host_files.allowed_write_paths is empty"
        assert policy_host_paths, "bootstrap._build_default_policy host_constraint is empty"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
