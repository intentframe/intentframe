# The macOS Platform Server (Swift)

> The native bridge that lets IntentFrame's executor reach Apple's frameworks — Calendar, Reminders, Contacts, Notes, iMessage, Notifications, and more — through a single local socket.

The platform server is a small Swift binary that runs as a background `.app` bundle on macOS. It exposes Apple's native frameworks (EventKit, Contacts, UserNotifications, AppleScript bridges) over a Unix domain socket as JSON-over-HTTP. The executor's macOS adapters call it for anything that requires Apple framework access.

This is what gives IntentFrame on macOS the same first-class access to Calendar, Contacts, and iMessage that Apple's own apps have — without giving the agent direct access.

For implementation details (Swift package layout, build steps, full route reference), see [`../macos-appkit-server/README.md`](../macos-appkit-server/README.md).

---

## Why a separate Swift process

There are three reasons IntentFrame's macOS native integration lives in its own process, written in Swift, instead of in the Python executor.

**1. The frameworks are Swift/Objective-C only.** EventKit, Contacts.framework, UserNotifications, AppleScript — these have no usable Python bindings. Any Python integration would be wrapping subprocess calls or PyObjC, both of which are slower and more brittle than a native Swift process.

**2. TCC permissions are per-binary.** macOS's permission system (Transparency, Consent, and Control) tracks which executable is asking for Calendar / Contacts / etc. access, not which user. If permissions belonged to the Python interpreter, every venv rebuild or Python upgrade would force the user to re-grant permissions. Pinning permissions to a stable code-signed Swift binary (`IntentFrame Dev`) means TCC grants persist across IntentFrame upgrades.

**3. Process isolation.** The platform server is the only IntentFrame process that holds Apple framework handles. If something goes wrong with EventKit (which has a history of CPU-burning bugs), only the platform server is affected — the executor, pipeline, and Guardian are insulated.

---

## What it exposes

| Service | Apple framework | Capabilities |
|---|---|---|
| **Calendar** | EventKit | Create, list, search, update, delete events and calendars |
| **Reminders** | EventKit | Create, list, complete, update, delete reminders and lists |
| **Contacts** | Contacts.framework | Search, get, add, update, delete contacts |
| **Notes** | SQLite + NSAppleScript | List, read, create, delete notes |
| **Messages** | SQLite + NSAppleScript + Madrid (typedstream) | Send messages, read conversation history (incl. macOS Tahoe `attributedBody`) |
| **Mail** | NSAppleScript | Send / read / search via Mail.app (note: the executor uses [EDI](email-sync.md) instead by default) |
| **Mail Corpus** | NSAppleScript | List mailboxes, fetch headers and bodies for external consumers |
| **Notifications** | UserNotifications | Show rich branded notifications |
| **User I/O** | AppKit (NSAlert) | Text input, confirmation, option selection, info dialogs |
| **System** | DisplayServices + NSAppleScript | Display brightness, dark mode toggle |

Each service is dispatched through a single `ServiceDispatcher.swift` that maps `adapter + action` to the right Swift implementation.

---

## How it fits into IntentFrame

```
Agent's intent: CREATE_EVENT
    │
    ▼
intentframe-core pipeline (validates)
    │
    ▼
executor (gateway) → CalendarAdapter (Python)
    │
    │  HTTP POST over UDS
    │  ~/.intentframe/run/platform.sock
    │
    ▼
macOS Platform Server (Swift)
    │
    ▼
ServiceDispatcher → CalendarService → EventKit → real calendar
```

The executor's Python `CalendarAdapter` is a thin wrapper: it constructs a JSON request and forwards it to the platform server. The platform server is what actually talks to EventKit. This keeps the executor's Python codebase free of macOS-specific Swift bindings.

---

## TCC permissions

When the platform server first launches, macOS shows permission prompts for any framework that requires user consent — Calendar, Reminders, Contacts, Notifications. The user grants or denies each one in the standard macOS dialog.

The server's manifest (`Resources/Info.plist`) declares the required usage descriptions, so the OS shows a meaningful explanation in the prompt. Once granted, the permission persists across server restarts as long as the binary's code signature is stable.

This is why the setup script enforces a stable signing identity:

```bash
bash macos-appkit-server/Scripts/setup-signing.sh
```

It creates a local code-signing certificate named `IntentFrame Dev`. Every build of the platform server is signed with this identity, so macOS sees the same "app" across rebuilds and TCC permissions stick.

You can inspect the current grant state via the server's health endpoint:

```bash
curl --unix-socket ~/.intentframe/run/platform.sock http://localhost/health
```

```json
{
  "status": "ok",
  "service": "platform-server",
  "permissions": {
    "calendar":      { "granted": true,  "hint": null },
    "reminders":     { "granted": true,  "hint": null },
    "contacts":      { "granted": false, "hint": "Grant in System Settings > Privacy & Security > Contacts" },
    "notifications": { "granted": true,  "hint": null }
  }
}
```

The executor reads this at startup so it can refuse a `CREATE_EVENT` intent with a clear "Calendar permission not granted" error instead of silently failing.

---

## Process model

