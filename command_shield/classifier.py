"""Capability classification — deterministic regex/structural tags.

Step 7 of the inspection pipeline.  Works on any command string
regardless of language support; tags describe *what the command can
do*, not *whether it is allowed*.  Consumer (Guardian/AE) decides what
to do with each capability.

Emitted capability IDs (stable contract):
    capability:package_install   — installs packages (pip/npm/apt/...)
    capability:compilation       — compiles/links code (gcc/clang/make/...)
    capability:network_bind      — binds a local network port/listener
    capability:background_exec   — backgrounds a process (nohup/&/screen)
    capability:download_and_exec — fetches a remote payload and pipes to a shell
    capability:spawns_process    — shells out / spawns a child process

Each hit produces a Signal with check="capability" and signal_id set to
the capability tag (e.g. "capability:package_install").  Multiple
capabilities per command are expected; they are not mutually exclusive.
"""

from __future__ import annotations

import re

from command_shield.verdict import Signal

# ── Capability IDs ───────────────────────────────────────────────────

CAPABILITY_PACKAGE_INSTALL = "capability:package_install"
CAPABILITY_COMPILATION = "capability:compilation"
CAPABILITY_NETWORK_BIND = "capability:network_bind"
CAPABILITY_BACKGROUND_EXEC = "capability:background_exec"
CAPABILITY_DOWNLOAD_AND_EXEC = "capability:download_and_exec"
CAPABILITY_SPAWNS_PROCESS = "capability:spawns_process"


# ── Detection rules ─────────────────────────────────────────────────
#
# Each rule is (regex, capability_id, description).
# Regexes run against the normalized command string and against each
# indirection payload.  Rules are intentionally conservative — false
# negatives are preferable to false positives, since the verdict comes
# from step 3 patterns and these signals are advisory.

_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    # Package installation — common managers, install-style verbs.
    (
        re.compile(
            r"\b(?:pip3?|pipx|uv|poetry|conda|mamba)\s+install\b"
            r"|\bnpm\s+(?:i|install|add)\b"
            r"|\bpnpm\s+(?:i|add|install)\b"
            r"|\byarn\s+(?:add|install)\b"
            r"|\bbrew\s+(?:install|reinstall|upgrade)\b"
            r"|\bapt(?:-get)?\s+(?:install|upgrade)\b"
            r"|\byum\s+(?:install|update)\b"
            r"|\bdnf\s+(?:install|upgrade)\b"
            r"|\bpacman\s+-S\b"
            r"|\bapk\s+add\b"
            r"|\bgem\s+install\b"
            r"|\bcargo\s+install\b"
            r"|\bgo\s+install\b"
            r"|\bcomposer\s+(?:install|require)\b"
        ),
        CAPABILITY_PACKAGE_INSTALL,
        "Command installs one or more packages",
    ),
    # Compilation / build — compilers and build drivers.
    (
        re.compile(
            r"(?:^|[\s;&|])(?:gcc|g\+\+|clang|clang\+\+|cc|ld)\b"
            r"|\bmake\b"
            r"|\bcmake\b"
            r"|\bcargo\s+build\b"
            r"|\bgo\s+build\b"
            r"|\brustc\b"
            r"|\bjavac\b"
            r"|\bswiftc\b"
            r"|\btsc\b"
        ),
        CAPABILITY_COMPILATION,
        "Command compiles or links code",
    ),
    # Network bind — opening a listener on a local port.
    (
        re.compile(
            r"\bnc\b(?=[^|]*\s-l)"
            r"|\bncat\b(?=[^|]*\s-l)"
            r"|\bsocat\b[^|]*\bLISTEN\b"
            r"|\bpython3?\s+-m\s+http\.server\b"
            r"|\bpython3?\s+-m\s+SimpleHTTPServer\b"
            r"|\bphp\s+-S\b"
            r"|\bruby\s+-run\s+-e\s+httpd\b"
        ),
        CAPABILITY_NETWORK_BIND,
        "Command binds a local network listener",
    ),
    # Background execution — persists beyond the current shell.
    (
        re.compile(
            r"\bnohup\b"
            r"|\bdisown\b"
            r"|\bsetsid\b"
            r"|\bscreen\s+-d(?:m)?\b"
            r"|\btmux\s+new-session\s+-d\b"
            r"|[^&|]&\s*(?:$|[;\n])"
        ),
        CAPABILITY_BACKGROUND_EXEC,
        "Command runs a process in the background",
    ),
    # Download-and-execute — fetch remote payload piped into a shell.
    # (Note: catastrophic subset of this is already caught by step 3.
    # Here we tag the capability for any remote-fetch-then-execute shape.)
    (
        re.compile(
            r"\b(?:curl|wget|fetch|aria2c)\b[^|]*\|\s*"
            r"(?:sh|bash|zsh|dash|python3?|perl|ruby|node)\b"
        ),
        CAPABILITY_DOWNLOAD_AND_EXEC,
        "Command downloads a remote payload and pipes it to an interpreter",
    ),
    # Generic spawn — shells out via common indirection verbs.
    (
        re.compile(
            r"\bxargs\b"
            r"|\bfind\b[^|]*-exec\b"
            r"|\bsudo\b"
            r"|\bsu\b(?=\s+-)"
            r"|\bssh\b"
            r"|\bdocker\s+(?:run|exec)\b"
            r"|\bkubectl\s+exec\b"
        ),
        CAPABILITY_SPAWNS_PROCESS,
        "Command spawns or delegates to another process",
    ),
)


def classify_capabilities(
    command: str,
    *,
    sub_commands: tuple[str, ...] = (),
    indirections: tuple[str, ...] = (),
) -> tuple[tuple[str, ...], tuple[Signal, ...]]:
    """Classify *command* into zero or more capability tags.

    Returns (capabilities, signals) where capabilities is a tuple of
    unique capability IDs and signals is the corresponding Signal list
    (one per distinct capability).  Scans the normalized command,
    sub-commands, and indirection payloads so hidden shells still pay
    their tax.
    """
    if not command:
        return (), ()

    haystacks: list[str] = [command]
    haystacks.extend(sub_commands)
    haystacks.extend(indirections)

    seen: dict[str, Signal] = {}
    for rx, cap_id, desc in _RULES:
        for text in haystacks:
            m = rx.search(text)
            if m is None:
                continue
            if cap_id in seen:
                break
            seen[cap_id] = Signal(
                check="capability",
                signal_id=cap_id,
                description=desc,
                evidence=m.group()[:120],
            )
            break

    capabilities = tuple(seen.keys())
    signals = tuple(seen.values())
    return capabilities, signals
