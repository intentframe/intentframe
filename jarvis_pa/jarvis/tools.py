"""Tool definitions for Jarvis PA.

``Actor.submit`` wrappers plus agent-only tools (``memory_search``,
``memory_get``, ``spawn_agent``).

Each I/O tool follows the same pattern:
  1. Build a typed Pydantic action model (tool-schema validation).
  2. Optional registry pre-flight via ``_validate_against_registry`` — Jarvis
     imports ``intentframe_native_kit.action_registry`` as author-side convenience (taxonomy + domain
     payload slices). The Actor itself does not import the registry.
  3. Submit through ``actor.submit()`` — every call hits the IntentFrame
     Guardian pipeline. Server-side bundles re-validate authoritatively.

The LLM sees these as plain callable functions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents import RunContextWrapper, WebSearchTool, function_tool
from loguru import logger
from pydantic import BaseModel

# Author-side convenience: jarvis (the agent author) opts into the action
# registry to fail fast before the network round-trip. The actor and core stay
# decoupled from the registry; the IntentFrame pipeline still re-validates
# authoritatively server-side.
from intentframe_native_kit.action_registry.domains import DOMAIN_SCHEMAS
from intentframe_native_kit.action_registry.types import ACTION_DOMAINS, ActionType

from jarvis.types import AgentContext

# ---------------------------------------------------------------------------
# Typed action models — validate payloads before actor.submit()
#
# Field names MUST match the adapter's params.get() keys exactly.
# The actor auto-captures every field except action/target/reason into
# IntentFrame.data, which the executor client forwards as adapter params.
# ---------------------------------------------------------------------------

# ── Host-file actions ─────────────────────────────────────────────────
# ``target`` carries a real host path like ``~/Documents/foo.txt``.

# File tools: ``path`` is the executable field — it lands in IntentFrame.data
# and is exactly what the executor adapter acts on (params["path"]) and what
# deterministic/domain checks validate. ``target`` is display/audit only.
class _ReadHostFileAction(BaseModel):
    action: str = "READ_HOST_FILE"
    target: str
    path: str
    reason: str
    offset: int | None = None
    limit: int | None = None

class _WriteHostFileAction(BaseModel):
    action: str = "WRITE_HOST_FILE"
    target: str
    path: str
    content: str
    reason: str

class _ListHostDirectoryAction(BaseModel):
    action: str = "LIST_HOST_DIRECTORY"
    target: str
    path: str
    reason: str

class _DeleteHostFileAction(BaseModel):
    action: str = "DELETE_HOST_FILE"
    target: str
    reason: str
    # DELETE_HOST_FILE is in the deletion domain; ``path`` satisfies
    # DeletionIntentData and is the field both the domain policy and the
    # executor act on. ``target`` is display/audit only.
    path: str
    irreversible: bool = True

class _CommandAction(BaseModel):
    action: str = "RUN_COMMAND"
    command: str
    reason: str

class _EmailSendAction(BaseModel):
    action: str = "SEND_EMAIL"
    account_email: str
    to: str
    subject: str
    body: str
    reason: str

class _EmailReadAction(BaseModel):
    action: str = "READ_EMAIL"
    account_email: str
    mailbox: str = "INBOX"
    limit: int = 10
    reason: str

class _EmailSearchAction(BaseModel):
    action: str = "SEARCH_EMAIL"
    account_email: str
    query: str
    reason: str

class _EmailGetAction(BaseModel):
    action: str = "GET_EMAIL"
    rfc_message_id: str
    headers_only: bool = False
    reason: str

class _EmailReplyAction(BaseModel):
    action: str = "REPLY_EMAIL"
    rfc_message_id: str
    body: str
    reply_all: bool = False
    reason: str

class _EmailForwardAction(BaseModel):
    action: str = "FORWARD_EMAIL"
    rfc_message_id: str
    to: str
    body: str = ""
    reason: str

class _EmailMarkReadAction(BaseModel):
    action: str = "MARK_READ_EMAIL"
    rfc_message_id: str
    read: bool = True
    reason: str

class _EmailMoveAction(BaseModel):
    action: str = "MOVE_EMAIL"
    rfc_message_id: str
    to_folder: str
    reason: str

class _EmailDeleteAction(BaseModel):
    action: str = "DELETE_EMAIL"
    rfc_message_id: str
    reason: str

class _EmailDownloadAttachmentAction(BaseModel):
    action: str = "DOWNLOAD_ATTACHMENT"
    rfc_message_id: str
    filename: str
    reason: str

class _CalendarAction(BaseModel):
    action: str
    title: str = ""
    start: str = ""
    end: str = ""
    calendar: str = ""
    location: str = ""
    notes: str = ""
    event_id: str = ""
    query: str = ""
    duration: int = 0
    future_events: bool = False
    limit: int = 20
    reason: str

class _ReminderAction(BaseModel):
    action: str
    title: str = ""
    due_date: str = ""
    list: str = ""
    notes: str = ""
    reminder_id: str = ""
    priority: int = 0
    undo: bool = False
    include_completed: bool = False
    limit: int = 20
    reason: str

class _ContactAction(BaseModel):
    action: str
    query: str = ""
    name: str = ""
    contact_id: str = ""
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    organization: str = ""
    job_title: str = ""
    nickname: str = ""
    notes: str = ""
    limit: int = 20
    reason: str

class _NoteAction(BaseModel):
    action: str
    title: str = ""
    body: str = ""
    folder: str = ""
    reason: str

class _MessageAction(BaseModel):
    action: str = "SEND_MESSAGE"
    to: str
    text: str
    service: str = "iMessage"
    reason: str

class _ReadMessagesAction(BaseModel):
    action: str = "READ_MESSAGES"
    contact: str = ""
    limit: int = 10
    reason: str

class _BrowserAction(BaseModel):
    action: str
    url: str = ""
    query: str = ""
    reason: str

class _ClipboardAction(BaseModel):
    action: str
    content: str = ""
    reason: str

class _SpotlightAction(BaseModel):
    action: str = "SEARCH_SPOTLIGHT"
    query: str
    reason: str

class _NotificationAction(BaseModel):
    action: str = "SHOW_NOTIFICATION"
    title: str = ""
    message: str = ""
    reason: str

class _UserIOAction(BaseModel):
    action: str = "ASK_USER"
    prompt: str
    options: list[str] = []
    reason: str

class _SystemAction(BaseModel):
    action: str
    level: float = 0.0
    reason: str


# ---------------------------------------------------------------------------
# Result rendering
# ---------------------------------------------------------------------------
#
# The LLM must see the same structured shape on both success and failure;
# otherwise it loses useful context (e.g. a `find` with rc=1 still has
# thousands of lines of real answers in stdout). We forward the full data
# dict in both cases but cap the known-big string fields so a multi-MB
# blob from a noisy command can't torch the context window.
#
# Caps are per-field (not a single JSON cap) so the payload stays valid
# JSON and small keys like return_code / command always make it through.
# Truncation keeps head + tail: listings keep their first entries and
# compile logs keep the real error line at the bottom.

MAX_STDOUT_CHARS = 8192    # ~2k tokens — fine for listings, diffs, logs
MAX_STDERR_CHARS = 2048    # errors are almost always short
MAX_CONTENT_CHARS = 8192   # paginated file reads still get a backstop cap
MAX_ERROR_CHARS = 2048     # for result.error when distinct from stderr

_TRUNCATE_LIMITS: dict[str, int] = {
    "stdout": MAX_STDOUT_CHARS,
    "stderr": MAX_STDERR_CHARS,
    "content": MAX_CONTENT_CHARS,
}


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    """Return ``(maybe_shortened, was_truncated)`` using a head+tail window.

    Preserves the first and last portions of the text so both the start
    of a listing and the trailing error/summary line survive. The marker
    in the middle tells the LLM the gap is a truncation, not real data.
    """
    if len(text) <= limit:
        return text, False
    head = limit // 2
    tail = limit - head
    dropped = len(text) - limit
    return f"{text[:head]}\n…[{dropped} chars truncated]…\n{text[-tail:]}", True


def _render_result(result: Any) -> str:
    """Serialise an ExecutionResult for the LLM.

    Success and failure produce the same shape — a JSON object with
    ``success`` plus the adapter's ``data`` fields (truncated where
    relevant). On failure, ``error`` is added only when it carries
    information beyond what ``stderr`` already contains, avoiding the
    duplicate text that ``f"Error: {stderr}"`` used to emit.

    Falls back to plain strings when ``data`` is not a dict (rare:
    some adapters return a scalar or None).
    """
    if not isinstance(result.data, dict):
        if result.success:
            return str(result.data) if result.data is not None else "OK"
        return f"Error: {result.error or 'unknown error'}"

    rendered: dict[str, Any] = {"success": result.success}
    for key, value in result.data.items():
        limit = _TRUNCATE_LIMITS.get(key)
        if limit is not None and isinstance(value, str):
            shortened, was_truncated = _truncate(value, limit)
            rendered[key] = shortened
            if was_truncated:
                rendered[f"{key}_truncated"] = True
                rendered[f"{key}_total_chars"] = len(value)
        else:
            rendered[key] = value

    if not result.success and result.error:
        # For terminal failures result.error is literally stderr — don't
        # double-send it. For other adapters (email, calendar, etc.) it's
        # distinct information and must be surfaced.
        #
        # Compare against the ORIGINAL stderr, not the truncated form;
        # otherwise a large stderr (cap-triggered) would never match
        # result.error and we'd emit both fields with the same text.
        original_stderr = result.data.get("stderr")
        if original_stderr != result.error:
            err_short, err_truncated = _truncate(result.error, MAX_ERROR_CHARS)
            rendered["error"] = err_short
            if err_truncated:
                rendered["error_truncated"] = True

    return json.dumps(rendered, default=str)


# ---------------------------------------------------------------------------
# Shared submit helper
# ---------------------------------------------------------------------------

def _validate_against_registry(payload: dict[str, Any]) -> str | None:
    """Author-side pre-flight validation using the action registry.

    Returns an error string if the action is unknown to the taxonomy or its
    critical-domain payload slice is malformed; otherwise ``None``. This is a
    fail-fast convenience that runs before the network round-trip — the
    IntentFrame pipeline re-validates authoritatively server-side regardless,
    so this never weakens enforcement.
    """
    action_str = payload.get("action", "")
    try:
        action = ActionType(action_str)
    except ValueError:
        return (
            f"Error: unknown action '{action_str}' — not part of the action "
            f"registry taxonomy."
        )

    domain = ACTION_DOMAINS.get(action)
    if domain is not None:
        schema_cls = DOMAIN_SCHEMAS.get(domain)
        if schema_cls is not None:
            try:
                schema_cls.validate_slice(payload)
            except Exception as exc:
                return (
                    f"Error: {action.value} is in the {domain.value} domain and "
                    f"requires valid {schema_cls.__name__} data: {exc}"
                )
    return None


async def _submit(ctx: RunContextWrapper[AgentContext], action: BaseModel) -> str:
    """Submit an action through the actor and return a string result."""
    payload = action.model_dump()
    action_type = payload.get("action", "UNKNOWN")
    payload["display_subject"] = (
        payload.get("target")
        or payload.get("message_id")
        or payload.get("command")
        or payload.get("query")
        or payload.get("url")
        or ""
    )

    pre_flight_error = _validate_against_registry(payload)
    if pre_flight_error is not None:
        logger.warning(
            f"actor.submit pre-flight rejected {action_type}: {pre_flight_error}"
        )
        return pre_flight_error

    logger.debug(
        f"actor.submit: {action_type} — {str(payload['display_subject'])[:60]}"
    )
    try:
        result = await ctx.context.actor.submit(payload)
        return _render_result(result)
    except Exception as exc:
        logger.warning(f"actor.submit failed for {action_type}: {exc}")
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
# Host file / directory tools
# ---------------------------------------------------------------------------

@function_tool
async def read_host_file(
    ctx: RunContextWrapper[AgentContext],
    path: str,
    reason: str,
    offset: int = 0,
    limit: int = 500,
) -> str:
    """Read the contents of a file. Supports text files and PDFs.
    Returns up to `limit` lines starting at `offset` (0-based).
    Response includes total_lines and truncated flag — call again
    with a higher offset to read more."""
    return await _submit(ctx, _ReadHostFileAction(
        target=path, path=path, reason=reason, offset=offset, limit=limit,
    ))


@function_tool
async def write_host_file(
    ctx: RunContextWrapper[AgentContext],
    path: str,
    content: str,
    reason: str,
) -> str:
    """Write content to a file (create or overwrite)."""
    return await _submit(ctx, _WriteHostFileAction(
        target=path, path=path, content=content, reason=reason,
    ))


@function_tool
async def list_host_directory(
    ctx: RunContextWrapper[AgentContext],
    path: str,
    reason: str,
) -> str:
    """List files and subdirectories at the given path."""
    return await _submit(ctx, _ListHostDirectoryAction(
        target=path, path=path, reason=reason,
    ))


@function_tool
async def delete_host_file(
    ctx: RunContextWrapper[AgentContext],
    path: str,
    reason: str,
) -> str:
    """Delete a file or empty directory."""
    return await _submit(ctx, _DeleteHostFileAction(
        target=path, path=path, reason=reason,
    ))


# ---------------------------------------------------------------------------
# Terminal
# ---------------------------------------------------------------------------

@function_tool
async def run_command(ctx: RunContextWrapper[AgentContext], command: str, reason: str) -> str:
    """Execute a shell command and return its output."""
    return await _submit(ctx, _CommandAction(command=command, reason=reason))


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

@function_tool
async def send_email(ctx: RunContextWrapper[AgentContext], account_email: str, to: str, subject: str, body: str, reason: str) -> str:
    """Send an email. account_email identifies which configured email account to send from."""
    return await _submit(ctx, _EmailSendAction(account_email=account_email, to=to, subject=subject, body=body, reason=reason))


@function_tool
async def read_email(ctx: RunContextWrapper[AgentContext], account_email: str, reason: str, mailbox: str = "INBOX", limit: int = 10) -> str:
    """Read recent emails from a mailbox. account_email identifies which configured email account to read from."""
    return await _submit(ctx, _EmailReadAction(account_email=account_email, mailbox=mailbox, limit=limit, reason=reason))


@function_tool
async def search_email(ctx: RunContextWrapper[AgentContext], account_email: str, query: str, reason: str) -> str:
    """Search emails. Operators (implicitly ANDed): from:, to:, subject:,
    in:inbox/sent/trash, has:attachment, after:YYYY-MM-DD, before:YYYY-MM-DD,
    is:unread/read. Plain words do full-text search on subject, sender, body.
    OR/NOT/body:/parentheses are NOT supported."""
    return await _submit(ctx, _EmailSearchAction(account_email=account_email, query=query, reason=reason))


@function_tool
async def get_email(ctx: RunContextWrapper[AgentContext], rfc_message_id: str, reason: str, headers_only: bool = False) -> str:
    """Get a specific email by its RFC message ID (the angle-bracket ID from search/read
    results, e.g. '<CALyg3Ru...@mail.gmail.com>'). Do NOT use numeric IDs or fake or invent your own for rfc_message_id.
    Returns full body, metadata, and attachment list. Use headers_only=True to skip body fetch."""
    return await _submit(ctx, _EmailGetAction(
        rfc_message_id=rfc_message_id, headers_only=headers_only, reason=reason,
    ))


@function_tool
async def reply_email(ctx: RunContextWrapper[AgentContext], rfc_message_id: str, body: str, reason: str, reply_all: bool = False) -> str:
    """Reply to an email. rfc_message_id is the angle-bracket ID from search/read results
    (e.g. '<CALyg3Ru...@mail.gmail.com>'). Do NOT use numeric IDs or fake or invent your own for rfc_message_id. Set reply_all=True to reply to all recipients."""
    return await _submit(ctx, _EmailReplyAction(
        rfc_message_id=rfc_message_id, body=body, reply_all=reply_all,
        reason=reason,
    ))


@function_tool
async def forward_email(ctx: RunContextWrapper[AgentContext], rfc_message_id: str, to: str, reason: str, body: str = "") -> str:
    """Forward an email to the specified recipient. rfc_message_id is the angle-bracket ID
    from search/read results (e.g. '<CALyg3Ru...@mail.gmail.com>'). Do NOT use numeric IDs or fake or invent your own for rfc_message_id. Optionally add a body message."""
    return await _submit(ctx, _EmailForwardAction(
        rfc_message_id=rfc_message_id, to=to, body=body,
        reason=reason,
    ))


@function_tool
async def mark_read_email(ctx: RunContextWrapper[AgentContext], rfc_message_id: str, reason: str, read: bool = True) -> str:
    """Mark an email as read or unread. rfc_message_id is the angle-bracket ID from
    search/read results. Do NOT use numeric IDs or fake or invent your own for rfc_message_id. Set read=False to mark as unread."""
    return await _submit(ctx, _EmailMarkReadAction(
        rfc_message_id=rfc_message_id, read=read,
        reason=reason,
    ))


@function_tool
async def move_email(ctx: RunContextWrapper[AgentContext], rfc_message_id: str, to_folder: str, reason: str) -> str:
    """Move an email to a different folder (e.g. Archive, Trash). rfc_message_id is the
    angle-bracket ID from search/read results. Do NOT use numeric IDs or fake or invent your own for rfc_message_id."""
    return await _submit(ctx, _EmailMoveAction(
        rfc_message_id=rfc_message_id, to_folder=to_folder,
        reason=reason,
    ))


@function_tool
async def delete_email(ctx: RunContextWrapper[AgentContext], rfc_message_id: str, reason: str) -> str:
    """Permanently delete an email. rfc_message_id is the angle-bracket ID from
    search/read results (e.g. '<CALyg3Ru...@mail.gmail.com>'). Do NOT use numeric IDs or fake or invent your own for rfc_message_id."""
    return await _submit(ctx, _EmailDeleteAction(
        rfc_message_id=rfc_message_id, reason=reason,
    ))


@function_tool
async def download_attachment(ctx: RunContextWrapper[AgentContext], rfc_message_id: str, filename: str, reason: str) -> str:
    """Download an email attachment to disk. Returns the saved file path.
    rfc_message_id is the angle-bracket ID from search/read/get_email results
    (e.g. '<CALyg3Ru...@mail.gmail.com>'). filename must match exactly as listed
    in the get_email attachments array. Do NOT use numeric IDs or fake or invent your own for rfc_message_id."""
    return await _submit(ctx, _EmailDownloadAttachmentAction(
        rfc_message_id=rfc_message_id, filename=filename,
        reason=reason,
    ))


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

@function_tool
async def list_calendars(ctx: RunContextWrapper[AgentContext], reason: str) -> str:
    """List all available calendars on the device. Call this first to discover calendar names before listing or creating events."""
    return await _submit(ctx, _CalendarAction(action="LIST_CALENDARS", reason=reason))


@function_tool
async def list_events(ctx: RunContextWrapper[AgentContext], reason: str, calendar: str = "", start: str = "", end: str = "", limit: int = 20) -> str:
    """List upcoming calendar events. Leave calendar empty to search all calendars. Dates are ISO 8601 or natural language (e.g. 'today', 'tomorrow')."""
    return await _submit(ctx, _CalendarAction(action="LIST_EVENTS", calendar=calendar, start=start, end=end, limit=limit, reason=reason))


@function_tool
async def create_event(ctx: RunContextWrapper[AgentContext], title: str, start: str, reason: str, end: str = "", duration: int = 60, calendar: str = "", location: str = "", notes: str = "") -> str:
    """Create a calendar event. Provide end time OR duration in minutes (default 60). Leave calendar empty to use the default."""
    return await _submit(ctx, _CalendarAction(action="CREATE_EVENT", title=title, start=start, end=end, duration=duration, calendar=calendar, location=location, notes=notes, reason=reason))


@function_tool
async def update_event(ctx: RunContextWrapper[AgentContext], event_id: str, reason: str, title: str = "", start: str = "", end: str = "", location: str = "", notes: str = "", future_events: bool = False) -> str:
    """Update an existing calendar event by event_id.
    IMPORTANT: Always call list_events or search_events first to get the current event_id. Do NOT reuse event_ids from earlier create_event calls — they may become stale after sync."""
    return await _submit(ctx, _CalendarAction(action="UPDATE_EVENT", event_id=event_id, title=title, start=start, end=end, location=location, notes=notes, future_events=future_events, reason=reason))


@function_tool
async def delete_event(ctx: RunContextWrapper[AgentContext], reason: str, event_id: str = "", title: str = "", future_events: bool = False) -> str:
    """Delete a calendar event by event_id or title.
    IMPORTANT: Always call list_events or search_events first to get the current event_id. Do NOT reuse event_ids from earlier create_event calls — they may become stale after sync."""
    return await _submit(ctx, _CalendarAction(action="DELETE_EVENT", event_id=event_id, title=title, future_events=future_events, reason=reason))


@function_tool
async def search_events(ctx: RunContextWrapper[AgentContext], query: str, reason: str, start: str = "", end: str = "", limit: int = 50) -> str:
    """Search calendar events by text query across title, notes, and location."""
    return await _submit(ctx, _CalendarAction(action="SEARCH_EVENTS", query=query, start=start, end=end, limit=limit, reason=reason))


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

@function_tool
async def list_reminder_lists(ctx: RunContextWrapper[AgentContext], reason: str) -> str:
    """List all reminder lists on the device. Call this first to discover list names."""
    return await _submit(ctx, _ReminderAction(action="LIST_REMINDER_LISTS", reason=reason))


@function_tool
async def list_reminders(ctx: RunContextWrapper[AgentContext], reason: str, list_name: str = "", include_completed: bool = False, limit: int = 20) -> str:
    """List reminders. Leave list_name empty to list from all lists."""
    return await _submit(ctx, _ReminderAction(action="LIST_REMINDERS", list=list_name, include_completed=include_completed, limit=limit, reason=reason))


@function_tool
async def create_reminder(ctx: RunContextWrapper[AgentContext], title: str, reason: str, due_date: str = "", list_name: str = "", notes: str = "", priority: int = 0) -> str:
    """Create a reminder. Priority: 0=none, 1=high, 5=medium, 9=low."""
    return await _submit(ctx, _ReminderAction(action="CREATE_REMINDER", title=title, due_date=due_date, list=list_name, notes=notes, priority=priority, reason=reason))


@function_tool
async def complete_reminder(ctx: RunContextWrapper[AgentContext], reason: str, reminder_id: str = "", title: str = "", undo: bool = False) -> str:
    """Mark a reminder as complete (or undo completion). Use reminder_id or title."""
    return await _submit(ctx, _ReminderAction(action="COMPLETE_REMINDER", reminder_id=reminder_id, title=title, undo=undo, reason=reason))


@function_tool
async def update_reminder(ctx: RunContextWrapper[AgentContext], reminder_id: str, reason: str, title: str = "", notes: str = "", due_date: str = "", priority: int = 0) -> str:
    """Update an existing reminder by reminder_id."""
    return await _submit(ctx, _ReminderAction(action="UPDATE_REMINDER", reminder_id=reminder_id, title=title, notes=notes, due_date=due_date, priority=priority, reason=reason))


@function_tool
async def delete_reminder(ctx: RunContextWrapper[AgentContext], reminder_id: str, reason: str) -> str:
    """Delete a reminder by reminder_id."""
    return await _submit(ctx, _ReminderAction(action="DELETE_REMINDER", reminder_id=reminder_id, reason=reason))


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

@function_tool
async def search_contacts(ctx: RunContextWrapper[AgentContext], query: str, reason: str, limit: int = 20) -> str:
    """Search contacts by name."""
    return await _submit(ctx, _ContactAction(action="SEARCH_CONTACTS", query=query, limit=limit, reason=reason))


@function_tool
async def get_contact(ctx: RunContextWrapper[AgentContext], reason: str, contact_id: str = "", name: str = "") -> str:
    """Get a single contact by contact_id or name."""
    return await _submit(ctx, _ContactAction(action="GET_CONTACT", contact_id=contact_id, name=name, reason=reason))


@function_tool
async def add_contact(ctx: RunContextWrapper[AgentContext], reason: str, first_name: str = "", last_name: str = "", email: str = "", phone: str = "", organization: str = "", job_title: str = "", notes: str = "") -> str:
    """Add a new contact. At least first_name, last_name, or organization required."""
    return await _submit(ctx, _ContactAction(action="ADD_CONTACT", first_name=first_name, last_name=last_name, email=email, phone=phone, organization=organization, job_title=job_title, notes=notes, reason=reason))


@function_tool
async def update_contact(ctx: RunContextWrapper[AgentContext], contact_id: str, reason: str, first_name: str = "", last_name: str = "", email: str = "", phone: str = "", organization: str = "", job_title: str = "", nickname: str = "") -> str:
    """Update an existing contact by contact_id."""
    return await _submit(ctx, _ContactAction(action="UPDATE_CONTACT", contact_id=contact_id, first_name=first_name, last_name=last_name, email=email, phone=phone, organization=organization, job_title=job_title, nickname=nickname, reason=reason))


@function_tool
async def delete_contact(ctx: RunContextWrapper[AgentContext], contact_id: str, reason: str) -> str:
    """Delete a contact by contact_id."""
    return await _submit(ctx, _ContactAction(action="DELETE_CONTACT", contact_id=contact_id, reason=reason))


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

@function_tool
async def create_note(ctx: RunContextWrapper[AgentContext], title: str, body: str, reason: str) -> str:
    """Create a note in the default notes app."""
    return await _submit(ctx, _NoteAction(action="CREATE_NOTE", title=title, body=body, reason=reason))


@function_tool
async def list_notes(ctx: RunContextWrapper[AgentContext], folder: str, reason: str) -> str:
    """List notes in a folder."""
    return await _submit(ctx, _NoteAction(action="LIST_NOTES", folder=folder, reason=reason))


@function_tool
async def read_note(ctx: RunContextWrapper[AgentContext], title: str, reason: str) -> str:
    """Read the body of a specific note by title."""
    return await _submit(ctx, _NoteAction(action="READ_NOTE", title=title, reason=reason))


@function_tool
async def delete_note(ctx: RunContextWrapper[AgentContext], title: str, reason: str) -> str:
    """Delete a note by title."""
    return await _submit(ctx, _NoteAction(action="DELETE_NOTE", title=title, reason=reason))


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

@function_tool
async def send_message(ctx: RunContextWrapper[AgentContext], to: str, text: str, service: str, reason: str) -> str:
    """Send an iMessage or SMS.

    IMPORTANT: `to` must be an exact phone number or email address from a
    search_contacts result. Do NOT retype or reconstruct it from memory —
    copy the exact value character-for-character. Plain names are NOT accepted.

    Workflow when given only a name:
    1. Call search_contacts(query=<name>) to look up the contact.
    2. Use their correct `phone` field if present, otherwise use their correct `email` field
       (iMessage works with both phone numbers and email addresses registered with iMessage accounts or APPLE IDs).
    3. Pass the resolved value as `to` here.
    """
    return await _submit(ctx, _MessageAction(to=to, text=text, service=service, reason=reason))


@function_tool
async def read_messages(ctx: RunContextWrapper[AgentContext], reason: str, contact: str = "", limit: int = 10) -> str:
    """Read recent messages, optionally filtered by contact name or phone number."""
    return await _submit(ctx, _ReadMessagesAction(contact=contact, limit=limit, reason=reason))


# ---------------------------------------------------------------------------
# Browser
# ---------------------------------------------------------------------------

@function_tool
async def open_url(ctx: RunContextWrapper[AgentContext], url: str, reason: str) -> str:
    """Open a URL in the default browser."""
    return await _submit(ctx, _BrowserAction(action="OPEN_URL", url=url, reason=reason))



@function_tool
async def get_page_content(ctx: RunContextWrapper[AgentContext], url: str, reason: str) -> str:
    """Fetch a URL and return its full text content as clean markdown.

    Use this when the user asks to read, fetch, or show the content of a specific URL.
    The web_search hosted tool cannot return full page content — only this tool can.
    """
    return await _submit(ctx, _BrowserAction(action="GET_PAGE_CONTENT", url=url, reason=reason))


# ---------------------------------------------------------------------------
# System  (adapters: clipboard, spotlight, notifications)
# ---------------------------------------------------------------------------

@function_tool
async def get_clipboard(ctx: RunContextWrapper[AgentContext], reason: str) -> str:
    """Read the current clipboard contents."""
    return await _submit(ctx, _ClipboardAction(action="GET_CLIPBOARD", reason=reason))


@function_tool
async def set_clipboard(ctx: RunContextWrapper[AgentContext], content: str, reason: str) -> str:
    """Set the clipboard contents."""
    return await _submit(ctx, _ClipboardAction(action="SET_CLIPBOARD", content=content, reason=reason))


@function_tool
async def search_spotlight(ctx: RunContextWrapper[AgentContext], query: str, reason: str) -> str:
    """Search the local filesystem via Spotlight."""
    return await _submit(ctx, _SpotlightAction(query=query, reason=reason))


@function_tool
async def show_notification(ctx: RunContextWrapper[AgentContext], title: str, message: str, reason: str) -> str:
    """Show a macOS notification."""
    return await _submit(ctx, _NotificationAction(title=title, message=message, reason=reason))


# ---------------------------------------------------------------------------
# User IO
# ---------------------------------------------------------------------------

@function_tool
async def ask_user(ctx: RunContextWrapper[AgentContext], prompt: str, options: list[str], reason: str) -> str:
    """Ask the user a question with optional multiple-choice options."""
    return await _submit(ctx, _UserIOAction(prompt=prompt, options=options, reason=reason))


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------

@function_tool
async def get_system_info(ctx: RunContextWrapper[AgentContext], reason: str) -> str:
    """Get macOS system information: OS version, hostname, architecture, Python version."""
    return await _submit(ctx, _SystemAction(action="GET_SYSTEM_INFO", reason=reason))


@function_tool
async def set_volume(ctx: RunContextWrapper[AgentContext], level: int, reason: str) -> str:
    """Set the system audio output volume. Level is 0–100."""
    return await _submit(ctx, _SystemAction(action="SET_VOLUME", level=float(level), reason=reason))


@function_tool
async def get_volume(ctx: RunContextWrapper[AgentContext], reason: str) -> str:
    """Get the current system audio output volume (0–100)."""
    return await _submit(ctx, _SystemAction(action="GET_VOLUME", reason=reason))


@function_tool
async def toggle_mute(ctx: RunContextWrapper[AgentContext], reason: str) -> str:
    """Toggle system audio mute on/off."""
    return await _submit(ctx, _SystemAction(action="TOGGLE_MUTE", reason=reason))


@function_tool
async def get_mute(ctx: RunContextWrapper[AgentContext], reason: str) -> str:
    """Check whether system audio is currently muted."""
    return await _submit(ctx, _SystemAction(action="GET_MUTE", reason=reason))


@function_tool
async def set_brightness(ctx: RunContextWrapper[AgentContext], level: float, reason: str) -> str:
    """Set the display brightness. Level is 0.0 (off) to 1.0 (full). Example: 0.75 for 75%."""
    return await _submit(ctx, _SystemAction(action="SET_BRIGHTNESS", level=level, reason=reason))


@function_tool
async def get_brightness(ctx: RunContextWrapper[AgentContext], reason: str) -> str:
    """Get the current display brightness level (0.0–1.0)."""
    return await _submit(ctx, _SystemAction(action="GET_BRIGHTNESS", reason=reason))


@function_tool
async def toggle_dark_mode(ctx: RunContextWrapper[AgentContext], reason: str) -> str:
    """Toggle macOS dark/light appearance mode."""
    return await _submit(ctx, _SystemAction(action="TOGGLE_DARK_MODE", reason=reason))


@function_tool
async def get_dark_mode(ctx: RunContextWrapper[AgentContext], reason: str) -> str:
    """Check whether macOS dark mode is currently enabled."""
    return await _submit(ctx, _SystemAction(action="GET_DARK_MODE", reason=reason))


# ---------------------------------------------------------------------------
# Agent-only tools (no actor.submit)
# ---------------------------------------------------------------------------

@function_tool
async def memory_search(ctx: RunContextWrapper[AgentContext], query: str) -> str:
    """Search Jarvis memory for relevant facts, decisions, preferences, etc."""
    searcher = ctx.context.searcher
    if searcher.db is None:
        return "Memory index not yet available. Ask me again after a moment."
    try:
        results = await searcher.search(query)
        if not results:
            return "No relevant memory found."
        lines = []
        for r in results:
            lines.append(f"Source: {r.path}#{r.start_line}\n{r.text.strip()}\n")
        return "\n---\n".join(lines)
    except Exception as exc:
        logger.warning(f"memory_search failed: {exc}")
        return f"Memory search error: {exc}"


def _read_memory_lines(
    workspace_root: Path,
    path: str,
    start_line: int,
    end_line: int,
) -> str:
    """Read a 1-indexed, inclusive line range from a memory file.

    ``workspace_root`` MUST be an absolute, resolved path; callers are
    responsible for ``.expanduser().resolve()`` so this helper's
    traversal guard is deterministic.

    All failures return a human-readable ``"Error reading ..."`` string
    rather than raising — memory tooling is on the LLM hot path and the
    model should see the reason verbatim.  Kept as a plain function
    (not an ``@function_tool``) so unit tests can exercise path
    boundaries, symlink escapes, and line-slice edges without going
    through the agents SDK.
    """
    target = (workspace_root / path).resolve()

    try:
        target.relative_to(workspace_root)
    except ValueError:
        return f"Error reading {path}: path escapes Jarvis memory workspace"

    if not target.exists():
        return f"Error reading {path}: file does not exist"
    if not target.is_file():
        return f"Error reading {path}: not a file"

    try:
        content = target.read_text(encoding="utf-8")
    except Exception as exc:
        return f"Error reading {path}: {exc}"

    lines = content.splitlines()
    selected = lines[max(0, start_line - 1):end_line]
    return "\n".join(selected)


@function_tool
async def memory_get(ctx: RunContextWrapper[AgentContext], path: str, start_line: int, end_line: int) -> str:
    """Read specific lines from a memory file."""
    workspace_root = (ctx.context.config.workspace_dir / "workspace").expanduser().resolve()
    result = _read_memory_lines(workspace_root, path, start_line, end_line)
    logger.debug(f"memory_get({path!r}, {start_line}, {end_line}) → {len(result.splitlines())} lines")
    return result


@function_tool
async def spawn_agent(ctx: RunContextWrapper[AgentContext], task: str, model: str | None = None) -> str:
    """Spawn a focused sub-agent for a self-contained task.

    Sub-agents share the same tools and Actor but have minimal context.
    They cannot spawn further sub-agents (single-level nesting only).
    """
    import uuid
    from agents import Agent, Runner

    # Guard: prevent sub-agents from spawning further sub-agents.
    if ctx.context.is_sub_agent:
        return "Sub-agents cannot spawn further sub-agents."

    config = ctx.context.config
    sub_model = model or config.sub_agent_model

    sub_prompt = (
        f"You are a focused sub-agent spawned by Jarvis to handle a specific task.\n"
        f"Your task: {task}\n\n"
        f"Use the available tools as needed. Be concise. Report results clearly.\n"
        f"You cannot spawn other sub-agents.\n"
    )

    # Build a sub-context that marks is_sub_agent=True.
    from jarvis.types import AgentContext
    sub_ctx = AgentContext(
        actor=ctx.context.actor,
        config=ctx.context.config,
        searcher=ctx.context.searcher,
        is_sub_agent=True,
    )

    sub_agent = Agent(
        name=f"jarvis-sub-{str(uuid.uuid4())[:6]}",
        instructions=sub_prompt,
        tools=ALL_TOOLS,
        model=sub_model,
    )

    logger.debug(f"Spawning sub-agent for task: {task[:60]!r} (model={sub_model})")

    try:
        result = await Runner.run(sub_agent, task, context=sub_ctx)
        return result.final_output
    except Exception as exc:
        logger.error(f"Sub-agent failed: {exc}")
        return f"Sub-agent error: {exc}"


# ---------------------------------------------------------------------------
# Tool registry – single list for the Agent constructor
# ---------------------------------------------------------------------------

ALL_TOOLS: list[Any] = [
    read_host_file,
    write_host_file,
    list_host_directory,
    delete_host_file,
    run_command,
    send_email,
    read_email,
    search_email,
    get_email,
    reply_email,
    forward_email,
    mark_read_email,
    move_email,
    delete_email,
    download_attachment,
    # Calendar
    list_calendars,
    list_events,
    create_event,
    update_event,
    delete_event,
    search_events,
    # Reminders
    list_reminder_lists,
    list_reminders,
    create_reminder,
    complete_reminder,
    update_reminder,
    delete_reminder,
    # Contacts
    search_contacts,
    get_contact,
    add_contact,
    update_contact,
    delete_contact,
    # Notes
    create_note,
    list_notes,
    read_note,
    delete_note,
    # Messages
    send_message,
    read_messages,
    open_url,
    get_page_content,
    get_clipboard,
    set_clipboard,
    search_spotlight,
    show_notification,
    ask_user,
    # System control
    get_system_info,
    set_volume,
    get_volume,
    toggle_mute,
    get_mute,
    set_brightness,
    get_brightness,
    toggle_dark_mode,
    get_dark_mode,
    memory_search,
    memory_get,
    spawn_agent,
    # Hosted tools (Responses API only)
    WebSearchTool(),
]
