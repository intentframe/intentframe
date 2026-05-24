"""Unit tests for :class:`intentframe_action_bundle.host_files.bundle.HostFilesActionBundle`.

``HostFilesActionBundle.enforce_constraints`` is the per-action constraint
enforcer for the ``HOST_FILE`` category.  Unlike the virtual ``files``
family, it operates on real host paths — ``~`` expansion + symlink
resolution via :func:`resource_registry.floor.canonicalize_real_path`, then
fnmatch matching against ``HostFileConstraints.allowed_host_paths``.

The floor (``match_deny_prefix``) is a separate wall enforced by DG
``structural_gates`` and by the adapter; this module tests only the user's
per-action allowlist.  Floor interactions are covered in
``tests/test_deterministic_guardian.py::TestHostFileFloorBlock``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from action_registry.types import ActionType
from intentframe_action_bundle.host_files.bundle import HostFilesActionBundle
from intentframe_action_bundle.host_files.constraints import HostFileConstraints
from intentframe_core.types import IntentFrame
from intentframe_bundle_sdk.types import ActionPermission, BundleContext, PhaseDecision


def _intent(target: str, action: ActionType = ActionType.READ_HOST_FILE) -> IntentFrame:
    return IntentFrame(
        action=action,
        target=target,
        reason="test",
        agent_id="host-checker-tester",
    )


_BUNDLE = HostFilesActionBundle()


def _enforce(
    target: str,
    constraints: HostFileConstraints,
    *,
    action: ActionType = ActionType.READ_HOST_FILE,
) -> tuple[bool, str]:
    intent = _intent(target, action=action)
    ctx = BundleContext(intent=intent.model_copy(deep=True))
    outcome = _BUNDLE.enforce_constraints(
        intent,
        ActionPermission(
            safe=False,
            constraints=constraints.model_dump(mode="python"),
        ),
        ctx,
    )
    if outcome.decision is PhaseDecision.BLOCK:
        return False, outcome.reason
    return True, ""


class TestAllowMatching:
    def test_exact_path_match(self):
        home = os.path.expanduser("~")
        c = HostFileConstraints(allowed_host_paths=[f"{home}/Documents/note.txt"])
        ok, _ = _enforce(f"{home}/Documents/note.txt", c)
        assert ok

    def test_tilde_pattern_matches_expanded_target(self):
        c = HostFileConstraints(allowed_host_paths=["~/Documents/note.txt"])
        ok, _ = _enforce("~/Documents/note.txt", c)
        assert ok

    def test_tilde_pattern_matches_absolute_target(self):
        home = os.path.expanduser("~")
        c = HostFileConstraints(allowed_host_paths=["~/Documents/note.txt"])
        ok, _ = _enforce(f"{home}/Documents/note.txt", c)
        assert ok

    def test_glob_pattern_match(self):
        c = HostFileConstraints(allowed_host_paths=["~/Documents/*"])
        ok, _ = _enforce("~/Documents/foo.txt", c)
        assert ok

    def test_directory_match_via_slash_star_pattern(self):
        c = HostFileConstraints(allowed_host_paths=["~/Documents/*"])
        ok, _ = _enforce("~/Documents", c)
        assert ok

    def test_home_root_star_matches_deep_path(self):
        c = HostFileConstraints(allowed_host_paths=["~/*"])
        ok, _ = _enforce("~/Documents/sub/nested.txt", c)
        assert ok


class TestDenyMatching:
    def test_path_outside_allowlist_denied(self):
        c = HostFileConstraints(allowed_host_paths=["~/Documents/*"])
        ok, reason = _enforce("/tmp/escape.txt", c)
        assert not ok
        assert "not in allowed host paths" in reason.lower()

    def test_parent_traversal_denied_after_canonicalize(self, tmp_path):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        forbidden = tmp_path / "forbidden"
        forbidden.mkdir()
        c = HostFileConstraints(allowed_host_paths=[f"{allowed}/*"])
        ok, _ = _enforce(f"{allowed}/../forbidden/escape.txt", c)
        assert not ok

    def test_sibling_directory_denied(self, tmp_path):
        allowed = tmp_path / "Documents"
        allowed.mkdir()
        sibling = tmp_path / "Downloads"
        sibling.mkdir()
        c = HostFileConstraints(allowed_host_paths=[f"{allowed}/*"])
        ok, _ = _enforce(f"{sibling}/other.txt", c)
        assert not ok


class TestDescribe:
    def test_describe_returns_human_readable(self):
        c = HostFileConstraints(allowed_host_paths=["~/Documents/*", "~/Downloads/*"])
        summary = _BUNDLE.describe_constraints(
            ActionPermission(
                safe=False,
                constraints=c.model_dump(mode="python"),
            )
        )
        assert summary is not None
        assert "~/Documents/*" in summary
        assert "~/Downloads/*" in summary
        assert "host" in summary.lower()


class TestIntentTargetMatchesCanonical:
    def test_symlink_target_resolves_before_match(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        (real / "secret.txt").write_text("x")
        link_parent = tmp_path / "link-parent"
        link_parent.mkdir()
        link = link_parent / "alias"
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unsupported in this environment")
        c = HostFileConstraints(allowed_host_paths=[f"{link_parent}/*"])
        ok, _ = _enforce(f"{link}/secret.txt", c)
        assert not ok


class TestTrailingSlashRejectedAtLoadTime:
    def test_trailing_slash_directory_pattern_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            HostFileConstraints(allowed_host_paths=["~/Documents/"])
        msg = str(exc_info.value)
        assert "~/Documents/" in msg
        assert "dir/*" in msg

    def test_absolute_trailing_slash_pattern_rejected(self):
        with pytest.raises(ValidationError):
            HostFileConstraints(allowed_host_paths=["/Users/someone/work/"])

    def test_mixed_valid_and_trailing_slash_rejects_whole_list(self):
        with pytest.raises(ValidationError):
            HostFileConstraints(
                allowed_host_paths=["~/Documents/*", "~/Downloads/"]
            )

    def test_explicit_glob_form_still_accepted(self):
        c = HostFileConstraints(allowed_host_paths=["~/Documents/*"])
        assert c.allowed_host_paths == ["~/Documents/*"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
