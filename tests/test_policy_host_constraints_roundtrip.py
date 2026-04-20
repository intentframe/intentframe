"""Regression pin for the per-action constraint Union dispatch invariant.

``policy_registry.models.ConstraintTypes`` is an undiscriminated
pydantic ``Union``.  ``FileConstraints`` (virtual paths) and
``HostFileConstraints`` (real host paths) have the same logical shape —
a single ``list[str]`` of allowed patterns — so naively they would both
validate against the same input and pydantic's smart-union matcher
would silently pick the first Union member.  That would route host-path
policies through ``FileChecker`` (which applies
``normalize_virtual_path``) and break host-file enforcement.

The fix is schema-level disambiguation:

- ``FileConstraints.allowed_paths`` vs
  ``HostFileConstraints.allowed_host_paths`` — disjoint required field
  names;
- ``model_config = ConfigDict(frozen=True, extra="forbid")`` on both —
  mixed payloads fail loudly instead of silently matching the wrong
  Union member.

This test locks the invariant so any future rename back to identical
keys (or a removal of ``extra="forbid"``) fails loudly in CI instead of
silently re-introducing the dispatch bug.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from policy_registry.constraints import FileConstraints, HostFileConstraints
from policy_registry.models import ActionPermission, UserPolicy


class TestFieldNameDisambiguation:
    """Per-payload: each payload validates against exactly one concrete type."""

    def test_file_payload_selects_file_constraints(self):
        perm = ActionPermission.model_validate(
            {"safe": False, "constraints": {"allowed_paths": ["/home/*"]}}
        )
        assert isinstance(perm.constraints, FileConstraints)
        assert not isinstance(perm.constraints, HostFileConstraints)

    def test_host_file_payload_selects_host_file_constraints(self):
        perm = ActionPermission.model_validate(
            {
                "safe": False,
                "constraints": {"allowed_host_paths": ["~/Documents/*"]},
            }
        )
        assert isinstance(perm.constraints, HostFileConstraints)
        assert not isinstance(perm.constraints, FileConstraints)

    def test_mixed_fields_do_not_select_file_or_host_file(self):
        """Payload carrying BOTH fields must NOT silently bind to either.

        A mixed payload is user error — the invariant we pin is that it
        never silently binds to ``FileConstraints`` or
        ``HostFileConstraints``.  (Other Union members without
        ``extra='forbid'`` may happen to catch the payload; that's a
        pre-existing registry-wide quirk outside this plan's scope.
        What matters for host-file enforcement is that the two
        path-shaped types cannot be confused for each other.)
        """
        perm = ActionPermission.model_validate(
            {
                "safe": False,
                "constraints": {
                    "allowed_paths": ["/home/*"],
                    "allowed_host_paths": ["~/Documents/*"],
                },
            }
        )
        assert not isinstance(perm.constraints, FileConstraints)
        assert not isinstance(perm.constraints, HostFileConstraints)


class TestJsonRoundtrip:
    """Serialize → deserialize through the full ``UserPolicy`` envelope."""

    def test_host_file_constraints_survive_user_policy_roundtrip(self):
        original = UserPolicy(
            user_id="u1",
            allowed_actions={
                "READ_HOST_FILE": ActionPermission(
                    safe=True,
                    constraints=HostFileConstraints(
                        allowed_host_paths=["~/Documents/*"]
                    ),
                ),
                "READ_FILE": ActionPermission(
                    safe=True,
                    constraints=FileConstraints(allowed_paths=["/home/*"]),
                ),
            },
        )
        raw = original.model_dump_json()
        rebuilt = UserPolicy.model_validate_json(raw)

        host_perm = rebuilt.allowed_actions["READ_HOST_FILE"]
        file_perm = rebuilt.allowed_actions["READ_FILE"]

        assert isinstance(host_perm.constraints, HostFileConstraints)
        assert host_perm.constraints.allowed_host_paths == ["~/Documents/*"]
        assert not isinstance(host_perm.constraints, FileConstraints)

        assert isinstance(file_perm.constraints, FileConstraints)
        assert file_perm.constraints.allowed_paths == ["/home/*"]
        assert not isinstance(file_perm.constraints, HostFileConstraints)


class TestExtraForbid:
    """Both models carry ``extra='forbid'`` — pin both explicitly.

    ``extra='forbid'`` is the second half of the disambiguation
    invariant.  Dropping it on either side would re-open the ambiguity
    (a payload carrying both fields would match the first Union member
    and silently ignore the extra field instead of erroring out).
    """

    def test_file_constraints_forbids_extras(self):
        with pytest.raises(ValidationError):
            FileConstraints.model_validate(
                {"allowed_paths": ["/home/*"], "allowed_host_paths": ["~/*"]}
            )

    def test_host_file_constraints_forbids_extras(self):
        with pytest.raises(ValidationError):
            HostFileConstraints.model_validate(
                {"allowed_host_paths": ["~/*"], "allowed_paths": ["/home/*"]}
            )


class TestPolicyLoaderCompatibility:
    """demo/tests/policy_loader.py matches constraints by field-set.

    It iterates ``policy_registry.constraints.__all__`` and picks the
    first class whose ``model_fields`` is a superset of the raw YAML
    keys.  The disjoint field names make this deterministic.
    """

    def test_loader_resolves_host_file_constraints(self):
        from demo.tests.policy_loader import _parse_constraints

        resolved = _parse_constraints({"allowed_host_paths": ["~/Documents/*"]})
        assert isinstance(resolved, HostFileConstraints)

    def test_loader_resolves_file_constraints(self):
        from demo.tests.policy_loader import _parse_constraints

        resolved = _parse_constraints({"allowed_paths": ["/home/*"]})
        assert isinstance(resolved, FileConstraints)
