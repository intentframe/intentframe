"""Shared console, prompt definitions, and display helpers for the CLI."""

from __future__ import annotations

from pathlib import Path

import httpx
from prompt_toolkit.formatted_text import FormattedText
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console(force_terminal=True)

# User-space marker written by ``intentframe_setup_root_demo.sh``; its
# presence on disk is the simplest local signal that the machine has
# root-demo escalation provisioned.  Shared here so the pre-flight
# warning (main.py) and the post-shutdown hint (repl.py) agree.
ROOT_DEMO_MARKER = Path.home() / ".intentframe" / "state" / "root-demo.json"


def root_demo_installed() -> bool:
    """True iff the root-demo marker exists on disk for this user."""
    return ROOT_DEMO_MARKER.exists()

# ── Prompt styling ───────────────────────────────────────────────────────────

SETUP_PROMPT = FormattedText([
    ("bold ansiyellow", "intentframe"),
    ("", " "),
    ("ansiyellow", "[setup]"),
    ("", "> "),
])
NORMAL_PROMPT = FormattedText([
    ("bold ansicyan", "intentframe"),
    ("", "> "),
])

# ── Command registry ─────────────────────────────────────────────────────────

COMMANDS: dict[str, str] = {
    "status":       "Show all service statuses",
    "health":       "Quick health check",
    "logs":         "View logs: logs <service> [lines]",
    "chat":         "Chat with Jarvis (or just type a message)",
    "start":        "Start a service: start <service>",
    "stop":         "Stop a service: stop <service>",
    "restart":      "Restart a service: restart <service>",
    "vault":        "Manage credentials (list/set/get/delete)",
    "edi":          "Manage EDI email (status/accounts/add/remove)",
    "config":       "Manage app preferences (list/get/set/delete)",
    "env":          "Manage system config env vars (list/set/delete)",
    "audit":        "View the intent audit trail",
    "permissions":  "Show macOS TCC permission status",
    "policies":     "List active policies",
    "bootstrap":    "Re-run policy/workspace seeding",
    "help":         "Show this help",
    "quit":         "Shut down IntentFrame and exit",
}

SETUP_COMMANDS = frozenset({
    "vault", "health", "status", "logs", "help", "quit", "exit", "q",
})

# ── Error formatting ─────────────────────────────────────────────────────────


def friendly_error(exc: Exception) -> str:
    """Extract a human-readable message from gateway errors."""
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            detail = exc.response.json().get("detail")
            if detail:
                return f"{exc.response.status_code}: {detail}"
        except Exception:
            pass
        return f"{exc.response.status_code}: {exc.response.reason_phrase}"
    return str(exc)


def error(msg: str) -> None:
    console.print(f"[red]{msg}[/]")


# ── Display helpers ──────────────────────────────────────────────────────────


def print_service_status(health_data: dict) -> None:
    """Compact service-health table from /system/health response."""
    services = health_data.get("services", {})
    if not services:
        return
    table = Table(show_header=True, box=None, padding=(0, 2))
    table.add_column("Service", style="cyan")
    table.add_column("Status")
    for name, info in services.items():
        healthy = info.get("healthy", False)
        running = info.get("running", healthy)
        if healthy:
            icon = "[green]ok[/]"
        elif not running:
            icon = "[dim]--[/]"
        else:
            icon = "[red bold]UNHEALTHY[/]"
        table.add_row(name, icon)
    console.print()
    console.print(table)
    console.print()


def print_profile_banner(health_data: dict) -> None:
    """Render the root-demo profile/escalation banner.

    Reads the ``root_demo`` block emitted by
    ``GET /system/health`` (see intentframe_gateway/routes/system.py).
    Stays silent for the vanilla user profile when escalation is
    disarmed -- banners in the default dev flow would be noise.  Renders
    a one-line status (plus install hint when relevant) for the root
    profile, and still renders for the user profile if the machine is
    armed, so operators who forget to pass ``--profile root`` after
    installing root-demo aren't surprised.
    """
    rd = health_data.get("root_demo") or {}
    profile = rd.get("profile", "user")
    armed = bool(rd.get("escalation_armed", False))
    exec_root = bool(rd.get("executor_running_as_root", False))

    if profile == "user" and not armed and not exec_root:
        return

    armed_label = "[green]ARMED[/]" if armed else "[red bold]DISARMED[/]"
    exec_label = "[green]yes[/]" if exec_root else "[dim]no[/]"
    console.print(
        f"[bold]Profile:[/] {profile}   "
        f"[bold]Escalation:[/] {armed_label}   "
        f"[bold]Executor running_as_root:[/] {exec_label}"
    )
    if profile == "root" and not armed:
        console.print(
            "[dim]Install:  sudo bash intentframe_setup_root_demo.sh[/]"
        )
    console.print()


