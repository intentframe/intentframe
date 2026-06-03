# Gateway Runtime Monitoring

This document explains how to inspect the running `intentframe-gateway-cli` stack on macOS, including:

- the gateway process tree
- CPU and memory usage for the full runtime
- service logs from both the CLI and the filesystem
- how EDI behaves during startup, backfill, and steady-state idle

The commands below are intended for local development and debugging.

## What the CLI Starts

When you run:

```bash
uv run intentframe-gateway-cli
```

the CLI starts the gateway if it is not already running, waits for it to become healthy, and then connects to it.

At runtime, the gateway is the root Python process for most of the stack:

```text
gateway
├── credential-vault
├── edi
├── jarvis
├── telegram
└── supervisor
    ├── policy-registry
    ├── resource-registry
    ├── executor
    └── intentframe-server
```

On macOS, `platform-server` is launched separately via `open` so it may not appear in the same process group as the Python children.

## Runtime Directories

Important runtime paths:

- PID files: `~/.intentframe/run`
- Unix sockets: `~/.intentframe/run`
- Logs: `~/.intentframe/logs`

Useful PID files:

- `~/.intentframe/run/gateway.pid`
- `~/.intentframe/run/supervisor.pid`
- `~/.intentframe/run/platform-server.pid`

## Check the Process Tree

Start by reading the gateway PID:

```bash
cat ~/.intentframe/run/gateway.pid
```

If you have `pstree` installed:

```bash
pstree -p $(cat ~/.intentframe/run/gateway.pid)
```

If not, inspect the gateway process group instead:

```bash
PGID=$(ps -o pgid= -p $(cat ~/.intentframe/run/gateway.pid) | tr -d ' ')
echo "Process group: $PGID"
ps -o pid,ppid,pgid,%cpu,%mem,rss,vsz,stat,command -ax | awk -v g="$PGID" '$3==g'
```

That gives you the gateway and all Python descendants in the same process group.

To inspect the macOS platform server separately:

```bash
ps -p $(cat ~/.intentframe/run/platform-server.pid) -o pid,ppid,%cpu,%mem,rss,command
```

## Check Resource Usage

For a one-shot snapshot of CPU and RSS for the gateway stack:

```bash
PGID=$(ps -o pgid= -p $(cat ~/.intentframe/run/gateway.pid) | tr -d ' ')
ps -o pid,pgid,command,%cpu,rss -ax | awk -v g="$PGID" 'NR==1 || $2==g' | sort -k5 -rn
```

Notes:

- `rss` is reported in KB
- divide RSS by `1024` to approximate MB
- this is usually the fastest way to see which child is heavy

For live monitoring on macOS with `top`, build repeated `-pid` flags:

```bash
PGID=$(ps -o pgid= -p $(cat ~/.intentframe/run/gateway.pid) | tr -d ' ')
PIDS=$(ps -o pid= -ax | while read p; do
  pg=$(ps -o pgid= -p "$p" 2>/dev/null | tr -d ' ')
  [ "$pg" = "$PGID" ] && printf -- "-pid %s " "$p"
done)
top -l 0 -s 2 -stats pid,command,cpu,mem,rss $PIDS
```

If you use `htop`, tree view is often easier:

```bash
htop --filter intentframe
```

## Cursor/VSCode Terminal vs Mac Terminal

The process inspection commands are the same in both places.

Practical differences:

- Cursor/VSCode terminal is fine for `ps`, `tail`, and quick checks
- Mac Terminal is usually better for long-running `top` or `htop` sessions
- if output wraps heavily, use a wider Mac Terminal window for tree and log views

## Inspect Service Health in the CLI

Inside the running REPL:

```text
intentframe> status
intentframe> health
```

`status` shows the known services and whether each one is healthy.

## Inspect Logs from the CLI

Inside the REPL, use:

```text
intentframe> logs edi
intentframe> logs jarvis
intentframe> logs gateway
intentframe> logs supervisor
intentframe> logs telegram
intentframe> logs executor
```

The command shape is:

```text
logs <service> [lines]
```

Behavior:

