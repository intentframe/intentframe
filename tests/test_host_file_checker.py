"""Unit tests for :class:`intentframe_components.guardian.checkers.host_file.HostFileChecker`.

``HostFileChecker`` is the per-action constraint enforcer for the
``HOST_FILE`` category.  Unlike ``FileChecker`` (virtual paths), it
operates on *real* host paths — ``~`` expansion + symlink resolution
via :func:`resource_registry.floor.canonicalize_real_path`, then
fnmatch matching against ``HostFileConstraints.allowed_host_paths``.

Covers:

- exact-match allow;
- glob match via ``~/Documents/*`` (the only supported subtree form);
- ``~`` expansion symmetry between agent target and policy pattern;
- out-of-scope denial (no false ALLOW);
- parent-traversal denial (``..`` resolves outside allowlist);
- load-time rejection of trailing-slash directory shorthand
  (``~/Documents/``) by ``HostFileConstraints``.

The floor (``match_deny_prefix``) is a *separate* wall enforced by DG
and by the adapter; the checker is only responsible for the user's
per-action allowlist.  Floor interactions are covered in
``tests/test_deterministic_guardian.py::TestHostFileFloorBlock``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from action_registry.types import ActionType
from intentframe_components.guardian.checkers.host_file import HostFileChecker
from intentframe_core.types import IntentFrame
from policy_registry.constraints.host_file import HostFileConstraints


def _intent(target: str, action: ActionType = ActionType.READ_HOST_FILE) -> IntentFrame:
    return IntentFrame(
        action=action,
        target=target,
        reason="test",
        agent_id="host-checker-tester",
    )


CHECKER = HostFileChecker()


class TestAllowMatching:
    def test_exact_path_match(self):
        home = os.path.expanduser("~")
        c = HostFileConstraints(allowed_host_paths=[f"{home}/Documents/note.txt"])
        ok, _ = CHECKER.check(_intent(f"{home}/Documents/note.txt"), c)
        assert ok

    def test_tilde_pattern_matches_expanded_target(self):
        # Policy uses ~/..., agent emits ~/... — canonicalizer expands
        # both sides.  Must match.
        c = HostFileConstraints(allowed_host_paths=["~/Documents/note.txt"])
        ok, _ = CHECKER.check(_intent("~/Documents/note.txt"), c)
        assert ok

    def test_tilde_pattern_matches_absolute_target(self):
        # Agent emits the already-expanded absolute path; policy has ~/...
        # Canonicalizer normalizes both sides to absolute.
        home = os.path.expanduser("~")
        c = HostFileConstraints(allowed_host_paths=["~/Documents/note.txt"])
        ok, _ = CHECKER.check(_intent(f"{home}/Documents/note.txt"), c)
        assert ok

    def test_glob_pattern_match(self):
        c = HostFileConstraints(allowed_host_paths=["~/Documents/*"])
        ok, _ = CHECKER.check(_intent("~/Documents/foo.txt"), c)
        assert ok

    def test_directory_match_via_slash_star_pattern(self):
        # ``~/Documents/*`` also admits the directory itself (``/Documents``)
        # so LIST_HOST_DIRECTORY on the root of an allowlist works.
        c = HostFileConstraints(allowed_host_paths=["~/Documents/*"])
        ok, _ = CHECKER.check(_intent("~/Documents"), c)
        assert ok

    def test_home_root_star_matches_deep_path(self):
        # Jarvis seed policy uses ["~/*"] — verify that pattern admits
        # deeply nested paths under HOME, matching what
        # jarvis_pa/executor.yaml's allowed_write_paths: ["~/"] allows.
        c = HostFileConstraints(allowed_host_paths=["~/*"])
        ok, _ = CHECKER.check(_intent("~/Documents/sub/nested.txt"), c)
        assert ok


class TestDenyMatching:
    def test_path_outside_allowlist_denied(self):
        c = HostFileConstraints(allowed_host_paths=["~/Documents/*"])
        ok, reason = CHECKER.check(_intent("/tmp/escape.txt"), c)
        assert not ok
        assert "not in allowed host paths" in reason.lower()

    def test_parent_traversal_denied_after_canonicalize(self, tmp_path):
        # Build an allowlist rooted at tmp_path / "allowed" and a target
        # that tries to ../ out.  Canonicalizer resolves .. before the
        # checker sees it, so the match fails cleanly.
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        forbidden = tmp_path / "forbidden"
        forbidden.mkdir()
        c = HostFileConstraints(allowed_host_paths=[f"{allowed}/*"])
        ok, _ = CHECKER.check(_intent(f"{allowed}/../forbidden/escape.txt"), c)
        assert not ok

    def test_sibling_directory_denied(self, tmp_path):
        allowed = tmp_path / "Documents"
        allowed.mkdir()
        sibling = tmp_path / "Downloads"
        sibling.mkdir()
        c = HostFileConstraints(allowed_host_paths=[f"{allowed}/*"])
        ok, _ = CHECKER.check(_intent(f"{sibling}/other.txt"), c)
        assert not ok


class TestSummarize:
    def test_summarize_returns_human_readable(self):
        c = HostFileConstraints(allowed_host_paths=["~/Documents/*", "~/Downloads/*"])
        summary = CHECKER.summarize(c)
        assert "~/Documents/*" in summary
        assert "~/Downloads/*" in summary
        assert "host" in summary.lower()


class TestIntentTargetMatchesCanonical:
    def test_symlink_target_resolves_before_match(self, tmp_path):
        # If the canonicalizer resolves a symlink to a real path that's
        # outside the allowlist, the checker must deny — covering the
        # basic symlink-escape case the checker defends against.
        real = tmp_path / "real"
        real.mkdir()
        (real / "secret.txt").write_text("x")
        link_parent = tmp_path / "link-parent"
        link_parent.mkdir()
        link = link_parent / "alias"
        # Create symlink link -> real (directory symlink).  On platforms
        # that don't allow symlinks we skip.
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unsupported in this environment")
        # Allowlist only the link_parent directory — NOT the symlink
        # target.  A target that traverses through the symlink will
        # canonicalize to the real directory and fall outside the list.
        c = HostFileConstraints(allowed_host_paths=[f"{link_parent}/*"])
        ok, _ = CHECKER.check(_intent(f"{link}/secret.txt"), c)
        assert not ok


class TestTrailingSlashRejectedAtLoadTime:
    """Pin the HostFileConstraints field validator.

    Rationale (see docstring on
    :meth:`HostFileConstraints._reject_trailing_slash`): trailing-slash
    directory shorthand collapses to the same canonical form as the
    bare directory path under ``Path.resolve``, so the matcher branch
    that historically handled it becomes dead code.  Rather than
    resurrect the branch with a parallel non-canonical comparison
    (with its attendant allowlist-widening risk), we reject the
    syntax at config load time.  These tests pin three things:

    1. ``"~/Documents/"`` fails fast with ``ValidationError`` — the
       policy author sees the problem at startup, not via a silent
       runtime false-deny.
    2. The error message names the offending pattern and points at
       the supported alternative (``dir/*``).
    3. The explicit glob form (``"~/Documents/*"``) still loads
       cleanly — we are narrowing the accepted syntax, not breaking
       the primary one.
    """

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
        # One bad entry must fail the whole load; partial acceptance
        # would mean a typo could silently drop an intended allow.
        with pytest.raises(ValidationError):
            HostFileConstraints(
                allowed_host_paths=["~/Documents/*", "~/Downloads/"]
            )

    def test_explicit_glob_form_still_accepted(self):
        # Sanity: the supported replacement syntax must keep loading.
        c = HostFileConstraints(allowed_host_paths=["~/Documents/*"])
        assert c.allowed_host_paths == ["~/Documents/*"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
