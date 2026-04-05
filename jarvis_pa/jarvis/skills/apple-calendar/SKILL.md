---
name: apple-calendar
description: Manage Apple Calendar events
version: "2.0"
metadata:
  os: ["darwin"]
---

# Apple Calendar

Manage calendars, events, and scheduling on this Mac.

## Available Tools

- `list_calendars` — List all calendars on the device. **Call this first** if you don't know the calendar name.
- `list_events` — List upcoming events. Leave `calendar` empty for all calendars, or specify a name from `list_calendars`.
- `create_event` — Create a new event. Provide `start` and either `end` or `duration` (minutes). Leave `calendar` empty for the default.
- `update_event` — Update an event by `event_id` (get IDs from `list_events` or `search_events`).
- `delete_event` — Delete an event by `event_id` or `title`.
- `search_events` — Search events by text across title, notes, and location.

## Important

- Always call `list_calendars` first if you need to know which calendars exist.
- Never guess calendar names — discover them.
- Dates accept ISO 8601 (`2026-03-04T10:00:00`) or natural language (`today`, `tomorrow`, `next week`).
- Before calling `update_event` or `delete_event`, always fetch a fresh `event_id` via `list_events` or `search_events`. Do not reuse an `event_id` returned by an earlier `create_event` — IDs can change after calendar sync.
- Always use the dedicated tools above for calendar operations.