- CLI default: `50` lines
- gateway API default: `100` lines
- in practice the CLI sends `50` unless you specify another value

Examples:

```text
intentframe> logs edi 200
intentframe> logs jarvis 100
```

The current CLI exposes a snapshot log command, not a live follow mode.

## Tail Logs Directly

For live monitoring, tail the log files directly:

```bash
tail -f ~/.intentframe/logs/edi.log
tail -f ~/.intentframe/logs/jarvis.log
tail -f ~/.intentframe/logs/gateway.log
```

To watch multiple services at once:

```bash
tail -f ~/.intentframe/logs/*.log
```

To focus on EDI startup and sync progress:

```bash
tail -f ~/.intentframe/logs/edi.log | grep -E 'priority|backfill|integrity|sync_|upgrade_|error'
```

Common log files:

- `gateway.log`
- `credential-vault.log`
- `edi.log`
- `jarvis.log`
- `telegram.log`
- `supervisor.log`
- `policy-registry.log`
- `resource-registry.log`
- `executor.log`
- `intentframe-server.log`
- `platform-server.log`

## EDI Lifecycle: Startup vs Idle

EDI does not become "idle" immediately after the gateway turns healthy.

On startup, EDI runs in phases:

1. Priority sync
2. Backfill
3. Deferred periodic sync
4. Ongoing IMAP IDLE + periodic sync loop

### 1. Priority sync

This happens first and is part of startup. EDI fetches recent full content for the priority folders, especially inbox and sent mail.

Look for:

- `priority_sync_done`

### 2. Backfill

After the priority pass, EDI starts a one-shot background backfill across the rest of the mailbox.

Look for:

- `backfill_start`
- `upgrade_progress`
- `backfill_integrity_ok`
- `backfill_done`

### 3. Deferred periodic sync

Once backfill is complete, EDI transitions into the regular periodic sync loop.

Look for:

- `periodic_sync_done`
- `periodic_integrity_ok`

### 4. Idle steady state

After the first backfill is done, true idle behavior should look like:

- EDI CPU near `0.0%` most of the time
- brief activity during periodic sync
- brief activity when IMAP IDLE receives new mail
- memory remains elevated compared to tiny services, which is normal for a long-lived Python daemon with mailbox state loaded

## How to Tell EDI Is Done

The clearest marker is:

```text
backfill_done
```

Once that appears, EDI should settle into:

- near-zero CPU at rest
- one periodic sync roughly every 5 minutes
- integrity checks after those syncs

If you still see sustained CPU after `backfill_done`, inspect the current tail of `edi.log` and confirm whether it is:

- processing a new batch of messages
- inside a periodic sync
- repeatedly retrying due to an IMAP or DB error

## Typical Local Interpretation

A healthy local run usually looks like this:

- gateway healthy in the CLI
- all services `ok` in `status`
- EDI temporarily heavier during first startup
- Jarvis among the largest RSS consumers even when idle
- total memory footprint dominated by Python service count rather than one tiny executable

During a first run with mailbox backfill, EDI may be one of the top CPU and memory consumers. After backfill completes, CPU should drop sharply even if RSS remains comparatively high.

## Recommended Workflow

For day-to-day debugging, a good setup is:

1. Run `uv run intentframe-gateway-cli`
2. In the REPL, use `status` and `logs edi`
3. In a second terminal, run `tail -f ~/.intentframe/logs/edi.log`
4. In a third terminal, capture a one-shot process-group snapshot with `ps`

That combination gives you:

- system health
- service-specific logs
- resource usage for the entire gateway tree

## Troubleshooting

If `status` says a service is healthy but you do not see it in the gateway process group:

- check whether it is `platform-server`, which may be outside the gateway PGID on macOS
- confirm its PID via `~/.intentframe/run/platform-server.pid`

If `logs <service>` shows too little context:

- rerun it with a larger line count, for example `logs edi 200`
- or switch to `tail -f ~/.intentframe/logs/<service>.log`

If EDI appears busy long after startup:

- confirm whether `backfill_done` has appeared
- check whether periodic sync is running
- inspect `edi.log` for repeated errors or retry loops
