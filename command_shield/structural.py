"""Structural analysis via bashlex AST + shlex fallback.

Decomposes commands into sub-commands, detects command substitution,
variable expansion, redirections, and interpreter indirection.
"""

from __future__ import annotations

import logging
import shlex
from typing import Any

from command_shield.verdict import Signal, Verdict

logger = logging.getLogger(__name__)

_INTERPRETERS = frozenset({
    "python", "python3", "python2",
    "perl", "ruby", "node",
    "bash", "sh", "zsh", "dash",
    "osascript",
})

_INLINE_FLAGS = frozenset({"-c", "-e", "--eval"})

try:
    import bashlex  # type: ignore[import-untyped]
    from bashlex import ast as _ast  # type: ignore[import-untyped]
    from bashlex.errors import ParsingError  # type: ignore[import-untyped]
    _HAS_BASHLEX = True
except ImportError:
    _HAS_BASHLEX = False
    ParsingError = Exception  # noqa: N818  — fallback type


class _Visitor(_ast.nodevisitor if _HAS_BASHLEX else object):  # type: ignore[misc]
    """Walk a bashlex AST collecting structural signals."""

    def __init__(self) -> None:
        self.sub_commands: list[str] = []
        self.signals: list[Signal] = []
        self.indirections: list[str] = []  # extracted inner payloads

    # -- node visitors (bashlex calls visit<kind>) -------------------------

    def visitcommand(self, n: Any, parts: list[Any]) -> bool:
        words = [p.word for p in parts if getattr(p, "kind", None) == "word"]
        if words:
            self.sub_commands.append(" ".join(words))
            self._check_indirection(words)
        return True

    def visitcommandsubstitution(self, n: Any, command: Any) -> bool:
        pos = getattr(n, "pos", (0, 0))
        self.signals.append(Signal(
            check="structural",
            signal_id="command-substitution",
            description="Command substitution detected ($() or backticks)",
            evidence=f"pos {pos[0]}–{pos[1]}",
        ))
        return False  # don't recurse — inner command is opaque

    def visitparameter(self, n: Any, value: str) -> bool:
        self.signals.append(Signal(
            check="structural",
            signal_id="variable-expansion",
            description=f"Variable expansion ${{{value}}}",
            evidence=value,
        ))
        return True

    def visitprocesssubstitution(self, n: Any, command: Any) -> bool:
        self.signals.append(Signal(
            check="structural",
            signal_id="process-substitution",
            description="Process substitution detected <() or >()",
            evidence=str(getattr(n, "pos", "")),
        ))
        return False

    # -- indirection -------------------------------------------------------

    def _check_indirection(self, words: list[str]) -> None:
        if len(words) < 3:
            return
        cmd = words[0].split("/")[-1]  # strip path prefix
        if cmd not in _INTERPRETERS:
            return
        for i, w in enumerate(words[1:], start=1):
            if w in _INLINE_FLAGS and i + 1 < len(words):
                payload = words[i + 1]
                self.indirections.append(payload)
                self.signals.append(Signal(
                    check="indirection",
                    signal_id="interpreter-indirection",
                    description=f"Interpreter indirection: {cmd} {w}",
                    evidence=payload[:200],
                ))
                return


def decompose(command: str) -> tuple[list[str], list[Signal], list[str]]:
    """Parse *command* into structural components.

    Returns (sub_commands, signals, indirection_payloads).
    Falls back to shlex if bashlex is unavailable or parsing fails.
    """
    if _HAS_BASHLEX:
        try:
            trees = bashlex.parse(command)
            visitor = _Visitor()
            for tree in trees:
                visitor.visit(tree)
            return visitor.sub_commands, visitor.signals, visitor.indirections
        except ParsingError:
            return _shlex_fallback(command, parse_error=True)
        except NotImplementedError:
            return _shlex_fallback(command, parse_error=True)
        except Exception:  # noqa: BLE001
            logger.debug("bashlex unexpected error, falling back to shlex", exc_info=True)
            return _shlex_fallback(command, parse_error=True)

    return _shlex_fallback(command, parse_error=False)


def _shlex_fallback(
    command: str,
    *,
    parse_error: bool,
) -> tuple[list[str], list[Signal], list[str]]:
    """Tokenise via shlex.  Returns signals noting the fallback."""
    signals: list[Signal] = []
    if parse_error:
        signals.append(Signal(
            check="structural",
            signal_id="parse-failure",
            description="Could not parse command (malformed syntax or unsupported construct)",
            evidence=command[:200],
        ))

    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
        signals.append(Signal(
            check="structural",
            signal_id="shlex-failure",
            description="shlex could not tokenize command",
            evidence=command[:200],
        ))

    sub_commands = [" ".join(tokens)] if tokens else []

    indirections: list[str] = []
    for i, tok in enumerate(tokens):
        cmd = tok.split("/")[-1]
        if cmd in _INTERPRETERS and i + 2 < len(tokens) and tokens[i + 1] in _INLINE_FLAGS:
            payload = tokens[i + 2]
            indirections.append(payload)
            signals.append(Signal(
                check="indirection",
                signal_id="interpreter-indirection",
                description=f"Interpreter indirection: {cmd} {tokens[i+1]}",
                evidence=payload[:200],
            ))

    return sub_commands, signals, indirections


def normalize(command: str) -> str:
    """Normalize a command by stripping quote obfuscation via shlex."""
    try:
        tokens = shlex.split(command)
        return " ".join(tokens)
    except ValueError:
        return command
