---
name: apple-reminders
description: Manage Apple Reminders
version: "2.0"
metadata:
  os: ["darwin"]
---

# Apple Reminders

Manage reminder lists and reminders on this Mac.

## Available Tools

- `list_reminder_lists` — List all reminder lists. **Call this first** if you don't know the list name.
- `list_reminders` — List reminders from a specific list or all lists. Can include completed reminders.
- `create_reminder` — Create a reminder with optional due date, notes, and priority (1=high, 5=medium, 9=low).
- `complete_reminder` — Mark a reminder as done (or undo with `undo=true`).
- `update_reminder` — Update a reminder by `reminder_id`.
- `delete_reminder` — Delete a reminder by `reminder_id`.

## Important

- Always call `list_reminder_lists` first if you need to know which lists exist.
- Never guess list names — discover them.
- Get `reminder_id` from `list_reminders` before updating, completing, or deleting.
- Always use the dedicated tools above for reminder operations.
