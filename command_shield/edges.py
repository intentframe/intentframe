"""Containment-edge extraction for commands.

A command string is the *root* of a graph of code units.  Each
outgoing edge tells us about one other code body the command may
execute.  `extract_edges` produces one :class:`Edge` per such
outgoing link, preserving enough information for the pipeline to
decide whether to walk the edge (resolve the file, inspect the body)
or stop at a signal.

Edge kinds:

    inline        body is in-band in the command            (always resolvable)
    referenced    body is at a literal file path            (resolvable)
    piped_stdin   body streams from a producer process      (not resolvable)
    dynamic       path or body is constructed at shell-eval (not resolvable)
    interactive   interpreter invoked without any body      (not resolvable)
    compiled      classified after file-content sniffing    (not applicable here)

The `compiled` kind is produced downstream by the resolver once it
inspects the target file's magic bytes — not here.

Edges never execute anything, never touch the filesystem, and never
raise.  They are pure descriptors over a tokenised command string.
"""

from __future__ import annotations

import re
import shlex
from typing import Iterable

from command_shield.verdict import Edge

# ── Tables shared with language.py / structural.py ───────────────────

_INTERPRETER_LANGUAGE: dict[str, str] = {
    "python": "python",
    "python3": "python",
    "python2": "python",
    "bash": "shell",
    "sh": "shell",
    "zsh": "shell",
    "dash": "shell",
    "ksh": "shell",
    "ash": "shell",
    "fish": "shell",
    "node": "javascript",
    "nodejs": "javascript",
    "ruby": "ruby",
    "perl": "perl",
    "osascript": "applescript",
}

_INLINE_FLAGS: frozenset[str] = frozenset({"-c", "-e", "--eval"})

# Python/bash flags that take no argument and must be skipped when
# scanning for the first positional script.  This is intentionally a
# conservative superset — unknown single-letter flags also get skipped.
_ARGLESS_INTERPRETER_FLAGS: frozenset[str] = frozenset({
    # Python
    "-B", "-E", "-I", "-O", "-OO", "-R", "-s", "-S", "-u", "-v", "-x",
    # Bash / sh
    "-a", "-b", "-E", "-f", "-h", "-k", "-m", "-n", "-p", "-t", "-u",
    "-v", "-x", "-B", "-C", "-H", "-P", "-T",
    "-i",  # bash interactive — still parses a following script arg
    "-l", "--login", "--norc", "--noprofile",
    # Node
    "--no-warnings", "--use-strict",
})

# Sourcing builtins — their first positional is a *script file* to be
# evaluated in-process.
_SOURCE_VERBS: frozenset[str] = frozenset({"source", "."})

# Characters that, when present in a positional path, make the path
# non-literal (shell will rewrite it at eval time).  Ordered so the
# reason can be reported with the most specific marker that hit.
_DYNAMIC_MARKERS: tuple[tuple[str, str], ...] = (
    ("$(", "command-substitution"),
    ("`", "backtick-substitution"),
    ("<(", "process-substitution"),
    (">(", "process-substitution"),
    ("$", "variable-expansion"),
    ("*", "glob"),
    ("?", "glob"),
    ("[", "glob"),
)

# Pipe-to-interpreter shape.  Matches `| python`, `| python3 -`,
# `| bash`, etc. — the inner body cannot be resolved.
_PIPED_STDIN_RX = re.compile(
    r"\|\s*"
    r"(?P<interp>python3?|python2|node|nodejs|ruby|perl|bash|sh|zsh|dash|ksh|ash)"
    r"(?:\s+-)?"
    r"(?=\s|$|\||;|&)"
)


def _interpreter_language(tok: str) -> str | None:
    """Return the language of *tok* if it looks like an interpreter verb."""
    base = tok.rsplit("/", 1)[-1]
    return _INTERPRETER_LANGUAGE.get(base)


def _unresolvable_reason(arg: str) -> str | None:
    """Return the marker name if *arg* contains any dynamic construct."""
    if not arg:
        return "empty"
    if arg == "-":
        return "stdin-marker"
    for marker, name in _DYNAMIC_MARKERS:
        if marker in arg:
            return name
    return None


def _scan_piped_stdin(command: str, depth: int) -> list[Edge]:
    """Find `… | <interpreter>` shapes and emit piped_stdin edges."""
    edges: list[Edge] = []
    for m in _PIPED_STDIN_RX.finditer(command):
        interp = m.group("interp")
        base = interp.rstrip("0123456789")
        lang = _INTERPRETER_LANGUAGE.get(interp) or _INTERPRETER_LANGUAGE.get(base)
        edges.append(Edge(
            kind="piped_stdin",
            language=lang,
            body=None,
            path_arg=None,
            resolvable=False,
            unresolvable_reason="stdin-pipe",
            position=(m.start(), m.end()),
            depth=depth,
        ))
    return edges


