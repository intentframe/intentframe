"""Entry point: python -m external_data_ingestion.email

Commands:
    email-sync-daemon start        Start the sync daemon (default)
    email-sync-daemon stop         Stop the running daemon
    email-sync-daemon status       Show daemon status
    email-sync-daemon verify       Check local DB integrity against IMAP server
    email-sync-daemon add EMAIL    Add an email account
    email-sync-daemon remove EMAIL Remove an email account
    email-sync-daemon list         List configured email accounts
    email-sync-daemon reset        Wipe DB + attachments (keep config)
    email-sync-daemon reset --all  Full wipe including config

Set INTENTFRAME_EMAIL_HOME to override the workspace
(default: ~/.intentframe/email).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time


def _cmd_start(args: argparse.Namespace) -> None:
    from .daemon import is_daemon_running, run_daemon

    alive, pid = is_daemon_running()
    if alive:
        print(f"Daemon already running (PID {pid})", file=sys.stderr)
        sys.exit(1)

    body_days = getattr(args, "body_days", None)
    try:
        asyncio.run(run_daemon(body_sync_days=body_days))
    except (FileNotFoundError, ValueError, ConnectionError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


def _cmd_stop(_args: argparse.Namespace) -> None:
    from .daemon import is_daemon_running, stop_daemon

    alive, pid = is_daemon_running()
    if not alive:
        print("Daemon is not running.")
        return

    print(f"Sending SIGTERM to daemon (PID {pid})...")
    stop_daemon()

    for _ in range(30):
        time.sleep(0.5)
        running, _ = is_daemon_running()
        if not running:
            print("Daemon stopped.")
            return

    print("Daemon did not stop within 15 seconds.", file=sys.stderr)
    sys.exit(1)


def _cmd_status(_args: argparse.Namespace) -> None:
    from .config import get_email_home, list_configured_emails
    from .daemon import is_daemon_running

    home = get_email_home()
    alive, pid = is_daemon_running()
    accounts = list_configured_emails()

    print(f"Workspace:  {home}")
    print(f"Daemon:     {'running (PID ' + str(pid) + ')' if alive else 'stopped'}")
    print(f"Accounts:   {len(accounts)}")
    if accounts:
        for email in accounts:
            print(f"  - {email}")


def _cmd_add(args: argparse.Namespace) -> None:
    from .config import add_email

    try:
        account = add_email(
            args.email,
            display_name=args.name or "",
            validate=not args.no_validate,
        )
        print(f"Added {account.email} ({account.provider}, {account.imap_host})")
        print("Restart the daemon to start syncing this account.")
    except (ValueError, ConnectionError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def _cmd_remove(args: argparse.Namespace) -> None:
    from .config import remove_email

    if remove_email(args.email):
        print(f"Removed {args.email}")
        print("Restart the daemon to stop syncing this account.")
    else:
        print(f"{args.email} not found in config", file=sys.stderr)
        sys.exit(1)


def _cmd_list(_args: argparse.Namespace) -> None:
    from .config import list_configured_emails

    emails = list_configured_emails()
    if not emails:
        print("No accounts configured.")
        return
    for email in emails:
        print(f"  {email}")


def _cmd_verify(_args: argparse.Namespace) -> None:
    from .config import load_config
    from .db import init_db
    from .sync import verify_integrity

    try:
        cfg = load_config()
    except (FileNotFoundError, ValueError, ConnectionError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    async def _run():
        db = await init_db(cfg.db_path)
        all_ok = True

        for account in cfg.accounts:
            print(f"\n{'─' * 60}")
            print(f"Verifying {account.email} ...")
            result = await verify_integrity(account, db, skip_roles={"all"})

            print(f"\n  {'Folder':<35s} {'Server':>7s} {'Local':>7s} {'Missing':>8s}")
            print(f"  {'─' * 35} {'─' * 7} {'─' * 7} {'─' * 8}")
            for name, info in sorted(result["folders"].items()):
                flag = "✓" if not info["missing"] else "✗"
                print(
                    f"  {name:<35s} {info['server']:>7d} {info['local']:>7d} "
                    f"{len(info['missing']):>7d}  {flag}"
                )
            print(f"  {'─' * 35} {'─' * 7} {'─' * 7} {'─' * 8}")
            print(
                f"  {'TOTAL':<35s} {result['total_server']:>7d} "
                f"{result['total_local']:>7d}"
            )

            if result["ok"]:
                print(f"\n  ✓ {account.email}: all UIDs accounted for")
            else:
                all_ok = False
                print(f"\n  ✗ {account.email}: gaps detected")
                for name, info in sorted(result["folders"].items()):
                    if info["missing"]:
                        sample = info["missing"][:10]
                        print(f"    {name}: {len(info['missing'])} missing UIDs (e.g. {sample})")

        await db.close()
        print(f"\n{'─' * 60}")
        if all_ok:
            print("All accounts verified — no gaps.")
        else:
            print("Integrity issues found. Re-run the daemon to fill gaps.")
            sys.exit(1)

    asyncio.run(_run())


def _cmd_reset(args: argparse.Namespace) -> None:
    from .config import get_email_home, reset_workspace
    from .daemon import is_daemon_running

    home = get_email_home()
    scope = "ALL data including config" if args.all else "database and attachments (keeping config)"

    if not args.yes:
        alive, pid = is_daemon_running()
        print(f"Workspace: {home}")
        if alive:
            print(f"Daemon:    running (PID {pid}) — will be stopped")
        print(f"This will delete {scope}.")
        answer = input("Are you sure? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return

    deleted = reset_workspace(include_config=args.all)

    parts = []
    if deleted.get("db"):
        parts.append("database")
    if deleted.get("attachments"):
        parts.append("attachments")
    if deleted.get("config"):
        parts.append("config")
    if deleted.get("pid"):
        parts.append("pid file")

    if parts:
        print(f"Deleted: {', '.join(parts)}")
    else:
        print("Nothing to delete — workspace was already clean.")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="email-sync-daemon",
        description="Email sync daemon and account management",
    )
    sub = parser.add_subparsers(dest="command")

    start_p = sub.add_parser("start", help="Start the sync daemon")
    start_p.add_argument(
        "--body-days", type=int, default=None,
        help="Days of message bodies to fetch during initial sync (default: 90, from config)",
    )
    sub.add_parser("stop", help="Stop the running daemon")
    sub.add_parser("status", help="Show daemon status")

    add_p = sub.add_parser("add", help="Add an email account (password must be in vault)")
    add_p.add_argument("email", help="Email address to add")
    add_p.add_argument("--name", "-n", default=None, help="Display name")
    add_p.add_argument("--no-validate", action="store_true", help="Skip IMAP login validation")

    rm_p = sub.add_parser("remove", help="Remove an email account")
    rm_p.add_argument("email", help="Email address to remove")

    sub.add_parser("list", help="List configured email accounts")

    sub.add_parser("verify", help="Check local DB integrity against IMAP server")

    reset_p = sub.add_parser("reset", help="Delete workspace data (wipe DB + attachments)")
    reset_p.add_argument("--all", action="store_true", help="Also delete config.yaml (full wipe)")
    reset_p.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")

    args = parser.parse_args()

    commands = {
        "start": _cmd_start,
        "stop": _cmd_stop,
        "status": _cmd_status,
        "add": _cmd_add,
        "remove": _cmd_remove,
        "list": _cmd_list,
        "verify": _cmd_verify,
        "reset": _cmd_reset,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        _cmd_start(args)


if __name__ == "__main__":
    main()
