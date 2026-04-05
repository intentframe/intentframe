# macOS AppKit Server

A headless macOS service that exposes native Apple frameworks over a local Unix domain socket. Clients send JSON requests; the server dispatches them to the appropriate native service and returns structured JSON responses.

Runs as an `.app` bundle with `LSUIElement = true` (no Dock icon, no menu bar). Designed to be a long-running background process.

## What it does

| Service | Frameworks | Capabilities |
|---|---|---|
| **Calendar** | EventKit | Create, list, search, update, delete events and calendars |
| **Reminders** | EventKit | Create, list, complete, update, delete reminders and lists |
| **Contacts** | Contacts.framework | Search, get, add, update, delete contacts |
| **Notes** | SQLite + NSAppleScript | List, read, create, delete notes (hides Notes.app after writes) |
| **Messages** | SQLite + NSAppleScript | Send messages, read conversation history |
| **Mail** | NSAppleScript | Send, read, search email via Mail.app (executor uses EDI instead; retained for Mail.app-specific use) |
| **Mail Corpus** | NSAppleScript | List mailboxes, fetch headers and bodies for external consumers |
| **Notifications** | UserNotifications | Show rich branded notifications |
| **User I/O** | AppKit (NSAlert) | Text input, confirmation, option selection, and informational dialogs |
| **System** | DisplayServices + NSAppleScript | Display brightness, dark mode toggle |

## Requirements

- macOS 14 (Sonoma) or later
- Swift 5.9+
- Xcode Command Line Tools (`xcode-select --install`)

## Project structure

```
macos-appkit-server/
  Package.swift              Swift package manifest
  Resources/
    Info.plist               App bundle metadata & TCC usage descriptions
  Scripts/
    bundle.sh                Build + bundle helper
  Sources/
    App/
      entrypoint.swift       Main entry — socket setup, logging, TCC requests
    Routes/
      routes.swift           HTTP route registration (health, execute, rollback)
    Models/
      PlatformRequest.swift  Inbound JSON models (ExecuteRequest, RollbackRequest)
      PlatformResponse.swift Outbound JSON models (ExecuteResponse, PermissionStatus)
    Services/
      ServiceDispatcher.swift  Central router — maps adapter name to service
      CalendarService.swift
      RemindersService.swift
      ContactsService.swift
      NotesService.swift
      MessagesService.swift
      MailService.swift
      MailCorpusService.swift
      NotificationsService.swift
      UserIOService.swift
      SystemService.swift
    Shared/
      Errors.swift           PlatformError enum + ExecuteResponse convenience methods
      DateParsing.swift      Natural language & ISO 8601 date parsing
      RecurrenceHelpers.swift  Calendar recurrence rule helpers
      MailScriptRunner.swift   AppleScript helpers for Mail.app (runOsascript, escaping, parsing)
```

## Build

```bash
cd macos-appkit-server

# Debug build (faster compile, slower runtime)
swift build

# Release build
swift build -c release
```

## Create the .app bundle

The bundle script compiles a release build and wraps the binary with `Info.plist` into a proper `.app`:

```bash
bash Scripts/bundle.sh
```

Output: `.build/release/macos-appkit-server.app`

## Run

### Option A — Run the binary directly

```bash
# Debug
swift run

# Release (after swift build -c release)
.build/release/macos-appkit-server
```

### Option B — Launch the .app bundle

```bash
open .build/release/macos-appkit-server.app
```

Launching via `open` is required if you need macOS to show TCC permission prompts (Calendars, Reminders, Contacts, Notifications). Direct binary execution may silently deny TCC-gated APIs.

### Socket location

By default the server listens on:

```
~/.intentframe/run/platform.sock
```

Override with the `PLATFORM_SOCKET` environment variable:

```bash
PLATFORM_SOCKET=/tmp/my-platform.sock swift run
```

### PID file

The server writes its PID to:

```
~/.intentframe/run/platform-server.pid
```

This is used by the gateway to detect whether the server is already running and for orphan cleanup on shutdown.

### Logs

Stdout/stderr is mirrored to:

```
~/.intentframe/logs/platform-server.log
```

## API

All communication is JSON over HTTP on the Unix domain socket.

### `GET /health`

Returns server status and TCC permission state.

```json
{
  "status": "ok",
  "service": "platform-server",
  "permissions": {
    "calendar":      { "granted": true, "hint": null },
    "reminders":     { "granted": true, "hint": null },
    "contacts":      { "granted": false, "hint": "Grant in System Settings > Privacy & Security > Contacts" },
    "notifications": { "granted": true, "hint": null }
  }
}
```

### `GET /permissions`

Returns just the permissions object (same shape as `health.permissions`).

### `POST /execute`

Execute an action on a service.

