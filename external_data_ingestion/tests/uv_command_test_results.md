Every command works correctly. Here's the full summary:

| # | Command | Result |
|---|---------|--------|
| 1 | `start` (no config at all) | "No config found... Add an account first" — exit 1 |
| 2 | `status` (no config) | Workspace + "stopped" + 0 accounts — exit 0 |
| 3 | `list` (no config) | "No accounts configured." — exit 0 |
| 4 | `add testuser@gmail.com` | IMAP login validated, config.yaml created, account saved — exit 0 |
| 5 | `list` | Shows `testuser@gmail.com` |
| 6 | `status` (before start) | Daemon stopped, 1 account listed |
| 7 | `start` | Daemon started, initial sync ran, IDLE spawned |
| 8 | `status` (while running) | "running (PID 83915)" |
| 9 | `start` again | "Daemon already running (PID 83915)" — exit 1 |
| 10 | `stop` | SIGTERM sent, polled, "Daemon stopped." — exit 0 |
| 11 | `status` (after stop) | "stopped", PID file cleaned up |
| 12 | `stop` (already stopped) | "Daemon is not running." — exit 0 |
| 13 | `add` (duplicate) | Idempotent upsert — exit 0 |
| 14 | `remove` | Account removed, list shows empty |
| 15 | `remove` (nonexistent) | "not found in config" — exit 1 |
| 16 | `start` (config exists, 0 accounts) | "No accounts in config... Add one with:" — exit 1 |