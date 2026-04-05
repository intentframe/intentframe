"""Command handlers -- each function talks to the gateway and renders output."""

from __future__ import annotations

import json
import logging

from prompt_toolkit import PromptSession
from rich.live import Live
from rich.markdown import Markdown
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from intentframe_cli.client import GatewayClient
from intentframe_cli.ui import console, error, friendly_error

logger = logging.getLogger(__name__)

WELL_KNOWN_CREDENTIALS: dict[tuple[str, str], tuple[str, str]] = {
    ("openai", "api_key"): ("runtime_env", "OPENAI_API_KEY"),
    ("telegram", "bot_token"): ("runtime_env", "JARVIS_TELEGRAM_BOT_TOKEN"),
}


_RESTART_HINT = "[dim]  Restart the CLI ([cyan]quit[/cyan] then relaunch) for changes to take effect.[/]"


# ── Service / health ─────────────────────────────────────────────────────────


async def cmd_status(client: GatewayClient) -> None:
    try:
        svcs = await client.services()
    except Exception as exc:
        error(f"Error: {friendly_error(exc)}")
        return

    table = Table(show_header=True, padding=(0, 2))
    table.add_column("Service", style="cyan")
    table.add_column("Status")
    table.add_column("PID", style="dim")
    for s in svcs:
        name = s.get("name", "?")
        healthy = s.get("healthy", False)
        running = s.get("running", s.get("socket_exists", False))
        pid = str(s.get("pid", "") or "")
        if healthy:
            icon = "[green]ok[/]"
        elif not running:
            icon = "[dim]--[/]"
        else:
            icon = "[red bold]UNHEALTHY[/]"
        table.add_row(name, icon, pid)
    console.print()
    console.print(table)
    console.print()


async def cmd_health(client: GatewayClient) -> None:
    try:
        h = await client.health()
    except Exception as exc:
        error(f"Error: {friendly_error(exc)}")
        return

    overall = h.get("status", "unknown")
    partial = h.get("partial_startup", False)
    color = "green" if overall == "healthy" else "yellow"
    label = f"[bold {color}]{overall}[/]"
    if partial:
        label += " [yellow](partial startup)[/]"
    console.print(f"\nOverall: {label}")

    services = h.get("services", {})
    for name, info in services.items():
        healthy = info.get("healthy", False)
        icon = "[green]ok[/]" if healthy else "[red]UNHEALTHY[/]"
        console.print(f"  {name:<24} {icon}")
    console.print()


async def cmd_logs(client: GatewayClient, args: list[str]) -> None:
    if not args:
        console.print("[yellow]Usage: logs <service> [lines][/]")
        return
    service = args[0]
    lines = int(args[1]) if len(args) > 1 else 50
    try:
        data = await client.logs(service, lines=lines)
    except Exception as exc:
        error(f"Error: {friendly_error(exc)}")
        return
    for line in data.get("lines", []):
        console.print(line, highlight=False)


async def cmd_service_action(
    client: GatewayClient, action: str, args: list[str]
) -> None:
    if not args:
        console.print(f"[yellow]Usage: {action} <service>[/]")
        return
    name = args[0]
    try:
        if action == "start":
            resp = await client.service_start(name)
        elif action == "stop":
            resp = await client.service_stop(name)
        else:
            resp = await client.service_restart(name)
        console.print(f"  [green]{name}[/]: {resp.get('status', resp)}")
    except Exception as exc:
        error(f"Error: {friendly_error(exc)}")


# ── Chat ─────────────────────────────────────────────────────────────────────


