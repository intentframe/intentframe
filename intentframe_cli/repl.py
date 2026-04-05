"""REPL loops (setup + normal mode) and prompt session factory."""

from __future__ import annotations

import os
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory

from intentframe_cli.client import GatewayClient
from intentframe_cli.commands import (
    cmd_audit,
    cmd_bootstrap,
    cmd_chat,
    cmd_config,
    cmd_edi,
    cmd_env,
    cmd_health,
    cmd_logs,
    cmd_permissions,
    cmd_policies,
    cmd_service_action,
    cmd_status,
    cmd_vault,
)
from intentframe_cli.lifecycle import restart_gateway, stop_gateway
from intentframe_cli.ui import (
    COMMANDS,
    NORMAL_PROMPT,
    SETUP_COMMANDS,
    SETUP_PROMPT,
    console,
    error,
    print_credential_checklist,
    print_help,
    print_missing_optional,
    print_service_status,
    print_setup_greeting,
    print_setup_help,
)

# ── Session factory ──────────────────────────────────────────────────────────


def _history_path() -> Path:
    p = Path(os.environ.get(
        "INTENTFRAME_DATA_DIR",
        os.path.expanduser("~/.intentframe"),
    )) / "cli_history.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def make_session(commands: list[str] | None = None) -> PromptSession:
    return PromptSession(
        history=FileHistory(str(_history_path())),
        auto_suggest=AutoSuggestFromHistory(),
        completer=WordCompleter(
            commands or list(COMMANDS.keys()), sentence=True,
        ),
    )


async def _shutdown(client: GatewayClient) -> None:
    """Shared shutdown sequence for Ctrl+C, EOF, and quit command."""
    console.print("\n[dim]Shutting down IntentFrame...[/]")
    graceful = await stop_gateway(client)
    if graceful:
        console.print("[green]Gateway stopped.[/]")
    else:
        console.print("[yellow]Gateway force-killed after timeout.[/]")


# ── Setup mode ───────────────────────────────────────────────────────────────


async def run_setup_mode(client: GatewayClient, health_data: dict) -> bool:
    """Restricted REPL for partial startup. Returns True if user quit."""
    print_service_status(health_data)
    try:
        cred_data = await client.credential_status()
        print_credential_checklist(cred_data.get("credentials", []))
    except Exception:
        print_setup_greeting()
    session = make_session(list(SETUP_COMMANDS))

    while True:
        try:
            raw = (await session.prompt_async(SETUP_PROMPT)).strip()
        except (KeyboardInterrupt, EOFError):
            await _shutdown(client)
            return True

        if not raw:
            continue

        parts = raw.split(None, 1)
        cmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""
        args = rest.split() if rest else []

        if cmd not in SETUP_COMMANDS:
            console.print(
                "[yellow]  Not available until OpenAI API key is configured.[/]"
            )
            console.print("  Run: [bold cyan]vault set openai api_key[/]\n")
            continue

        if cmd == "help":
            print_setup_help()
        elif cmd == "status":
            await cmd_status(client)
        elif cmd == "health":
            await cmd_health(client)
        elif cmd == "logs":
            await cmd_logs(client, args)
        elif cmd == "vault":
            stored_mandatory = await cmd_vault(client, args, session)
            if stored_mandatory:
                console.print(
                    "\n  [bold green]Key stored.[/] Restarting IntentFrame..."
                )
                ok = await restart_gateway(client)
                if not ok:
                    error("  Gateway did not restart successfully.")
                    console.print(
                        "  Check ~/.intentframe/logs/gateway.log for details.\n"
                    )
                    continue
                console.print("  [green]Gateway restarted.[/]\n")
                h = await client.health()
                if h.get("partial_startup", False):
                    print_service_status(h)
                    console.print(
                        "[yellow]  System still in partial startup.[/]\n"
                    )
                    continue
                return False
        elif cmd in ("quit", "exit", "q"):
            await _shutdown(client)
            return True


# ── Normal mode ──────────────────────────────────────────────────────────────


async def run_normal_mode(client: GatewayClient, health_data: dict) -> None:
    """Full REPL after successful startup."""
    print_service_status(health_data)
    try:
        cred_data = await client.credential_status()
        print_missing_optional(cred_data.get("credentials", []))
    except Exception:
        pass
    console.print(
        "[bold green]Jarvis is ready.[/] Type a message, or [cyan]help[/] for commands.\n"
    )
    session = make_session()

    while True:
        try:
            raw = (await session.prompt_async(NORMAL_PROMPT)).strip()
        except (KeyboardInterrupt, EOFError):
            await _shutdown(client)
            break

        if not raw:
            continue

        parts = raw.split(None, 1)
        cmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""
        args = rest.split() if rest else []

        if cmd == "help":
            print_help()
        elif cmd == "status":
            await cmd_status(client)
        elif cmd == "health":
            await cmd_health(client)
        elif cmd == "logs":
            await cmd_logs(client, args)
        elif cmd == "chat":
            await cmd_chat(client, rest)
        elif cmd in ("start", "stop", "restart"):
            await cmd_service_action(client, cmd, args)
        elif cmd == "vault":
            await cmd_vault(client, args, session)
        elif cmd == "edi":
            await cmd_edi(client, args)
        elif cmd == "config":
            await cmd_config(client, args)
        elif cmd == "env":
            await cmd_env(client, args)
        elif cmd == "audit":
            await cmd_audit(client)
        elif cmd == "permissions":
            await cmd_permissions(client)
        elif cmd == "policies":
            await cmd_policies(client)
        elif cmd == "bootstrap":
            await cmd_bootstrap(client)
        elif cmd in ("quit", "exit", "q"):
            await _shutdown(client)
            break
        else:
            await cmd_chat(client, raw)