def _find_script_positional(
    tokens: list[str], start: int
) -> tuple[int, str] | None:
    """Find first non-flag positional after interpreter token at *start*.

    Returns (index, token) or None if the interpreter has no positional
    (interactive shape) or is followed only by flags.  Flags with
    attached values (``-Wignore``, ``--module=foo``) are skipped.  The
    inline-flag case (`-c`, `-e`, `--eval`) is handled by the caller
    and should never reach here.
    """
    i = start + 1
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if not tok.startswith("-"):
            return i, tok
        # Handle `-m module` specially — module name is *not* a script
        # path, the body is importlib-resolved.  Treat as interactive.
        if tok == "-m" and i + 1 < n:
            return None
        # Long option with `=` embedded value → skip as one token.
        if tok.startswith("--") and "=" in tok:
            i += 1
            continue
        # Bare `-` or `-<digit>` → treated as positional (stdin / script).
        if tok == "-":
            return i, tok
        i += 1
    return None


def _extract_from_tokens(
    tokens: list[str], *, depth: int, text: str
) -> list[Edge]:
    """Walk *tokens* looking for interpreter + script / inline shapes."""
    edges: list[Edge] = []
    n = len(tokens)
    i = 0
    while i < n:
        tok = tokens[i]
        base = tok.rsplit("/", 1)[-1]

        # `source foo.sh` / `. foo.sh` — sourcing counts as execution.
        if base in _SOURCE_VERBS and i + 1 < n:
            path_tok = tokens[i + 1]
            reason = _unresolvable_reason(path_tok)
            if reason:
                edges.append(Edge(
                    kind="dynamic",
                    language="shell",
                    body=None,
                    path_arg=path_tok,
                    resolvable=False,
                    unresolvable_reason=reason,
                    position=(0, 0),
                    sub_kind="source",
                    depth=depth,
                ))
            else:
                edges.append(Edge(
                    kind="referenced",
                    language="shell",
                    body=None,
                    path_arg=path_tok,
                    resolvable=True,
                    unresolvable_reason=None,
                    position=(0, 0),
                    sub_kind="source",
                    depth=depth,
                ))
            i += 2
            continue

        lang = _interpreter_language(tok)
        if lang is None:
            i += 1
            continue

        # Inline flag shape: `python -c "code"`, `node --eval "code"`.
        inline_body: str | None = None
        inline_at: int | None = None
        j = i + 1
        while j < n:
            if tokens[j] in _INLINE_FLAGS and j + 1 < n:
                inline_body = tokens[j + 1]
                inline_at = j
                break
            if not tokens[j].startswith("-"):
                break
            j += 1

        if inline_body is not None:
            edges.append(Edge(
                kind="inline",
                language=lang,
                body=inline_body,
                path_arg=None,
                resolvable=True,
                unresolvable_reason=None,
                position=(0, 0),
                depth=depth,
            ))
            # Past the flag + its payload.
            i = (inline_at or i) + 2
            continue

        # Non-inline interpreter → look for a script positional.
        pos = _find_script_positional(tokens, i)
        if pos is None:
            # Interactive (`python` with no args) or `-m module` shape.
            edges.append(Edge(
                kind="interactive",
                language=lang,
                body=None,
                path_arg=None,
                resolvable=False,
                unresolvable_reason="no-body",
                position=(0, 0),
                depth=depth,
            ))
            i += 1
            continue

        pos_idx, path_tok = pos
        reason = _unresolvable_reason(path_tok)
        if path_tok == "-":
            edges.append(Edge(
                kind="interactive",
                language=lang,
                body=None,
                path_arg="-",
                resolvable=False,
                unresolvable_reason="stdin-marker",
                position=(0, 0),
                depth=depth,
            ))
        elif reason:
            edges.append(Edge(
                kind="dynamic",
                language=lang,
                body=None,
                path_arg=path_tok,
                resolvable=False,
                unresolvable_reason=reason,
                position=(0, 0),
                depth=depth,
            ))
        else:
            edges.append(Edge(
                kind="referenced",
                language=lang,
                body=None,
                path_arg=path_tok,
                resolvable=True,
                unresolvable_reason=None,
                position=(0, 0),
                depth=depth,
            ))
        i = pos_idx + 1

    return edges


def extract_edges(
    command: str,
    *,
    indirections: Iterable[str] = (),
    depth: int = 0,
    max_depth: int = 2,
) -> tuple[Edge, ...]:
    """Extract outgoing containment edges from *command*.

    `indirections` are payloads already pulled out of `bash -c "..."`
    / `python -c "..."` shapes by the structural pass — we walk them
    as depth+1 so nested script references are discovered too.

    Depth is bounded by *max_depth*; deeper nesting stops quietly
    (the caller can inspect `len(edges)` vs structural signals to
    decide whether to emit `edge:nested-too-deep`).
    """
    if not command or not command.strip() or depth > max_depth:
        return ()

    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        # Unclosed quotes or similar — fall back to whitespace split.
        tokens = command.split()

    edges: list[Edge] = []
    if tokens:
        edges.extend(_extract_from_tokens(tokens, depth=depth, text=command))

    # Piped-stdin shapes need the raw string — `|` is a shell operator
    # that shlex collapses into tokens out of context.
    edges.extend(_scan_piped_stdin(command, depth=depth))

    if depth < max_depth:
        for payload in indirections:
            edges.extend(
                extract_edges(
                    payload,
                    indirections=(),
                    depth=depth + 1,
                    max_depth=max_depth,
                )
            )

    return tuple(edges)


__all__ = ["Edge", "extract_edges"]