async def cmd_chat(client: GatewayClient, message: str) -> None:
    if not message.strip():
        console.print("[yellow]Usage: chat <message>  (or just type your message directly)[/]")
        return

    jarvis_label = Text("Jarvis: ", style="bold green")

    try:
        accumulated = ""
        with Live(
            Spinner("dots", text="thinking…", style="cyan"),
            console=console,
            refresh_per_second=15,
        ) as live:
            async for chunk in client.chat_stream(message):
                try:
                    data = json.loads(chunk)
                except (json.JSONDecodeError, TypeError):
                    accumulated += str(chunk)
                    live.update(Markdown(accumulated))
                    continue
                evt_type = data.get("type", "")
                if evt_type == "done":
                    break
                text = data.get("delta", data.get("text", data.get("chunk", "")))
                if text:
                    accumulated += str(text)
                    live.update(Markdown(accumulated))
        console.print()
    except Exception as exc:
        logger.debug("Chat stream failed; falling back to POST /chat: %s", exc)
        try:
            resp = await client.chat(message)
            text = resp.get("response", resp.get("text", str(resp)))
            console.print(jarvis_label)
            console.print(Markdown(text))
        except Exception as exc2:
            error(f"Error: {friendly_error(exc2)}")
    console.print()


# ── Vault ────────────────────────────────────────────────────────────────────


async def cmd_vault(
    client: GatewayClient, args: list[str], session: PromptSession
) -> bool:
    """Returns True if a mandatory credential was just stored."""
    sub = args[0] if args else "list"
    stored_mandatory = False

    if sub == "list":
        ns = args[1] if len(args) > 1 else None
        try:
            creds = await client.vault_list(ns)
        except Exception as exc:
            error(f"Error: {friendly_error(exc)}")
            return False
        if not creds:
            console.print("[dim]No credentials stored." + (f" (namespace: {ns})" if ns else "") + "[/]")
            return False
        table = Table(show_header=True, padding=(0, 2))
        table.add_column("Namespace", style="cyan")
        table.add_column("Key", style="bold")
        table.add_column("Value", style="dim")
        table.add_column("Delivery")
        for c in creds:
            table.add_row(
                c.get("namespace", ""),
                c.get("key", ""),
                c.get("masked_preview", "***"),
                c.get("delivery_mode", ""),
            )
        console.print()
        console.print(table)
        console.print()

    elif sub == "get":
        if len(args) < 3:
            console.print("[yellow]Usage: vault get <namespace> <key>[/]")
            return False
        try:
            data = await client.vault_get(args[1], args[2])
            console.print(f"\n[cyan]{args[1]}/{args[2]}[/] = {data.get('value', '???')}\n")
        except Exception as exc:
            error(f"Error: {friendly_error(exc)}")

    elif sub == "set":
        if len(args) < 3:
            console.print("[yellow]Usage: vault set <namespace> <key>[/]")
            return False
        ns, key = args[1], args[2]

        value = await session.prompt_async(f"  Value for {ns}/{key}: ")
        if not value.strip():
            console.print("[dim]Aborted (empty value).[/]")
            return False

        well_known = WELL_KNOWN_CREDENTIALS.get((ns, key))
        if well_known:
            delivery, env_name = well_known
        else:
            delivery = "executor_only"
            env_name = None
            mode_input = (await session.prompt_async(
                "  Delivery mode [executor_only/runtime_env] (default: executor_only): "
            )).strip().lower()
            if mode_input in ("runtime_env", "r"):
                delivery = "runtime_env"
                env_name = (await session.prompt_async(
                    "  Env variable name (e.g. OPENAI_API_KEY): "
                )).strip() or None

        try:
            resp = await client.vault_set(ns, key, value.strip(), delivery_mode=delivery, env_name=env_name)
            console.print(f"  [green]{resp.get('status', 'done')}[/]: {ns}/{key}")
            if (ns, key) == ("openai", "api_key"):
                stored_mandatory = True
            elif not stored_mandatory:
                console.print(_RESTART_HINT)
        except Exception as exc:
            error(f"Error: {friendly_error(exc)}")

    elif sub == "delete":
        if len(args) < 3:
            console.print("[yellow]Usage: vault delete <namespace> <key>[/]")
            return False
        try:
            resp = await client.vault_delete(args[1], args[2])
            console.print(f"  [green]{resp.get('status', 'deleted')}[/]: {args[1]}/{args[2]}")
            console.print(_RESTART_HINT)
        except Exception as exc:
            error(f"Error: {friendly_error(exc)}")

    elif sub == "check":
        if len(args) < 3:
            console.print("[yellow]Usage: vault check <namespace> <key>[/]")
            return False
        try:
            exists = await client.vault_has(args[1], args[2])
            if exists:
                console.print(f"  {args[1]}/{args[2]}: [green]exists[/]")
            else:
                console.print(f"  {args[1]}/{args[2]}: [red]NOT FOUND[/]")
        except Exception as exc:
            error(f"Error: {friendly_error(exc)}")

    else:
        console.print("[yellow]Usage: vault [list|get|set|delete|check] ...[/]")

    return stored_mandatory


