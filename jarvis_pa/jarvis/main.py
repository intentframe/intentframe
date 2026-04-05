"""Entry point: terminal REPL with slash commands.

Uses prompt_toolkit for interactive input (persistent history, autocomplete,
fish-style suggestions) and rich for streaming markdown output.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from loguru import logger
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from jarvis.config import JarvisConfig, load_config
from jarvis.agent import JarvisAgent

# ---------------------------------------------------------------------------
# Rich console (shared)
# ---------------------------------------------------------------------------

console = Console()

# ---------------------------------------------------------------------------
# Prompt styling
# ---------------------------------------------------------------------------

# Bold cyan "You: " label shown at the input prompt.
_YOU_PROMPT = FormattedText([("bold ansicyan", "You"), ("", ": ")])

# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

SLASH_COMMANDS: dict[str, str] = {
    "/help":      "Show available commands",
    "/new":       "Start a new session (archive current)",
    "/memory":    "Show memory files status",
    "/skills":    "List active skills",
    "/heartbeat": "Run heartbeat check now",
    "/config":    "Show current config",
    "/quit":      "Exit Jarvis",
}


async def handle_command(command: str, jarvis: JarvisAgent) -> None:
    """Dispatch a slash command."""
    cmd = command.strip().split()[0].lower()

    if cmd == "/help":
        table = Table(show_header=False, box=None, padding=(0, 2))
        for name, desc in SLASH_COMMANDS.items():
            table.add_row(f"[bold cyan]{name}[/]", desc)
        console.print(table)

    elif cmd == "/new":
        jarvis.session.reset()
        console.print("[green]Session archived. Starting fresh.[/]")

    elif cmd == "/memory":
        _cmd_memory(jarvis)

    elif cmd == "/skills":
        _cmd_skills(jarvis)

    elif cmd == "/heartbeat":
        await _cmd_heartbeat(jarvis)

    elif cmd == "/config":
        _cmd_config(jarvis.config)

    elif cmd == "/quit":
        await jarvis.shutdown()
        sys.exit(0)

    else:
        console.print(f"[red]Unknown command: {cmd}[/]. Type /help for options.")


def _cmd_config(config: JarvisConfig) -> None:
    """Pretty-print configuration as a rich table."""
    table = Table(title="Jarvis Configuration", show_header=True)
    table.add_column("Setting", style="cyan")
    table.add_column("Value")
    for field_name, value in config.model_dump().items():
        table.add_row(field_name, str(value))
    console.print(table)


def _cmd_memory(jarvis: JarvisAgent) -> None:
    """List workspace files with sizes and modification dates.

    M5: Enhanced with memory stats. For now shows basic file listing.
    """
    workspace = jarvis.memory.workspace
    if not workspace.exists():
        console.print("[yellow]Workspace not yet bootstrapped.[/]")
        return

    table = Table(title=f"Memory — {workspace}", show_header=True)
    table.add_column("File", style="cyan")
    table.add_column("Size", justify="right")
    table.add_column("Modified")

    import datetime as dt
    for path in sorted(workspace.rglob("*.md")):
        stat = path.stat()
        size = f"{stat.st_size:,} B"
        mtime = dt.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        rel = str(path.relative_to(workspace))
        table.add_row(rel, size, mtime)

    console.print(table)


def _cmd_skills(jarvis: JarvisAgent) -> None:
    """List active skills."""
    skills = getattr(jarvis, "_gated_skills", [])
    if not skills:
        console.print("[yellow]No skills active (check that required binaries are installed).[/]")
        return
    table = Table(title="Active Skills", show_header=True)
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Path", style="dim")
    for skill in skills:
        table.add_row(skill.name, skill.description, str(skill.path.parent))
    console.print(table)


async def _cmd_heartbeat(jarvis: JarvisAgent) -> None:
    """Run a heartbeat check immediately."""
    console.print("[cyan]Running heartbeat check…[/]")
    try:
        await jarvis.heartbeat._run_once()
        console.print("[green]Heartbeat check complete.[/]")
    except Exception as exc:
        console.print(f"[red]Heartbeat error: {exc}[/]")


# ---------------------------------------------------------------------------
# Streaming chat helper
# ---------------------------------------------------------------------------

_JARVIS_LABEL = Text("Jarvis: ", style="bold green")
_THINKING_SPINNER = Spinner("dots", text="thinking…", style="cyan")


def _render_tool_call(item: object) -> Panel:
    """Render a tool call as a compact dim panel (name + JSON args).

    Handles both function_call (has .name/.arguments) and hosted tool calls
    like web_search_call (has .type/.action) from the Responses API.
    """
    raw = getattr(item, "raw_item", None)
    raw_type = getattr(raw, "type", None)

    if raw_type == "function_call":
        name = getattr(raw, "name", "function")
        args_str = getattr(raw, "arguments", "{}")
        try:
            formatted = json.dumps(json.loads(args_str), indent=2)
        except Exception:
            formatted = args_str or "{}"
    elif raw_type == "web_search_call":
        name = "web_search"
        action = getattr(raw, "action", None)
        if action is not None:
            action_type = getattr(action, "type", "search")
            if action_type == "search":
                queries = getattr(action, "queries", None) or [getattr(action, "query", "")]
                formatted = json.dumps({"queries": queries}, indent=2)
            elif action_type == "open_page":
                formatted = json.dumps({"url": getattr(action, "url", "")}, indent=2)
            elif action_type == "find":
                formatted = json.dumps({"pattern": getattr(action, "pattern", ""), "url": getattr(action, "url", "")}, indent=2)
            else:
                formatted = json.dumps({"action": action_type}, indent=2)
        else:
            formatted = "{}"
    else:
        name = getattr(raw, "name", None) or raw_type or "tool"
        try:
            formatted = json.dumps(raw.model_dump(), indent=2, default=str) if hasattr(raw, "model_dump") else "{}"
        except Exception:
            formatted = "{}"

    return Panel(
        Syntax(formatted, "json", theme="monokai", background_color="default"),
        title=f"[dim]⚙  {name}[/dim]",
        border_style="dim",
        padding=(0, 1),
    )


def _build_live_renderable(
    tool_panels: list[Panel],
    text: str,
) -> Group:
    """Compose the live display: Jarvis label + tool panels + text (or spinner)."""
    parts: list[object] = [_JARVIS_LABEL]
    parts.extend(tool_panels)
    if text:
        parts.append(Markdown(text))
    else:
        parts.append(_THINKING_SPINNER)
    return Group(*parts)


async def _stream_response(jarvis: JarvisAgent, message: str) -> str:
    """Send a message and stream the response as live markdown.

    Shows a spinner while waiting for the first token.  Tool calls are
    rendered as dim labelled panels so they are visible but clearly
    separated from the conversational text.  Falls back to a single
    non-streamed run() call if run_streamed raises.
    """
    from openai.types.responses import ResponseTextDeltaEvent
    from agents import Runner

    if jarvis.agent is None or jarvis.ctx is None:
        return ""

    jarvis.session.append_user(message)
    await jarvis.session.maybe_compact(jarvis.memory)

    messages = jarvis.session.to_openai_messages()

    accumulated = ""
    tool_panels: list[Panel] = []

    try:
        result = Runner.run_streamed(jarvis.agent, messages, context=jarvis.ctx)
        with Live(
            _build_live_renderable(tool_panels, accumulated),
            console=console,
            refresh_per_second=15,
        ) as live:
            async for event in result.stream_events():
                if event.type == "raw_response_event":
                    if isinstance(event.data, ResponseTextDeltaEvent):
                        accumulated += event.data.delta
                        live.update(_build_live_renderable(tool_panels, accumulated))

                elif event.type == "run_item_stream_event":
                    if (
                        event.name == "tool_called"
                        and event.item.type == "tool_call_item"
                    ):
                        tool_panels.append(_render_tool_call(event.item))
                        live.update(_build_live_renderable(tool_panels, accumulated))

        final = result.final_output if hasattr(result, "final_output") else accumulated
    except Exception:
        result_sync = await Runner.run(jarvis.agent, messages, context=jarvis.ctx)
        final = result_sync.final_output
        console.print(Group(_JARVIS_LABEL, Markdown(final)))

    jarvis.session.append_assistant(final)
    jarvis.memory.auto_capture(message, final)
    return final


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

async def repl() -> None:
    """Main async REPL loop."""
    _setup_logging()

    config = load_config()
    jarvis = JarvisAgent(config)

    console.print("[bold cyan]Starting Jarvis…[/]")
    try:
        await jarvis.setup()
    except Exception as exc:
        console.print(f"[red]Setup failed: {exc}[/]")
        logger.exception("Setup error")
        sys.exit(1)

    console.print("[bold green]Jarvis ready.[/] Type a message or [cyan]/help[/] for commands.\n")

    history_path = config.workspace_dir / "history.txt"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    completer = WordCompleter(list(SLASH_COMMANDS.keys()), sentence=True)
    prompt_session: PromptSession[str] = PromptSession(
        history=FileHistory(str(history_path)),
        auto_suggest=AutoSuggestFromHistory(),
        completer=completer,
    )

    while True:
        try:
            user_input = await prompt_session.prompt_async(_YOU_PROMPT)
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye.[/]")
            await jarvis.shutdown()
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input.startswith("/"):
            await handle_command(user_input, jarvis)
            continue

        console.print()  # blank line after user input
        try:
            await _stream_response(jarvis, user_input)
        except Exception as exc:
            console.print(f"[red]Error: {exc}[/]")
            logger.exception("Chat error")
        console.print()  # blank line before next prompt


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    """Configure loguru: stderr for warnings+, file sink for everything."""
    logger.remove()  # Remove default handler
    # Human-readable stderr output (warnings and above only — keeps REPL clean)
    logger.add(sys.stderr, level="WARNING", format="{time:HH:mm:ss} | {level} | {message}")
    # Detailed file log for debugging
    log_dir = Path("~/.jarvis/logs").expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        str(log_dir / "jarvis.log"),
        level="DEBUG",
        rotation="10 MB",
        retention="7 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} | {message}",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def cli() -> None:
    """Sync entry point for the ``jarvis`` console script."""
    asyncio.run(repl())


if __name__ == "__main__":
    cli()
