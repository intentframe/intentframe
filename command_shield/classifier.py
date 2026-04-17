"""Capability classification — deterministic regex/structural tags.

Step 7 of the inspection pipeline.  Works on any command string
regardless of language support; tags describe *what the command can
do*, not *whether it is allowed*.  Consumer (Guardian/AE) decides what
to do with each capability.

Emitted capability IDs (stable contract).  Tags marked `:<suffix>` are
refined so that policy can allow/deny at the tool grain (e.g. allow
`capability:package_install:pip` but deny `capability:package_install:apt`):

    capability:package_install:pip       — pip / pip3 / pipx / uv / poetry / conda / mamba
    capability:package_install:npm       — npm / pnpm / yarn
    capability:package_install:brew      — Homebrew
    capability:package_install:apt       — apt / apt-get (Debian / Ubuntu)
    capability:package_install:yum       — yum (RHEL / CentOS)
    capability:package_install:dnf       — dnf (Fedora)
    capability:package_install:pacman    — pacman (Arch)
    capability:package_install:apk       — apk (Alpine)
    capability:package_install:gem       — gem (Ruby)
    capability:package_install:cargo     — cargo install (Rust)
    capability:package_install:go        — go install (Go)
    capability:package_install:composer  — composer install / require (PHP)

    capability:script_execution:python       — `python foo.py` / `python3 foo.py`
    capability:script_execution:node         — `node app.js` / `.mjs` / `.cjs`
    capability:script_execution:ruby         — `ruby foo.rb`
    capability:script_execution:perl         — `perl foo.pl`
    capability:script_execution:shell        — `bash foo.sh` / `sh` / `zsh` / `ksh` / `dash`
    capability:script_execution:local_binary — `./foo` / `./bin/tool`

    capability:compilation       — compiles/links code (gcc/clang/make/...)
    capability:network_bind      — binds a local network port/listener
    capability:background_exec   — backgrounds a process (nohup/&/screen)
    capability:download_and_exec — fetches a remote payload and pipes to a shell
    capability:binary_download   — fetches a remote payload to disk (no shell pipe)
    capability:process_signal    — sends signals to processes (kill/pkill/killall)
    capability:spawns_process    — shells out / spawns a child process

Each hit produces a Signal with check="capability" and signal_id set to
the capability tag.  Multiple capabilities per command are expected;
they are not mutually exclusive.  Policy can match exact tags or use
prefix matching on the `:` boundary (e.g. `capability:package_install:*`).
"""

from __future__ import annotations

import re

from command_shield.verdict import Signal

# ── Capability IDs ───────────────────────────────────────────────────

CAPABILITY_PACKAGE_INSTALL = "capability:package_install"
CAPABILITY_COMPILATION = "capability:compilation"
CAPABILITY_SCRIPT_EXECUTION = "capability:script_execution"
CAPABILITY_NETWORK_BIND = "capability:network_bind"
CAPABILITY_BACKGROUND_EXEC = "capability:background_exec"
CAPABILITY_DOWNLOAD_AND_EXEC = "capability:download_and_exec"
CAPABILITY_BINARY_DOWNLOAD = "capability:binary_download"
CAPABILITY_PROCESS_SIGNAL = "capability:process_signal"
CAPABILITY_SPAWNS_PROCESS = "capability:spawns_process"


# ── Detection rules ─────────────────────────────────────────────────
#
# Each rule is (regex, capability_id, description).
# Regexes run against the normalized command string and against each
# indirection payload.  Rules are intentionally conservative — false
# negatives are preferable to false positives, since the verdict comes
# from step 3 patterns and these signals are advisory.

# Refined rules: one per manager so policy can allow/deny at tool grain.
# Order matters only within a capability family (first match wins per tag
# in `seen`); across capabilities all independent rules are evaluated.
_PACKAGE_INSTALL_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:pip3?|pipx|uv|poetry|conda|mamba)\s+install\b"), "pip"),
    (re.compile(r"\b(?:npm|pnpm)\s+(?:i|install|add)\b|\byarn\s+(?:add|install)\b"), "npm"),
    (re.compile(r"\bbrew\s+(?:install|reinstall|upgrade)\b"), "brew"),
    (re.compile(r"\bapt(?:-get)?\s+(?:install|upgrade)\b"), "apt"),
    (re.compile(r"\byum\s+(?:install|update)\b"), "yum"),
    (re.compile(r"\bdnf\s+(?:install|upgrade)\b"), "dnf"),
    (re.compile(r"\bpacman\s+-S\b"), "pacman"),
    (re.compile(r"\bapk\s+add\b"), "apk"),
    (re.compile(r"\bgem\s+install\b"), "gem"),
    (re.compile(r"\bcargo\s+install\b"), "cargo"),
    (re.compile(r"\bgo\s+install\b"), "go"),
    (re.compile(r"\bcomposer\s+(?:install|require)\b"), "composer"),
)

# Refined rules: one per interpreter.  Excludes inline `-c` / `-e` /
# `--eval` forms (those are classified as inline code by the language
# detector, not as script-file execution).
_SCRIPT_EXECUTION_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bpython3?\s+[^|;&]*\.py\b"), "python"),
    (re.compile(r"\bnode\s+[^|;&]*\.(?:js|mjs|cjs)\b"), "node"),
    (re.compile(r"\bruby\s+[^|;&]*\.rb\b"), "ruby"),
    (re.compile(r"\bperl\s+[^|;&]*\.pl\b"), "perl"),
    (re.compile(r"\b(?:bash|sh|zsh|ksh|dash)\s+[^|;&]*\.(?:sh|bash|zsh)\b"), "shell"),
    (re.compile(r"(?:^|[\s;&|])\./[\w.][\w./-]*"), "local_binary"),
)


def _expand_refined(
    rules: tuple[tuple[re.Pattern[str], str], ...],
    base: str,
    desc_template: str,
) -> tuple[tuple[re.Pattern[str], str, str], ...]:
    return tuple(
        (rx, f"{base}:{suffix}", desc_template.format(suffix=suffix))
        for rx, suffix in rules
    )


_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    # Refined: package installation (one rule per manager).
    *_expand_refined(
        _PACKAGE_INSTALL_RULES,
        CAPABILITY_PACKAGE_INSTALL,
        "Command installs packages via {suffix}",
    ),
    # Refined: script execution (one rule per interpreter).
    *_expand_refined(
        _SCRIPT_EXECUTION_RULES,
        CAPABILITY_SCRIPT_EXECUTION,
        "Command executes a {suffix} script or local binary",
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
    # Binary download — fetches a remote payload to disk without piping
    # it straight to a shell.  The pipe-to-shell variant is already tagged
    # as download_and_exec above; both may fire together for
    # `curl -O url | sh` shapes, which is intentional.
    (
        re.compile(
            r"\bcurl\b[^|]*\s-[OoLJ]\b"
            r"|\bwget\b(?![^|]*\|\s*(?:sh|bash|zsh|dash|python3?|perl|ruby|node))"
            r"|\baria2c\b"
        ),
        CAPABILITY_BINARY_DOWNLOAD,
        "Command downloads a remote payload to disk",
    ),
    # Process signaling — kill/pkill/killall family.
    (
        re.compile(
            r"\bkill\s+-\w*\b"
            r"|\bkill\s+-?\d+\b"
            r"|\bkillall\b"
            r"|\bpkill\b"
            r"|\bskill\b"
        ),
        CAPABILITY_PROCESS_SIGNAL,
        "Command sends signals to processes",
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