# ── EDI ──────────────────────────────────────────────────────────────────────


async def cmd_edi(client: GatewayClient, args: list[str]) -> None:
    sub = args[0] if args else "status"

    if sub == "status":
        try:
            status = await client.edi_status()
            console.print_json(json.dumps(status, default=str))
        except Exception as exc:
            error(f"Error: {friendly_error(exc)}")

    elif sub == "accounts":
        try:
            data = await client.edi_accounts()
            accounts = data.get("accounts", [])
            if not accounts:
                console.print("[dim]No email accounts configured.[/]")
                return
            table = Table(show_header=True, box=None, padding=(0, 2))
            table.add_column("Email", style="cyan")
            for a in accounts:
                email = a.get("email", str(a)) if isinstance(a, dict) else str(a)
                table.add_row(email)
            console.print()
            console.print(table)
            console.print()
        except Exception as exc:
            error(f"Error: {friendly_error(exc)}")

    elif sub == "add":
        if len(args) < 2:
            console.print("[yellow]Usage: edi add <email> [display_name][/]")
            return
        email = args[1]
        display_name = " ".join(args[2:]) if len(args) > 2 else ""
        try:
            resp = await client.edi_add_account(email, display_name)
            console.print(f"  [green]Added[/]: {resp.get('email', email)} (provider: {resp.get('provider', '?')}, imap: {resp.get('imap_host', '?')})")
            console.print(_RESTART_HINT)
        except Exception as exc:
            error(f"Error: {friendly_error(exc)}")

    elif sub == "remove":
        if len(args) < 2:
            console.print("[yellow]Usage: edi remove <email>[/]")
            return
        try:
            resp = await client.edi_remove_account(args[1])
            console.print(f"  [green]Removed[/]: {resp.get('email', args[1])}")
            console.print(_RESTART_HINT)
        except Exception as exc:
            error(f"Error: {friendly_error(exc)}")

    else:
        console.print("[yellow]Usage: edi [status|accounts|add|remove] ...[/]")


# ── Config ───────────────────────────────────────────────────────────────────


async def cmd_config(client: GatewayClient, args: list[str]) -> None:
    sub = args[0] if args else "list"

    if sub == "list":
        try:
            data = await client.config_list()
            if not data:
                console.print("[dim]No preferences set.[/]")
                return
            table = Table(show_header=True, padding=(0, 2))
            table.add_column("Key", style="cyan")
            table.add_column("Value")
            for k, v in data.items():
                table.add_row(str(k), str(v))
            console.print()
            console.print(table)
            console.print()
        except Exception as exc:
            error(f"Error: {friendly_error(exc)}")

    elif sub == "get":
        if len(args) < 2:
            console.print("[yellow]Usage: config get <key>[/]")
            return
        try:
            data = await client.config_get(args[1])
            console.print(f"\n  [cyan]{data.get('key', args[1])}[/] = {data.get('value', '???')}\n")
        except Exception as exc:
            error(f"Error: {friendly_error(exc)}")

    elif sub == "set":
        if len(args) < 3:
            console.print("[yellow]Usage: config set <key> <value>[/]")
            return
        key = args[1]
        value = " ".join(args[2:])
        try:
            resp = await client.config_set(key, value)
            console.print(f"  [green]{resp.get('key', key)}[/] = {resp.get('value', value)}")
        except Exception as exc:
            error(f"Error: {friendly_error(exc)}")

    elif sub == "delete":
        if len(args) < 2:
            console.print("[yellow]Usage: config delete <key>[/]")
            return
        try:
            resp = await client.config_delete(args[1])
            console.print(f"  [green]Deleted[/]: {resp.get('key', args[1])}")
        except Exception as exc:
            error(f"Error: {friendly_error(exc)}")

    else:
        console.print("[yellow]Usage: config [list|get|set|delete] ...[/]")


