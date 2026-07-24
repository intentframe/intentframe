"""Minimal ANSI styling for return-agent demo output."""

from __future__ import annotations

import os
import re
import sys
import textwrap

_ENABLED = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
WIDTH = 92

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _visible_len(text: str) -> int:
    return len(_ANSI_RE.sub("", text))


def _pad_visible(text: str, width: int) -> str:
    """Pad accounting for invisible ANSI codes so bordered boxes stay aligned."""
    pad = width - _visible_len(text)
    return text + " " * pad if pad > 0 else text


def _wrap(code: str, text: str) -> str:
    if not _ENABLED:
        return text
    return f"\033[{code}m{text}\033[0m"


def build_a(text: str) -> str:
    return _wrap("93;1", text)


refund_agent = build_a


def intentframe(text: str) -> str:
    return _wrap("96;1", text)


def approve(text: str) -> str:
    return _wrap("92;1", text)


def block(text: str) -> str:
    return _wrap("91;1", text)


def warn(text: str) -> str:
    return _wrap("93", text)


def dim(text: str) -> str:
    return _wrap("2", text)


def bold(text: str) -> str:
    return _wrap("1", text)


def color_build_a_decision(decision: str) -> str:
    upper = (decision or "").upper()
    if upper == "APPROVE":
        return approve(decision)
    if upper in {"DENY", "BLOCK"}:
        return block(decision)
    if upper:
        return warn(decision)
    return decision or "(unparsed)"


def color_intentframe_decision(decision: str) -> str:
    upper = (decision or "").upper()
    if upper == "ALLOW":
        return approve(decision)
    if upper == "BLOCK":
        return block(decision)
    return decision


def _pad(text: str, width: int) -> str:
    if len(text) >= width:
        return text[:width]
    return text + " " * (width - len(text))


def hr(char: str = "─", width: int = WIDTH) -> None:
    print(dim(char * width))


def section(label: str, *, width: int = WIDTH) -> None:
    tail = max(1, width - len(label) - 5)
    print()
    print(dim(f"  ─── {label} " + "─" * tail))


def _center_visible(text: str, width: int) -> str:
    pad = width - _visible_len(text)
    if pad <= 0:
        return text
    left = pad // 2
    return " " * left + text + " " * (pad - left)


def headline(text: str, subtitle: str = "", *, width: int = WIDTH) -> None:
    inner = width - 2
    print("╔" + "═" * inner + "╗")
    print("║" + bold(_center_visible(text, inner)) + "║")
    if subtitle:
        print("║" + dim(_center_visible(subtitle, inner)) + "║")
    print("╚" + "═" * inner + "╝")


def run_footer(text: str = "END OF RUN", *, width: int = WIDTH) -> None:
    """Clear, distinct end marker so repeated runs are easy to separate."""
    label = f" {text} "
    side = (width - _visible_len(label)) // 2
    bar = "▁" * width
    print()
    print(dim("━" * side) + bold(label) + dim("━" * (width - side - _visible_len(label))))
    print(dim(bar))
    print("\n")


def columns(left: str, right: str, *, colw: int = 42, gap: str = " │ ") -> str:
    lc = _pad(left, colw)
    rc = _pad(right, colw)
    return f"  {lc}{gap}{rc}"


def callout(text: str, *, width: int = WIDTH) -> None:
    inner = width - 4
    print("  ╭" + "─" * (width - 2) + "╮")
    print("  │ " + bold(_pad_visible(text, inner)) + " │")
    print("  ╰" + "─" * (width - 2) + "╯")


def fenced_block(body: str, *, title: str = "", width: int = WIDTH, max_lines: int = 14) -> None:
    """Dim bordered block for verbose agent output."""
    inner = width - 6
    top = f"  ┌─ {title} " if title else "  ┌─"
    fill = max(1, width - len(top) - 1)
    print(dim(top + "─" * fill + "┐"))
    lines = body.splitlines()
    total = len(lines)
    if total > max_lines:
        lines = lines[:max_lines] + [f"... ({total - max_lines} more lines)"]
    for line in lines:
        for chunk in textwrap.wrap(line, width=inner) or [""]:
            print(dim("  │ ") + dim(chunk.ljust(inner)) + dim(" │"))
    print(dim("  └" + "─" * (width - 3) + "┘"))


def verdict_box(
    *,
    agent_label: str,
    agent_value: str,
    guard_label: str = "INTENTFRAME",
    guard_value: str | None = None,
    reason: str | None = None,
    width: int = WIDTH,
) -> None:
    inner = width - 6
    top = "  ┏" + "━" * (width - 4) + "┓"
    bottom = "  ┗" + "━" * (width - 4) + "┛"

    def line(content: str) -> None:
        print("  ┃ " + _pad_visible(content, inner) + " ┃")

    print()
    print(bold(top))
    line(f"{bold(agent_label.ljust(14))} {agent_value}")
    if guard_value is not None:
        line(f"{bold(guard_label.ljust(14))} {guard_value}")
    if reason:
        line("")
        first = True
        for chunk in textwrap.wrap(reason, width=inner - 9) or [""]:
            tag = dim("reason") if first else "      "
            line(f"{tag}   {dim(chunk)}")
            first = False
    print(bold(bottom))