def print_root_demo_uninstall_hint() -> None:
    """Post-shutdown reminder that the machine still has root-demo armed.

    Called after ``Gateway stopped.`` when ``root-demo.json`` is present.
    The sudoers entry persists across gateway lifetimes -- as long as it
    sits under ``/etc/sudoers.d/``, the *next* gateway launch will
    re-advertise ``INTENTFRAME_ESCALATION_ARMED=1`` regardless of which
    profile the user picks.  Remind the operator so they don't forget
    they're still carrying a NOPASSWD sudo entry for sandbox-exec.
    """
    if not root_demo_installed():
        return
    console.print(
        "[yellow]Note:[/] root-demo is still installed on this machine -- "
        "the next gateway launch will pick it up automatically."
    )
    console.print(
        "[dim]Uninstall:  sudo bash intentframe_uninstall_root_demo.sh[/]"
    )


def print_credential_checklist(creds: list[dict]) -> None:
    """Render a credential status panel with actionable hints for missing items."""
    table = Table(box=None, padding=(0, 2), show_header=False)
    table.add_column(style="bold")
    table.add_column(min_width=10)
    table.add_column(style="dim")

    any_missing_required = False
    any_missing_optional = False

    for c in creds:
        name = c["name"]
        configured = c["configured"]
        required = c["required"]

        if configured:
            icon = "[green]ok[/]"
            hint = ""
        elif required:
            icon = "[red bold]MISSING[/]"
            hint = c.get("hint", "")
            any_missing_required = True
        else:
            icon = "[yellow]--[/]"
            hint = c.get("hint", "")
            any_missing_optional = True

        tag = " [red](required)[/]" if required and not configured else ""
        help_note = f"  [dim italic]{c['help']}[/]" if not configured and c.get("help") else ""
        table.add_row(f"{name}{tag}", icon, f"{hint}{help_note}")

    footer_parts: list[str] = []
    if any_missing_required:
        footer_parts.append(
            "[bold red]Required credentials are missing — "
            "IntentFrame cannot fully start.[/]"
        )
    if any_missing_optional:
        footer_parts.append(
            "[dim]Optional credentials unlock Telegram and email features.[/]"
        )

    border = "red" if any_missing_required else ("yellow" if any_missing_optional else "green")

    console.print()
    console.print(Panel(
        table,
        title="[bold]Credential & Config Status[/]",
        border_style=border,
        padding=(1, 2),
        subtitle="[dim]Run the hint command to configure each item[/]",
    ))
    for part in footer_parts:
        console.print(f"  {part}")
    console.print()


def print_missing_optional(creds: list[dict]) -> None:
    """Compact one-liner hints for unconfigured optional features (normal mode)."""
    missing = [c for c in creds if not c["configured"] and not c["required"]]
    if not missing:
        return
    console.print("  [dim]Optional features not configured:[/]")
    for c in missing:
        console.print(f"    [yellow]--[/] {c['name']}:  [cyan]{c['hint']}[/]")
    console.print()


def print_setup_greeting() -> None:
    console.print(Panel(
        "[bold yellow]IntentFrame requires an OpenAI API key to start.[/]\n\n"
        "Run:  [bold cyan]vault set openai api_key[/]\n"
        "Then the system will restart automatically.\n\n"
        "[dim]Other commands: vault list, health, status, logs <service>, help, quit[/]",
        title="[bold]Setup Required[/]",
        border_style="yellow",
        padding=(1, 2),
    ))


def print_setup_help() -> None:
    table = Table(title="Setup Commands", show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column()
    table.add_row("vault set <ns> <key>", "Store a credential")
    table.add_row("vault list [ns]", "List credentials (masked)")
    table.add_row("vault check <ns> <key>", "Check if credential exists")
    table.add_row("health", "Aggregated health check")
    table.add_row("status", "Show all service statuses")
    table.add_row("logs <service> [lines]", "View logs")
    table.add_row("help", "Show this help")
    table.add_row("quit", "Shut down IntentFrame and exit")
    console.print()
    console.print(table)
    console.print("\n  Set the OpenAI key to unlock all features:")
    console.print("  [bold cyan]vault set openai api_key[/]\n")


def print_help() -> None:
    table = Table(title="Commands", show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column()
    for cmd, desc in COMMANDS.items():
        table.add_row(cmd, desc)
    console.print()
    console.print(table)

    sub = Table(title="Subcommands", show_header=False, box=None, padding=(0, 2))
    sub.add_column(style="cyan")
    sub.add_column(style="dim")
    for line in [
        ("vault list [ns]", "List credentials (masked)"),
        ("vault get <ns> <key>", "Retrieve credential value"),
        ("vault set <ns> <key>", "Store a credential (prompts for value)"),
        ("vault delete <ns> <key>", "Delete a credential"),
        ("vault check <ns> <key>", "Check if credential exists"),
        ("edi status", "EDI daemon status"),
        ("edi accounts", "List configured email accounts"),
        ("edi add <email> [name]", "Add email account"),
        ("edi remove <email>", "Remove email account"),
        ("config list", "List all preferences"),
        ("config get <key>", "Get preference value"),
        ("config set <key> <value>", "Set preference"),
        ("config delete <key>", "Delete preference"),
        ("env list", "Show system config and resolved env vars"),
        ("env set <key> <value>", "Set config (e.g. identity.user_id)"),
        ("env delete <key>", "Delete config key"),
    ]:
        sub.add_row(*line)
    console.print()
    console.print(sub)
    console.print("\nOr just type a message to chat with Jarvis.\n")
