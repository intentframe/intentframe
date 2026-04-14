"""Deterministic command capability classifier.

Independent module -- no imports from command_shield.  Inspects shell
command syntax to infer the minimum set of runtime capabilities required
(file read, file write, network, etc.).

Design rule: *over-approximate*, never under-approximate.  If unsure,
classify broader.  If parsing fails, mark the command opaque.
"""

from __future__ import annotations

import re
import shlex

from executor.sandbox.capabilities import Capability, CapabilityReport

# ---------------------------------------------------------------------------
# Tool / verb tables
# ---------------------------------------------------------------------------

_FILE_READ_VERBS = frozenset({
    "cat", "less", "more", "head", "tail", "grep", "egrep", "fgrep", "rg",
    "ag", "ack", "sed", "awk", "wc", "sort", "uniq", "diff", "cmp", "file",
    "stat", "strings", "xxd", "hexdump", "od", "bat",
})

_FILE_WRITE_VERBS = frozenset({
    "tee", "cp", "mv", "rm", "rmdir", "mkdir", "mktemp", "touch", "chmod",
    "chown", "chgrp", "ln", "install", "rsync", "tar", "unzip", "zip",
    "gzip", "gunzip", "bzip2", "xz",
})

_NETWORK_OUTBOUND_VERBS = frozenset({
    "curl", "wget", "scp", "sftp", "ssh", "rsync", "ftp",
    "git", "svn", "hg",
    "docker", "podman",
})

_NETWORK_BIND_PATTERNS = (
    re.compile(r"\bpython3?\s+(?:-\w\s+)*-m\s+http\.server\b"),
    re.compile(r"\bnc\s+.*-l\b"),
    re.compile(r"\bncat\s+.*-l\b"),
    re.compile(r"\bsocat\s+TCP-LISTEN\b", re.IGNORECASE),
    re.compile(r"\bhttp-server\b"),
    re.compile(r"\bnode\s+.*(?:express|server|listen)\b"),
)

_PACKAGE_INSTALL_PATTERNS = (
    re.compile(r"\bpip3?\s+install\b"),
    re.compile(r"\bnpm\s+install\b"),
    re.compile(r"\byarn\s+add\b"),
    re.compile(r"\bbrew\s+install\b"),
    re.compile(r"\bapt(?:-get)?\s+install\b"),
    re.compile(r"\bdnf\s+install\b"),
    re.compile(r"\bpacman\s+-S\b"),
    re.compile(r"\bcargo\s+install\b"),
    re.compile(r"\bgo\s+install\b"),
    re.compile(r"\bgem\s+install\b"),
    re.compile(r"\buv\s+(?:pip\s+)?install\b"),
)

_BACKGROUND_TOKENS = frozenset({"nohup", "disown", "setsid"})

_PROCESS_SIGNAL_VERBS = frozenset({"kill", "pkill", "killall", "xkill"})

_INTERPRETERS = frozenset({
    "python", "python3", "python2",
    "perl", "ruby", "node",
    "bash", "sh", "zsh", "dash",
    "osascript",
})

_INLINE_FLAGS = frozenset({"-c", "-e", "--eval"})

# Operators / constructs that make classification untrustworthy
_OPAQUE_PATTERNS = (
    re.compile(r"\$\("),                          # command substitution $(...)
    re.compile(r"`"),                              # backtick substitution
    re.compile(r"\beval\b"),                       # eval
    re.compile(r"\bsource\b"),                     # source / dot
    re.compile(r"^\.\s"),                          # dot-space (source)
    re.compile(r"\bbase64\b.*\|\s*(?:sh|bash)\b"), # base64 | sh
    re.compile(r"\bexec\b"),                       # exec
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify(command: str) -> CapabilityReport:
    """Classify *command* into a set of required capabilities."""
    if not command or not command.strip():
        return CapabilityReport(capabilities=frozenset())

    caps: set[Capability] = set()
    opaque = False

    # Check for opaque constructs on the raw command first
    for pat in _OPAQUE_PATTERNS:
        if pat.search(command):
            opaque = True
            break

    # Split on pipes -- classify each segment independently
    segments = _split_pipeline(command)
    for segment in segments:
        seg_caps, seg_opaque = _classify_segment(segment)
        caps.update(seg_caps)
        if seg_opaque:
            opaque = True

    # Trailing & means background process
    stripped = command.rstrip()
    if stripped.endswith("&") and not stripped.endswith("&&"):
        caps.add(Capability.BACKGROUND_PROCESS)

    return CapabilityReport(capabilities=frozenset(caps), opaque=opaque)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _split_pipeline(command: str) -> list[str]:
    """Split a command on un-escaped pipe operators.

    Handles ``|`` but not ``||`` (logical-or).  Very conservative: if the
    split looks wrong we return the whole command as a single segment.
    """
    segments: list[str] = []
    current: list[str] = []
    i = 0
    chars = command
    while i < len(chars):
        ch = chars[i]
        if ch == "|" and (i + 1 >= len(chars) or chars[i + 1] != "|"):
            segments.append("".join(current).strip())
            current = []
            i += 1
            continue
        if ch == "|" and i + 1 < len(chars) and chars[i + 1] == "|":
            current.append("||")
            i += 2
            continue
        current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail:
        segments.append(tail)
    return segments or [command]


def _classify_segment(segment: str) -> tuple[set[Capability], bool]:
    """Classify a single pipeline segment."""
    caps: set[Capability] = set()
    opaque = False

    try:
        tokens = shlex.split(segment)
    except ValueError:
        return caps, True  # unparseable -> opaque

    if not tokens:
        return caps, False

    verb = tokens[0].split("/")[-1]  # strip path prefix

    # --- Redirections (scan raw string) ---
    if re.search(r"<\s*\S", segment):
        caps.add(Capability.FILE_READ)
    if re.search(r">{1,2}\s*\S", segment):
        caps.add(Capability.FILE_WRITE)

    # --- Verb matching ---
    if verb in _FILE_READ_VERBS:
        caps.add(Capability.FILE_READ)
    if verb in _FILE_WRITE_VERBS:
        caps.add(Capability.FILE_WRITE)
    if verb in _NETWORK_OUTBOUND_VERBS:
        caps.add(Capability.NETWORK_OUTBOUND)
    if verb in _PROCESS_SIGNAL_VERBS:
        caps.add(Capability.PROCESS_SIGNAL)
    if verb in _BACKGROUND_TOKENS:
        caps.add(Capability.BACKGROUND_PROCESS)

    # --- Network bind patterns (multi-token) ---
    for pat in _NETWORK_BIND_PATTERNS:
        if pat.search(segment):
            caps.add(Capability.NETWORK_BIND)
            break

    # --- Package install patterns (multi-token) ---
    for pat in _PACKAGE_INSTALL_PATTERNS:
        if pat.search(segment):
            caps.add(Capability.PACKAGE_INSTALL)
            caps.add(Capability.NETWORK_OUTBOUND)
            break

    # --- Interpreter indirection (python -c, bash -c, etc.) ---
    if verb in _INTERPRETERS:
        for i, tok in enumerate(tokens[1:], start=1):
            if tok in _INLINE_FLAGS and i + 1 < len(tokens):
                opaque = True
                break
        # Running a script file is also opaque
        if not opaque and len(tokens) >= 2 and not tokens[1].startswith("-"):
            opaque = True

    # --- Binary / script execution (check raw token, not stripped verb) ---
    raw_verb = tokens[0]
    if raw_verb.startswith("./") or raw_verb.startswith("/"):
        opaque = True

    return caps, opaque
