"""Jarvis CLI — thin chatbot client that talks to the Jarvis API server.

Connects over UDS to a running jarvis-server.  If the server isn't
running, spawns it as a child process and waits for readiness.
Ctrl+C exits the CLI and kills any server process it started.

Uses prompt_toolkit for interactive input (persistent history,
fish-style suggestions) and rich for streaming markdown output.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
from loguru import logger
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.syntax import Syntax
from rich.text import Text

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SOCKET_PATH = "/tmp/jarvis.sock"
_HEALTH_URL = "/health"
_STREAM_URL = "/chat/stream"
_BASE_URL = "http://jarvis-local"
_STARTUP_TIMEOUT = 180  # seconds to wait for server readiness
_CLIENT_ID = "cli"

# ---------------------------------------------------------------------------
# Rich console & display
# ---------------------------------------------------------------------------

console = Console()

_YOU_PROMPT = FormattedText([("bold ansicyan", "You"), ("", ": ")])
_JARVIS_LABEL = Text("Jarvis: ", style="bold green")
_THINKING_SPINNER = Spinner("dots", text="thinking…", style="cyan")

# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

_server_process: subprocess.Popen | None = None


def _build_client() -> httpx.Client:
    transport = httpx.HTTPTransport(uds=_SOCKET_PATH)
    return httpx.Client(
        transport=transport,
        base_url=_BASE_URL,
        timeout=httpx.Timeout(connect=5.0, read=660.0, write=10.0, pool=10.0),
    )


def _server_is_ready(client: httpx.Client) -> bool:
    try:
        r = client.get(_HEALTH_URL)
        return r.status_code == 200
    except (httpx.ConnectError, httpx.RemoteProtocolError, OSError):
        return False


def _ensure_server() -> httpx.Client:
    """Return an httpx client connected to a running server.

    Starts the server as a child process if it isn't already running.
    """
    global _server_process

    client = _build_client()
    if _server_is_ready(client):
        console.print("[dim]Connected to running Jarvis server.[/]")
        console.print("[dim]Type 'exit' or 'quit' to stop.[/]\n")
        return client

    console.print("[bold cyan]Starting Jarvis server…[/]")
    log_path = Path("~/.jarvis/logs/server.log").expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "a")  # noqa: SIM115

    _server_process = subprocess.Popen(
        [sys.executable, "-m", "jarvis.server.app"],
        stdout=log_file,
        stderr=log_file,
    )
    log_file.close()

    deadline = time.monotonic() + _STARTUP_TIMEOUT
    poll_interval = 1.0
    with console.status("[cyan]Waiting for server to be ready…[/]"):
        while time.monotonic() < deadline:
            if _server_process.poll() is not None:
                console.print(
                    f"[red]Server exited with code {_server_process.returncode}. "
                    f"Check {log_path}[/]"
                )
                sys.exit(1)
            if _server_is_ready(client):
                console.print("[bold green]Jarvis ready.[/]")
                console.print("[dim]Type 'exit' or 'quit' to stop.[/]\n")
                return client
            time.sleep(poll_interval)
            poll_interval = min(poll_interval * 1.5, 5.0)

    console.print(f"[red]Server did not become ready within {_STARTUP_TIMEOUT}s. Check {log_path}[/]")
    _kill_server()
    sys.exit(1)


def _kill_server() -> None:
    global _server_process
    if _server_process is not None and _server_process.poll() is None:
        _server_process.terminate()
        try:
            _server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _server_process.kill()
            _server_process.wait()
        console.print("[dim]Server stopped.[/]")
    _server_process = None


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _render_tool_panel(name: str, arguments: str) -> Panel:
    """Render a tool call as a compact dim panel."""
    try:
        formatted = json.dumps(json.loads(arguments), indent=2)
    except Exception:
        formatted = arguments or "{}"

    return Panel(
        Syntax(formatted, "json", theme="monokai", background_color="default"),
        title=f"[dim]⚙  {name}[/dim]",
        border_style="dim",
        padding=(0, 1),
    )


def _build_live_renderable(tool_panels: list[Panel], text: str) -> Group:
    parts: list[object] = [_JARVIS_LABEL]
    parts.extend(tool_panels)
    if text:
        parts.append(Markdown(text))
    else:
        parts.append(_THINKING_SPINNER)
    return Group(*parts)


# ---------------------------------------------------------------------------
# Streaming chat
# ---------------------------------------------------------------------------

def _stream_response(client: httpx.Client, message: str) -> None:
    """POST /chat/stream and render SSE events as live markdown."""
    accumulated = ""
    tool_panels: list[Panel] = []

    try:
        with client.stream(
            "POST",
            _STREAM_URL,
            json={"message": message, "client": _CLIENT_ID},
        ) as resp:
            if resp.status_code == 429:
                resp.read()
                detail = resp.json().get("detail", {})
                who = detail.get("current_client", "another client")
                console.print(f"[yellow]Jarvis is busy talking to {who}. Try again shortly.[/]")
                return

            if resp.status_code != 200:
                console.print(f"[red]Server error ({resp.status_code})[/]")
                return

            with Live(
                _build_live_renderable(tool_panels, accumulated),
                console=console,
                refresh_per_second=15,
            ) as live:
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue

                    etype = event.get("type")

                    if etype == "text_delta":
                        accumulated += event.get("delta", "")
                        live.update(_build_live_renderable(tool_panels, accumulated))

                    elif etype == "tool_call":
                        tool_panels.append(
                            _render_tool_panel(
                                event.get("name", "tool"),
                                event.get("arguments", "{}"),
                            )
                        )
                        live.update(_build_live_renderable(tool_panels, accumulated))

                    elif etype == "done":
                        final = event.get("response", accumulated)
                        if final and final != accumulated:
                            live.update(_build_live_renderable(tool_panels, final))

                    elif etype == "error":
                        console.print(f"[red]Error: {event.get('error', 'unknown')}[/]")

    except httpx.ConnectError:
        console.print("[red]Lost connection to server.[/]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/]")
        logger.exception("Stream error")


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

async def repl() -> None:
    _setup_logging()

    client = _ensure_server()

    history_dir = Path("~/.jarvis").expanduser()
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / "history.txt"

    prompt_session: PromptSession[str] = PromptSession(
        history=FileHistory(str(history_path)),
        auto_suggest=AutoSuggestFromHistory(),
    )

    try:
        while True:
            try:
                user_input = await prompt_session.prompt_async(_YOU_PROMPT)
            except (KeyboardInterrupt, EOFError):
                break

            user_input = user_input.strip()
            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit"}:
                break

            console.print()
            _stream_response(client, user_input)
            console.print()
    finally:
        console.print("\n[dim]Goodbye.[/]")
        client.close()
        _kill_server()


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    logger.remove()
    logger.add(sys.stderr, level="WARNING", format="{time:HH:mm:ss} | {level} | {message}")
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
