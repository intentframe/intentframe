"""
Integration tests for Jarvis tool calls through the real IntentFrame pipeline.

Uses the real Actor → IntentFrame Runtime → Executor → macos-appkit-server
chain. All tests are READ-ONLY — they never create, update, or delete data
in your Mac apps. Write-path coverage is limited to payloads that should
fail validation before reaching the adapter (empty titles, bogus IDs, etc.).

Requirements:
    - Supervisor must be running (intentframe-core, policy-registry, executor,
      resource-registry, platform-server)
    - Policies must be seeded (python jarvis_pa/seed_policies.py)

Run:
    python -m jarvis_pa.test_tool_calls
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from intentframe_actor.actor import Actor
from intentframe_core.types import AgentCapabilities, ExecutionResult


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

SOCKET_PATH = "~/.intentframe/run/intentframe.sock"

CAPABILITIES = AgentCapabilities(
    agent_type="PersonalAssistant",
    description="Jarvis tool-call integration tests",
    capabilities=["calendar", "reminders", "notes", "messages"],
    action_types=[
        "LIST_CALENDARS", "LIST_EVENTS", "SEARCH_EVENTS",
        "CREATE_EVENT", "UPDATE_EVENT", "DELETE_EVENT",
        "LIST_REMINDER_LISTS", "LIST_REMINDERS",
        "CREATE_REMINDER", "UPDATE_REMINDER", "COMPLETE_REMINDER", "DELETE_REMINDER",
        "LIST_NOTES", "READ_NOTE", "CREATE_NOTE", "DELETE_NOTE",
        "SEND_MESSAGE", "READ_MESSAGES",
    ],
    version="0.1.0",
    author="test",
)


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

_passed = 0
_failed = 0
_errors: list[str] = []


def _fmt(result: ExecutionResult) -> str:
    if result.success:
        data = result.data
        if isinstance(data, dict):
            return json.dumps(data, indent=2, default=str)[:400]
        return str(data)[:400]
    return f"Error: {result.error}"


async def _submit(actor: Actor, payload: dict[str, Any]) -> ExecutionResult:
    return await actor.submit(payload)


def _check(
    name: str,
    result: ExecutionResult,
    *,
    expect_success: bool | None = None,
    expect_error_contains: str | None = None,
    expect_data_key: str | None = None,
) -> None:
    global _passed, _failed

    issues: list[str] = []

    if expect_success is not None:
        if result.success != expect_success:
            issues.append(
                f"expected success={expect_success}, got success={result.success} "
                f"(error={result.error!r})"
            )

    if expect_error_contains and result.error:
        if expect_error_contains.lower() not in str(result.error).lower():
            issues.append(
                f"expected error containing {expect_error_contains!r}, "
                f"got {result.error!r}"
            )

    if expect_data_key and result.success and isinstance(result.data, dict):
        if expect_data_key not in result.data:
            issues.append(f"expected key {expect_data_key!r} in data")

    if issues:
        _failed += 1
        msg = f"  FAIL  {name}: {'; '.join(issues)}"
        _errors.append(msg)
        print(msg)
        print(f"        raw: {_fmt(result)}")
    else:
        _passed += 1
        status = "ok" if result.success else "ok (expected failure)"
        print(f"  pass  {name} [{status}]")


# ---------------------------------------------------------------------------
# Calendar tests (read-only + negative validation)
# ---------------------------------------------------------------------------

async def test_calendar(actor: Actor) -> None:
    print("\n=== CALENDAR ===")

    now = datetime.now()
    today = now.strftime("%Y-%m-%dT%H:%M:%S")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    next_week = (now + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
    last_week = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")

    # ── reads ──

    r = await _submit(actor, {"action": "LIST_CALENDARS", "reason": "test: discover calendars"})
    _check("list_calendars", r, expect_success=True, expect_data_key="calendars")

    r = await _submit(actor, {
        "action": "LIST_EVENTS", "start": today, "end": tomorrow,
        "limit": 5, "reason": "test: today's events",
    })
    _check("list_events (today)", r, expect_success=True, expect_data_key="events")

    r = await _submit(actor, {
        "action": "LIST_EVENTS", "calendar": "", "start": today, "end": tomorrow,
        "reason": "test: empty calendar → all calendars",
    })
    _check("list_events (calendar='')", r, expect_success=True, expect_data_key="events")

    r = await _submit(actor, {
        "action": "LIST_EVENTS", "reason": "test: no date range → defaults",
    })
    _check("list_events (no dates)", r, expect_success=True, expect_data_key="events")

    r = await _submit(actor, {
        "action": "LIST_EVENTS", "start": last_week, "end": today,
        "limit": 10, "reason": "test: past week",
    })
    _check("list_events (past week)", r, expect_success=True, expect_data_key="events")

    r = await _submit(actor, {
        "action": "LIST_EVENTS", "start": tomorrow, "end": today,
        "reason": "test: inverted date range",
    })
    _check("list_events (inverted range)", r, expect_success=True)

    r = await _submit(actor, {
        "action": "LIST_EVENTS", "start": today, "end": next_week,
        "limit": 0, "reason": "test: limit=0",
    })
    _check("list_events (limit=0)", r, expect_success=True)

    r = await _submit(actor, {
        "action": "LIST_EVENTS", "start": today, "end": next_week,
        "limit": 999, "reason": "test: huge limit",
    })
    _check("list_events (limit=999)", r, expect_success=True)

    r = await _submit(actor, {
        "action": "SEARCH_EVENTS", "query": "meeting",
        "reason": "test: normal search",
    })
    _check("search_events (meeting)", r, expect_success=True, expect_data_key="events")

    r = await _submit(actor, {
        "action": "SEARCH_EVENTS", "query": "xyzzy_no_match_12345",
        "reason": "test: search with no results",
    })
    _check("search_events (no match)", r, expect_success=True)

    # ── negative: reads that should fail ──

    r = await _submit(actor, {
        "action": "LIST_EVENTS", "calendar": "NONEXISTENT_CAL_xyz_999",
        "start": today, "end": tomorrow, "reason": "test: bogus calendar name",
    })
    _check("list_events (bogus calendar)", r, expect_success=False)

    r = await _submit(actor, {
        "action": "SEARCH_EVENTS", "query": "", "reason": "test: empty search query",
    })
    _check("search_events (empty query)", r, expect_success=False)

    # ── negative: writes with invalid params (should fail before creating anything) ──

    r = await _submit(actor, {
        "action": "CREATE_EVENT", "start": tomorrow,
        "reason": "test: create without title",
    })
    _check("create_event (no title)", r, expect_success=False)

    r = await _submit(actor, {
        "action": "CREATE_EVENT", "title": "Test No Start",
        "reason": "test: create without start",
    })
    _check("create_event (no start)", r, expect_success=False)

    r = await _submit(actor, {
        "action": "CREATE_EVENT", "title": "", "start": tomorrow,
        "reason": "test: create with empty title",
    })
    _check("create_event (title='')", r, expect_success=False)

    r = await _submit(actor, {
        "action": "DELETE_EVENT", "event_id": "FAKE_EVENT_ID_000",
        "reason": "test: delete with bogus event_id",
    })
    _check("delete_event (bogus id)", r, expect_success=False)

    r = await _submit(actor, {
        "action": "UPDATE_EVENT", "event_id": "",
        "title": "should fail", "reason": "test: update with empty event_id",
    })
    _check("update_event (empty id)", r, expect_success=False)

    r = await _submit(actor, {
        "action": "UPDATE_EVENT", "event_id": "FAKE_EVENT_ID_000",
        "title": "nope", "reason": "test: update nonexistent event",
    })
    _check("update_event (bogus id)", r, expect_success=False)

    r = await _submit(actor, {
        "action": "DELETE_EVENT", "event_id": "",
        "reason": "test: delete with empty event_id",
    })
    _check("delete_event (empty id)", r, expect_success=False)


# ---------------------------------------------------------------------------
# Reminders tests (read-only + negative validation)
# ---------------------------------------------------------------------------

async def test_reminders(actor: Actor) -> None:
    print("\n=== REMINDERS ===")

    # ── reads ──

    r = await _submit(actor, {"action": "LIST_REMINDER_LISTS", "reason": "test: discover lists"})
    _check("list_reminder_lists", r, expect_success=True, expect_data_key="lists")

    r = await _submit(actor, {
        "action": "LIST_REMINDERS", "limit": 5,
        "reason": "test: list reminders",
    })
    _check("list_reminders (all)", r, expect_success=True, expect_data_key="reminders")

    r = await _submit(actor, {
        "action": "LIST_REMINDERS", "list": "",
        "reason": "test: empty list name → all lists",
    })
    _check("list_reminders (list='')", r, expect_success=True, expect_data_key="reminders")

    r = await _submit(actor, {
        "action": "LIST_REMINDERS", "include_completed": True, "limit": 5,
        "reason": "test: include completed",
    })
    _check("list_reminders (include_completed)", r, expect_success=True)

    r = await _submit(actor, {
        "action": "LIST_REMINDERS", "include_completed": False, "limit": 0,
        "reason": "test: limit=0",
    })
    _check("list_reminders (limit=0)", r, expect_success=True)

    r = await _submit(actor, {
        "action": "LIST_REMINDERS", "list": "Reminders",
        "reason": "test: explicit default list name",
    })
    _check("list_reminders (explicit 'Reminders')", r, expect_success=True)

    # ── negative: reads that should fail ──

    r = await _submit(actor, {
        "action": "LIST_REMINDERS", "list": "NONEXISTENT_LIST_xyz_999",
        "reason": "test: bogus list name",
    })
    _check("list_reminders (bogus list)", r, expect_success=False)

    # ── negative: writes with invalid params ──

    r = await _submit(actor, {
        "action": "CREATE_REMINDER", "reason": "test: create without title",
    })
    _check("create_reminder (no title)", r, expect_success=False)

    r = await _submit(actor, {
        "action": "CREATE_REMINDER", "title": "",
        "reason": "test: create with empty title",
    })
    _check("create_reminder (title='')", r, expect_success=False)

    r = await _submit(actor, {
        "action": "DELETE_REMINDER", "reminder_id": "FAKE_REMINDER_ID_000",
        "reason": "test: delete with bogus reminder_id",
    })
    _check("delete_reminder (bogus id)", r, expect_success=False)

    r = await _submit(actor, {
        "action": "UPDATE_REMINDER", "reminder_id": "",
        "title": "should fail", "reason": "test: update with empty reminder_id",
    })
    _check("update_reminder (empty id)", r, expect_success=False)

    r = await _submit(actor, {
        "action": "UPDATE_REMINDER", "reminder_id": "FAKE_REMINDER_ID_000",
        "title": "nope", "reason": "test: update nonexistent reminder",
    })
    _check("update_reminder (bogus id)", r, expect_success=False)

    r = await _submit(actor, {
        "action": "COMPLETE_REMINDER",
        "reason": "test: complete with no identifier",
    })
    _check("complete_reminder (no id)", r, expect_success=False)

    r = await _submit(actor, {
        "action": "COMPLETE_REMINDER", "reminder_id": "FAKE_REMINDER_ID_000",
        "reason": "test: complete nonexistent reminder",
    })
    _check("complete_reminder (bogus id)", r, expect_success=False)

    r = await _submit(actor, {
        "action": "DELETE_REMINDER", "reminder_id": "",
        "reason": "test: delete with empty id",
    })
    _check("delete_reminder (empty id)", r, expect_success=False)


# ---------------------------------------------------------------------------
# Notes tests (read-only + negative validation)
# ---------------------------------------------------------------------------

async def test_notes(actor: Actor) -> None:
    print("\n=== NOTES ===")

    # ── reads ──

    r = await _submit(actor, {"action": "LIST_NOTES", "reason": "test: list notes"})
    _check("list_notes", r, expect_success=True, expect_data_key="notes")

    r = await _submit(actor, {
        "action": "LIST_NOTES", "folder": "",
        "reason": "test: empty folder → all folders",
    })
    _check("list_notes (folder='')", r, expect_success=True, expect_data_key="notes")

    r = await _submit(actor, {
        "action": "LIST_NOTES", "folder": "NONEXISTENT_FOLDER_xyz",
        "reason": "test: bogus folder name",
    })
    _check("list_notes (bogus folder)", r, expect_success=True)

    # ── negative: reads that should fail ──

    r = await _submit(actor, {
        "action": "READ_NOTE", "title": "NONEXISTENT_NOTE_xyz_999",
        "reason": "test: read nonexistent note",
    })
    _check("read_note (nonexistent)", r, expect_success=False)

    r = await _submit(actor, {
        "action": "READ_NOTE", "title": "",
        "reason": "test: read with empty title",
    })
    _check("read_note (empty title)", r, expect_success=False)

    # ── negative: writes with invalid params ──

    r = await _submit(actor, {
        "action": "CREATE_NOTE", "title": "",
        "body": "should fail", "reason": "test: create with empty title",
    })
    _check("create_note (empty title)", r, expect_success=False)

    r = await _submit(actor, {
        "action": "DELETE_NOTE", "title": "",
        "reason": "test: delete with empty title",
    })
    _check("delete_note (empty title)", r, expect_success=False)

    r = await _submit(actor, {
        "action": "DELETE_NOTE", "title": "NONEXISTENT_NOTE_xyz_999",
        "reason": "test: delete nonexistent note",
    })
    _check("delete_note (nonexistent)", r, expect_success=False)


# ---------------------------------------------------------------------------
# Messages tests (read-only + negative validation)
# ---------------------------------------------------------------------------

async def test_messages(actor: Actor) -> None:
    print("\n=== MESSAGES ===")

    # ── reads ──

    r = await _submit(actor, {
        "action": "READ_MESSAGES", "limit": 3,
        "reason": "test: read recent messages",
    })
    _check("read_messages (all)", r, expect_success=True)

    r = await _submit(actor, {
        "action": "READ_MESSAGES", "contact": "", "limit": 3,
        "reason": "test: empty contact → all",
    })
    _check("read_messages (contact='')", r, expect_success=True)

    r = await _submit(actor, {
        "action": "READ_MESSAGES", "contact": "FAKE_PERSON_999",
        "limit": 3, "reason": "test: bogus contact name",
    })
    _check("read_messages (bogus contact)", r, expect_success=True)

    r = await _submit(actor, {
        "action": "READ_MESSAGES", "limit": 0,
        "reason": "test: limit=0",
    })
    _check("read_messages (limit=0)", r, expect_success=True)

    # ── negative: sends with invalid params (should fail before sending) ──

    r = await _submit(actor, {
        "action": "SEND_MESSAGE", "to": "", "text": "test",
        "reason": "test: send with empty recipient",
    })
    _check("send_message (empty to)", r, expect_success=False)

    r = await _submit(actor, {
        "action": "SEND_MESSAGE", "to": "+15555555555",
        "text": "", "reason": "test: send with empty text",
    })
    _check("send_message (empty text)", r, expect_success=False)

    r = await _submit(actor, {
        "action": "SEND_MESSAGE", "to": "not_a_phone_or_email",
        "text": "", "reason": "test: send with invalid recipient format + empty text",
    })
    _check("send_message (invalid to + empty text)", r, expect_success=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    socket = Path(SOCKET_PATH).expanduser()
    if not socket.exists():
        print(f"Error: IntentFrame socket not found at {socket}")
        print("Start the supervisor first: python -m supervisor.main start")
        sys.exit(1)

    actor = Actor(agent_id="jarvis-test", user_id="jarvis_default", socket_path=str(socket))
    await actor.handshake(CAPABILITIES)
    print(f"Handshake complete. Session: {actor.runtime_context.session_id}")

    try:
        await test_calendar(actor)
        await test_reminders(actor)
        await test_notes(actor)
        await test_messages(actor)
    finally:
        await actor.close()

    total = _passed + _failed
    print(f"\n{'=' * 60}")
    print(f"Results: {_passed}/{total} passed, {_failed} failed")
    if _errors:
        print("\nFailures:")
        for e in _errors:
            print(e)
    print(f"{'=' * 60}")

    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
