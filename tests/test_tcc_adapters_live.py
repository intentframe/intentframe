"""
Live integration tests for TCC-gated macOS adapters (calendar, reminders, contacts).

These tests talk to the real running macos-appkit-server (Swift platform server)
via its Unix domain socket. Start it with the IntentFrame CLI before running:

    intentframe-gateway-cli start          # or supervisor start
    # then in another terminal:
    .venv/bin/python -m pytest tests/test_tcc_adapters_live.py -v

Read-only only: every adapter action exercised here is a list/search/get-style
read. No create/update/delete/complete — nothing to clean up.

If the platform server is not reachable, every test in this file marks as
``xfail`` with a message telling you to start the server. It does NOT skip
silently — xfail shows up in the pytest results table so the gap is visible.

TCC grants required (System Settings > Privacy & Security):
    - Calendars    → for calendar adapter tests
    - Reminders    → for reminders adapter tests
    - Contacts     → for contacts adapter tests

If the server is up but a grant is missing, the relevant test group marks
xfail with the specific grant name so you know exactly what to fix.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import pytest

# ── platform guard ────────────────────────────────────────────────────────────
pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="TCC adapters are macOS-only",
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _run(coro) -> Any:
    return asyncio.run(coro)


def _socket_path() -> str:
    from intentframe_native_kit.intentframe_executor_pack_macos.adapters._platform_client import _socket_path
    return _socket_path()


# ── session-scoped server probe ───────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def require_platform_server() -> None:
    """Probe the Swift platform server once per session.

    Calls ``pytest.xfail`` (not skip) if the server is down so every test in
    this file appears as ``xfail`` in the results rather than disappearing
    silently. The xfail message tells you exactly how to fix it.
    """
    from intentframe_native_kit.intentframe_executor_pack_macos.adapters._platform_client import (
        PlatformServerUnavailable,
        platform_health,
    )
    try:
        _run(platform_health())
    except PlatformServerUnavailable:
        pytest.xfail(
            f"macos-appkit-server is not running at {_socket_path()}. "
            "Start it with the IntentFrame CLI ('intentframe-gateway-cli start' "
            "or 'python -m supervisor.main start --config "
            "intentframe_native_kit/supervisor_profile.yaml') then re-run."
        )
    except Exception as exc:
        pytest.xfail(f"Platform server health check failed unexpectedly: {exc}")


@pytest.fixture(scope="session")
def tcc_grants() -> dict[str, bool]:
    """Return the raw TCC grant dict from the platform server.

    Shape: ``{"calendar": {"granted": True, "hint": "..."}, ...}``
    """
    from intentframe_native_kit.intentframe_executor_pack_macos.adapters._platform_client import platform_permissions
    return _run(platform_permissions()) or {}


def _require_grant(tcc_grants: dict, adapter_id: str) -> None:
    """xfail (not skip) if the TCC grant for *adapter_id* is missing."""
    detail = tcc_grants.get(adapter_id, {})
    if not detail.get("granted", False):
        hint = detail.get("hint", "Grant in System Settings > Privacy & Security")
        pytest.xfail(
            f"TCC grant for '{adapter_id}' is not granted — {hint}. "
            "Grant it and re-run."
        )


# ── permissions endpoint ──────────────────────────────────────────────────────

class TestPermissionsEndpoint:
    """Verify the /permissions endpoint itself is healthy and well-formed."""

    def test_permissions_response_is_dict(self, tcc_grants) -> None:
        assert isinstance(tcc_grants, dict), (
            f"/permissions returned {type(tcc_grants).__name__}, expected dict"
        )

    def test_permissions_contains_tcc_adapters(self, tcc_grants) -> None:
        from intentframe_native_kit.intentframe_executor_pack_macos.permissions import TCC_ADAPTERS
        missing = TCC_ADAPTERS - set(tcc_grants)
        assert not missing, (
            f"/permissions response missing keys for TCC adapters: {sorted(missing)}"
        )

    def test_each_entry_has_granted_field(self, tcc_grants) -> None:
        from intentframe_native_kit.intentframe_executor_pack_macos.permissions import TCC_ADAPTERS
        bad = [k for k in TCC_ADAPTERS if "granted" not in tcc_grants.get(k, {})]
        assert not bad, f"entries missing 'granted' field: {bad}"

    def test_check_permissions_matches_endpoint(self, tcc_grants) -> None:
        from intentframe_native_kit.intentframe_executor_pack_macos.permissions import (
            TCC_ADAPTERS,
            _platform_perms,
        )
        # Bust the lru_cache so this test always does a fresh query
        _platform_perms.cache_clear()
        from intentframe_native_kit.intentframe_executor_pack_macos.permissions import check_permissions
        result = check_permissions(list(TCC_ADAPTERS))
        for adapter_id in TCC_ADAPTERS:
            expected = bool(tcc_grants.get(adapter_id, {}).get("granted", False))
            assert result[adapter_id] == expected, (
                f"check_permissions('{adapter_id}') returned {result[adapter_id]}, "
                f"expected {expected} from /permissions"
            )


# ── adapter construction ──────────────────────────────────────────────────────

class TestAdapterConstruction:
    """All three TCC adapters must construct without raising, even if grant is denied."""

    def test_calendar_adapter_constructs(self) -> None:
        from intentframe_native_kit.intentframe_executor_pack_macos.adapters.calendar import CalendarAdapter
        adapter = CalendarAdapter()
        assert adapter.manifest().adapter_id == "calendar"

    def test_reminders_adapter_constructs(self) -> None:
        from intentframe_native_kit.intentframe_executor_pack_macos.adapters.reminders import RemindersAdapter
        adapter = RemindersAdapter()
        assert adapter.manifest().adapter_id == "reminders"

    def test_contacts_adapter_constructs(self) -> None:
        from intentframe_native_kit.intentframe_executor_pack_macos.adapters.contacts import ContactsAdapter
        adapter = ContactsAdapter()
        assert adapter.manifest().adapter_id == "contacts"


# ── calendar ─────────────────────────────────────────────────────────────────

class TestCalendarAdapter:
    """Live calendar adapter tests (read-only) — require the Calendars TCC grant."""

    @pytest.fixture(autouse=True)
    def _need_grant(self, tcc_grants) -> None:
        _require_grant(tcc_grants, "calendar")

    @pytest.fixture
    def adapter(self):
        from intentframe_native_kit.intentframe_executor_pack_macos.adapters.calendar import CalendarAdapter
        return CalendarAdapter()

    def test_list_calendars_succeeds(self, adapter) -> None:
        from intentframe_native_kit.intentframe_executor_pack_macos.adapters._platform_client import platform_execute
        resp = _run(platform_execute("calendar", "LIST_CALENDARS", {}))
        assert isinstance(resp, dict), f"Expected dict, got {type(resp).__name__}"
        assert resp.get("success") is True, f"LIST_CALENDARS failed: {resp.get('error')}"

    def test_list_calendars_via_adapter(self, adapter) -> None:
        result = _run(adapter.execute("LIST_CALENDARS", {}))
        assert result.success is True, f"LIST_CALENDARS adapter error: {result.error}"
        assert result.data is not None

    def test_list_events_empty_range_succeeds(self, adapter) -> None:
        """LIST_EVENTS with a date range that returns zero events still succeeds."""
        params = {
            "start": "1970-01-01T00:00:00",
            "end": "1970-01-02T00:00:00",
        }
        result = _run(adapter.execute("LIST_EVENTS", params))
        assert result.success is True, f"LIST_EVENTS failed: {result.error}"

    def test_search_events_nonexistent_returns_empty(self, adapter) -> None:
        result = _run(adapter.execute("SEARCH_EVENTS", {
            "query": "intentframe_nonexistent_test_event_xyz_abc",
        }))
        assert result.success is True, f"SEARCH_EVENTS failed: {result.error}"
        events = (result.data or {}).get("events", [])
        assert isinstance(events, list)
        assert events == [], f"Expected no matches, got {events}"


# ── reminders ────────────────────────────────────────────────────────────────

class TestRemindersAdapter:
    """Live reminders adapter tests (read-only) — require the Reminders TCC grant."""

    @pytest.fixture(autouse=True)
    def _need_grant(self, tcc_grants) -> None:
        _require_grant(tcc_grants, "reminders")

    @pytest.fixture
    def adapter(self):
        from intentframe_native_kit.intentframe_executor_pack_macos.adapters.reminders import RemindersAdapter
        return RemindersAdapter()

    def test_list_reminder_lists_succeeds(self, adapter) -> None:
        result = _run(adapter.execute("LIST_REMINDER_LISTS", {}))
        assert result.success is True, f"LIST_REMINDER_LISTS failed: {result.error}"
        assert result.data is not None

    def test_list_reminders_succeeds(self, adapter) -> None:
        result = _run(adapter.execute("LIST_REMINDERS", {}))
        assert result.success is True, f"LIST_REMINDERS failed: {result.error}"


# ── contacts ─────────────────────────────────────────────────────────────────

class TestContactsAdapter:
    """Live contacts adapter tests (read-only) — require the Contacts TCC grant."""

    @pytest.fixture(autouse=True)
    def _need_grant(self, tcc_grants) -> None:
        _require_grant(tcc_grants, "contacts")

    @pytest.fixture
    def adapter(self):
        from intentframe_native_kit.intentframe_executor_pack_macos.adapters.contacts import ContactsAdapter
        return ContactsAdapter()

    def test_search_contacts_empty_query_rejected(self, adapter) -> None:
        """Empty query is rejected by the platform server (matches Jarvis validation)."""
        result = _run(adapter.execute("SEARCH_CONTACTS", {"query": ""}))
        assert result.success is False
        assert "query" in (result.error or "").lower()

    def test_search_contacts_nonexistent_returns_empty(self, adapter) -> None:
        result = _run(adapter.execute("SEARCH_CONTACTS", {
            "query": "intentframe_nonexistent_test_contact_xyz_abc",
        }))
        assert result.success is True, f"SEARCH_CONTACTS failed: {result.error}"
        items = (result.data or {}).get("contacts", [])
        assert isinstance(items, list)
        assert items == [], f"Expected no matches, got {items}"