```json
{
  "adapter": "calendar",
  "action": "LIST_EVENTS",
  "params": {
    "start": "today",
    "end": "next friday",
    "limit": 10
  }
}
```

**Response (success):**

```json
{
  "success": true,
  "data": { "events": [...], "count": 3 },
  "rollback_available": false,
  "rollback_id": null
}
```

**Response (error):**

```json
{
  "success": false,
  "error": "Calendar access not granted.",
  "error_code": "access_denied"
}
```

### `POST /rollback`

Undo a previously executed action (if `rollback_available` was `true`).

```json
{
  "adapter": "calendar",
  "rollback_id": "evt:ABC123"
}
```

### `POST /shutdown`

Gracefully shut down the server. Returns immediately; the server exits after a short delay.

```json
{"status": "shutting_down"}
```

Called by the gateway during its own shutdown sequence. The PID file is removed on clean exit.

## Empty-string parameter handling

Services treat empty strings in optional filter parameters the same as absent keys. For example, `LIST_EVENTS` with `"calendar": ""` lists events from all calendars (same as omitting `calendar` entirely). `LIST_REMINDERS` with `"list": ""` lists from all reminder lists. `CREATE_REMINDER` with `"list": ""` uses the default list.

Required parameters (e.g. `title` for `CREATE_EVENT`, `reminder_id` for `UPDATE_REMINDER`) reject empty strings as well as absent keys — both produce an `invalidInput` error.

**Current coverage:**

| Service / action | Empty-string behaviour | Status |
|---|---|---|
| `CalendarService.listEvents` — `calendar` | Treated as "all calendars" | Fixed |
| `CalendarService.createEvent` — `title` | Rejected as invalid input | Fixed |
| `RemindersService.listReminders` — `list` | Treated as "all lists" | Fixed |
| `RemindersService.createReminder` — `list` | Falls back to default "Reminders" list | Fixed |
| `RemindersService.createReminder` — `title` | Rejected as invalid input | Fixed |
| `NotesService.createNote` / `deleteNote` / `readNote` — `title` | Rejected as invalid input | Fixed |
| All other optional string params | May still be treated as literal values | Not yet fixed |

Callers should prefer omitting optional parameters rather than sending empty strings until full coverage is in place.

## Adapter & action reference

The `adapter` field routes to a service. The `action` field selects the operation within that service.

| Adapter | Actions |
|---|---|
| `calendar` | `LIST_CALENDARS`, `LIST_EVENTS`, `SEARCH_EVENTS`, `CREATE_EVENT`, `UPDATE_EVENT`, `DELETE_EVENT` |
| `reminders` | `LIST_REMINDER_LISTS`, `LIST_REMINDERS`, `CREATE_REMINDER`, `UPDATE_REMINDER`, `COMPLETE_REMINDER`, `DELETE_REMINDER` |
| `contacts` | `SEARCH_CONTACTS`, `GET_CONTACT`, `ADD_CONTACT`, `UPDATE_CONTACT`, `DELETE_CONTACT` |
| `notes` | `LIST_NOTES`, `READ_NOTE`, `CREATE_NOTE`, `DELETE_NOTE` |
| `messages` | `SEND_MESSAGE`, `READ_MESSAGES` |
| `mail` | `SEND_EMAIL`, `READ_EMAIL`, `SEARCH_EMAIL` (executor uses EDI `EmailClient` directly; this route is retained for Mail.app-specific clients) |
| `mail_corpus` | `LIST_MAILBOXES`, `GET_HEADERS`, `GET_BODY` |
| `notifications` | `SHOW_NOTIFICATION` |
| `user_io` | `ASK_USER`, `SHOW_MESSAGE`, `GET_CONFIRMATION`, `SHOW_OPTIONS` |
| `system` | `SET_BRIGHTNESS`, `GET_BRIGHTNESS`, `TOGGLE_DARK_MODE`, `GET_DARK_MODE` |

## TCC permissions

On first launch the server requests access to Calendars, Reminders, Contacts, and Notifications. macOS will show permission prompts. If denied, the corresponding service returns `access_denied` errors with a hint to grant access in System Settings.

Notes and Messages use SQLite reads which require **Full Disk Access** (System Settings > Privacy & Security > Full Disk Access) for the app or terminal running the server.

Mail and Mail Corpus use AppleScript to control Mail.app. Mail.app must be running (or will be launched). On first use, macOS may prompt for **Automation** permission (System Settings > Privacy & Security > Automation) to allow the server to control Mail.app. Note: the executor's `MailAdapter` now uses the EDI `EmailClient` (IMAP/SMTP) for all email operations and does not route through this server. The Mail service here is retained for Mail.app-specific integrations (e.g. bulk mail corpus export).

System brightness (DisplayServices) and dark mode (System Events AppleScript) require **Accessibility** permission if launched as an `.app` bundle.

## License

See the root `LICENSE` file.