# ── System Config Env ────────────────────────────────────────────────────────


async def cmd_env(client: GatewayClient, args: list[str]) -> None:
    sub = args[0] if args else "list"

    if sub == "list":
        try:
            data = await client.config_env_list()
        except Exception as exc:
            error(f"Error: {friendly_error(exc)}")
            return

        raw_config = data.get("config", {})
        resolved = data.get("resolved_env", {})

        if not raw_config and not resolved:
            console.print("[dim]No system config set (~/.intentframe/gateway.yaml).[/]")
            return

        if raw_config:
            console.print("\n[bold]Config file:[/]")
            for section, values in raw_config.items():
                if isinstance(values, dict):
                    for k, v in values.items():
                        console.print(f"  [cyan]{section}.{k}[/] = {v}")
                else:
                    console.print(f"  [cyan]{section}[/] = {values}")

        if resolved:
            console.print("\n[bold]Resolved env vars (injected into child processes):[/]")
            table = Table(show_header=True, padding=(0, 2))
            table.add_column("Env Variable", style="cyan")
            table.add_column("Value")
            for k, v in resolved.items():
                table.add_row(k, str(v))
            console.print(table)
        console.print()

    elif sub == "set":
        if len(args) < 3:
            console.print("[yellow]Usage: env set <key> <value>[/]")
            console.print("[dim]  e.g. env set identity.user_id jarvis_default[/]")
            console.print("[dim]  e.g. env set env.MY_CUSTOM_VAR some_value[/]")
            return
        key = args[1]
        value = " ".join(args[2:])
        try:
            resp = await client.config_env_set(key, value)
            console.print(f"  [green]{key}[/] = {value}")
            console.print(_RESTART_HINT)
        except Exception as exc:
            error(f"Error: {friendly_error(exc)}")

    elif sub == "delete":
        if len(args) < 2:
            console.print("[yellow]Usage: env delete <key>[/]")
            return
        key = args[1]
        try:
            resp = await client.config_env_delete(key)
            console.print(f"  [green]Deleted[/]: {key}")
            console.print(_RESTART_HINT)
        except Exception as exc:
            error(f"Error: {friendly_error(exc)}")

    else:
        console.print("[yellow]Usage: env [list|set|delete] ...[/]")
        console.print("[dim]  Manage non-sensitive config injected as env vars into child processes.[/]")
        console.print("[dim]  Stored in ~/.intentframe/gateway.yaml[/]")


# ── Misc ─────────────────────────────────────────────────────────────────────


async def cmd_audit(client: GatewayClient) -> None:
    try:
        entries = await client.audit()
    except Exception as exc:
        error(f"Error: {friendly_error(exc)}")
        return
    if not entries:
        console.print("[dim]No audit entries.[/]")
        return
    for entry in entries:
        console.print_json(json.dumps(entry, default=str))
    console.print()


async def cmd_permissions(client: GatewayClient) -> None:
    try:
        perms = await client.permissions()
    except Exception as exc:
        error(f"Error: {friendly_error(exc)}")
        return

    table = Table(show_header=True, box=None, padding=(0, 2))
    table.add_column("Permission", style="cyan")
    table.add_column("Status")
    table.add_column("Hint", style="dim")
    for name, info in perms.items():
        granted = info.get("granted", False)
        hint = info.get("hint", "")
        icon = "[green]granted[/]" if granted else "[red]DENIED[/]"
        table.add_row(name, icon, hint if not granted else "")
    console.print()
    console.print(table)
    console.print()


async def cmd_policies(client: GatewayClient) -> None:
    try:
        data = await client.policies()
    except Exception as exc:
        error(f"Error: {friendly_error(exc)}")
        return
    console.print_json(json.dumps(data, default=str))
    console.print()


async def cmd_bootstrap(client: GatewayClient) -> None:
    try:
        resp = await client.bootstrap()
        console.print(f"  [green]Bootstrap[/]: {resp.get('status', resp)}")
    except Exception as exc:
        error(f"Error: {friendly_error(exc)}")
