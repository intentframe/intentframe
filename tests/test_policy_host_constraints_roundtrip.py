"""Regression pin for opaque dict constraint storage and bundle validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests._bundle_loader import ensure_test_bundles_loaded
from intentframe_native_bundles.actions.files.constraints import FileConstraints
from intentframe_native_bundles.actions.host_files.constraints import HostFileConstraints
from intentframe_bundle_sdk.registry import action_bundle_for
from intentframe_bundle_sdk.types import ActionPermission as SdkActionPermission
from policy_registry.models import ActionPermission, UserPolicy


@pytest.fixture(autouse=True)
def _register_bundles() -> None:
    ensure_test_bundles_loaded()


class TestOpaqueDictStorage:
    def test_file_constraints_stored_as_dict(self):
        perm = ActionPermission.model_validate(
            {"safe": False, "constraints": {"allowed_paths": ["/home/*"]}}
        )
        assert isinstance(perm.constraints, dict)
        assert perm.constraints["allowed_paths"] == ["/home/*"]

    def test_host_file_constraints_stored_as_dict(self):
        perm = ActionPermission.model_validate(
            {
                "safe": False,
                "constraints": {"allowed_host_paths": ["~/Documents/*"]},
            }
        )
        assert isinstance(perm.constraints, dict)
        assert perm.constraints["allowed_host_paths"] == ["~/Documents/*"]


class TestJsonRoundtrip:
    def test_host_and_file_constraints_survive_user_policy_roundtrip(self):
        original = UserPolicy(
            user_id="u1",
            agent_id="roundtrip-test",
            allowed_actions={
                "READ_HOST_FILE": ActionPermission(
                    safe=True,
                    constraints={"allowed_host_paths": ["~/Documents/*"]},
                ),
                "READ_FILE": ActionPermission(
                    safe=True,
                    constraints={"allowed_paths": ["/home/*"]},
                ),
            },
        )
        raw = original.model_dump_json()
        rebuilt = UserPolicy.model_validate_json(raw)

        host_perm = rebuilt.allowed_actions["READ_HOST_FILE"]
        file_perm = rebuilt.allowed_actions["READ_FILE"]

        assert host_perm.constraints == {"allowed_host_paths": ["~/Documents/*"]}
        assert file_perm.constraints == {"allowed_paths": ["/home/*"]}


class TestFamilyBundleValidation:
    def test_file_bundle_validates_file_dict(self):
        bundle = action_bundle_for("READ_FILE")
        assert bundle is not None
        bundle.validate_constraints(
            SdkActionPermission(safe=True, constraints={"allowed_paths": ["/home/*"]})
        )

    def test_host_file_bundle_validates_host_dict(self):
        bundle = action_bundle_for("READ_HOST_FILE")
        assert bundle is not None
        bundle.validate_constraints(
            SdkActionPermission(
                safe=True,
                constraints={"allowed_host_paths": ["~/Documents/*"]},
            )
        )

    def test_mixed_fields_rejected_by_family_schemas(self):
        mixed = {
            "allowed_paths": ["/home/*"],
            "allowed_host_paths": ["~/Documents/*"],
        }
        with pytest.raises(ValidationError):
            FileConstraints.model_validate(mixed)
        with pytest.raises(ValidationError):
            HostFileConstraints.model_validate(mixed)
