"""Policy user id must match :func:`_build_policy` for the same profile + base id."""

from __future__ import annotations

import pytest

from intentframe_gateway import bootstrap as b


def test_policy_user_id_for_current_profile_matches_seeded_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Root profile appends _root; user profile is the unsuffixed base id."""
    monkeypatch.delenv("INTENTFRAME_PROFILE", raising=False)
    monkeypatch.setattr(b, "_resolve_user_id", lambda: "jarvis_default")
    assert b.policy_user_id_for_current_profile() == "jarvis_default"
    assert b._build_policy("user")["user_id"] == b.policy_user_id_for_current_profile()

    monkeypatch.setenv("INTENTFRAME_PROFILE", "root")
    assert b.policy_user_id_for_current_profile() == "jarvis_default_root"
    assert b._build_policy("root")["user_id"] == b.policy_user_id_for_current_profile()