The platform server is launched by the gateway in **Step 5** of startup, before the supervisor — so the executor's adapters can reach it during their own startup permission checks. See [processes.md § Process tree](processes.md).

| Property | Value |
|---|---|
| Process name | `macos-appkit-server` |
| Source | `macos-appkit-server/` |
| Binary form | `.app` bundle (`LSUIElement = true` — no Dock icon, no menu bar) |
| Socket | `~/.intentframe/run/platform.sock` (override with `PLATFORM_SOCKET`) |
| PID file | `~/.intentframe/run/platform-server.pid` |
| Logs | `~/.intentframe/logs/platform-server.log` |
| Lifecycle | Started by gateway via `open <bundle>.app`; gracefully stopped via HTTP `POST /shutdown` |

Why `open` instead of executing the binary directly: launching via `open` ensures macOS treats the process as a user-launched app, which is required for TCC permission prompts to appear and grants to apply. Direct binary execution may silently deny TCC-gated APIs.

---

## Why the executor uses EDI for email instead

Even though the platform server has a Mail service (via NSAppleScript bridges to Mail.app), the executor's `MailAdapter` uses [EDI](email-sync.md) by default. Reasons:

- **EDI is faster.** Local SQLite + FTS5 search returns in sub-millisecond; AppleScript queries to Mail.app can take seconds.
- **EDI is daemon-driven.** It maintains a long-lived IMAP IDLE connection for real-time INBOX updates. Mail.app's AppleScript bridge has no equivalent push channel.
- **EDI works headless.** Mail.app may not be running; AppleScript control can't reach it in that case. EDI runs as a daemon regardless.
- **EDI works cross-account.** It supports any IMAP/SMTP provider; Mail.app's AppleScript model is tied to whatever Mail.app is configured with.

The platform server's Mail service is retained for niche cases that genuinely need Mail.app-specific behavior (e.g. operating on Mail.app rules or signatures). For everything else, the executor's `MailAdapter` calls into EDI.

---

## Madrid: the typedstream parser

The Messages service uses Apple's `chat.db` SQLite store directly. On macOS 26 Tahoe, Apple stopped populating the `message.text` column for newly-received iMessages — the actual text now lives only in the `attributedBody` blob, which is encoded in Apple's proprietary `NSArchiver` typedstream format.

To read iMessage history on Tahoe, the platform server depends on [Madrid](https://github.com/loopwork-ai/Madrid), a pure-Swift parser for that format. Without Madrid, `READ_MESSAGES` would return empty bodies on Tahoe.

See [`../macos-appkit-server/docs/imessage-attributedbody.md`](../macos-appkit-server/docs/imessage-attributedbody.md) for the full backstory and verification commands.

---

## Quick answers

| Question | Answer |
|---|---|
| Is the platform server required? | Only on macOS, only if you want native Calendar / Contacts / Reminders / iMessage access. The IntentFrame core framework runs without it on Linux; those adapters report "unavailable". |
| Does it talk to the network? | No. It's local-only. (Apple's own iMessage / iCloud sync happens in OS-level processes, not in this server.) |
| Does it have credentials? | No. TCC handles all permissions. |
| What if I deny a TCC prompt? | The corresponding adapter reports the action as unavailable, with a hint to grant in System Settings. |
| Why a `.app` bundle instead of just a binary? | TCC permissions are pinned to the bundle's code signature. The bundle stays stable across rebuilds; the binary inside it can change. |
| What if I rebuild the server? | If the signing identity stays the same (`IntentFrame Dev`), TCC permissions persist. If you sign with a different identity, you'll get fresh prompts. |
| Will this work on Linux? | No — the server is Swift + Apple frameworks. On Linux the corresponding adapters are absent. Future Linux equivalents would need to bridge GNOME / KDE / etc. |
| What's the upgrade story for macOS Tahoe iMessage? | Madrid handles it. See `imessage-attributedbody.md` for the technical details. |

---

## Limitations

- **macOS only.** Apple framework access has no portable equivalent.
- **AppleScript dependence for Mail and Notes.** The Notes and Mail services rely on AppleScript bridges, which are slower and less reliable than direct framework access. There's no public Apple framework for either Notes or Mail; the AppleScript bridge is the only option.
- **Notes "hides Notes.app after writes" workaround.** Creating a Note via AppleScript causes Notes.app to surface; the server hides it after the write completes. This is a UX artifact of AppleScript, not a server bug.
- **No multi-user TCC story.** Permissions are per-user-per-binary. Running IntentFrame for multiple users on one machine would mean multiple TCC grant flows.

---

## Related documents

- [`../macos-appkit-server/README.md`](../macos-appkit-server/README.md) — Implementation reference: build, full API, dependency details
- [`../macos-appkit-server/docs/imessage-attributedbody.md`](../macos-appkit-server/docs/imessage-attributedbody.md) — Tahoe iMessage attributedBody decoding
- [processes.md](processes.md) — How the platform server fits into the process tree
- [email-sync.md](email-sync.md) — Why the executor uses EDI for email instead of the platform server's Mail service
- [executor.md](executor.md) — How adapters use the platform server
