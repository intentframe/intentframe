"""Content-aware language detection for file bodies.

Used by the code inspector and the edge resolver to decide which
analyzer to dispatch for a resolved file.  Sniffing runs in three
ordered layers:

    1. file extension (authoritative when present)
    2. shebang line                 (authoritative when present)
    3. content heuristics           (fallback)

Magic-byte detection is a separate concern handled by
:func:`detect_binary`, which runs before text-based sniffing so binary
artefacts can be flagged without attempting to decode them.

Return values are narrow, deterministic strings:

    "python"   "shell"   "javascript"   "typescript"   "ruby"   "perl"
    "applescript"   "binary"   "unknown"

The caller decides whether the returned language is in scope for its
analyzer dispatch (see :mod:`command_shield.code_inspector`).
"""

from __future__ import annotations

import re

# ── Extension map (authoritative when present) ───────────────────────

_EXTENSION_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".pyw": "python",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".ksh": "shell",
    ".dash": "shell",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".rb": "ruby",
    ".pl": "perl",
    ".scpt": "applescript",
    ".applescript": "applescript",
}


# ── Shebang patterns ─────────────────────────────────────────────────

_SHEBANG_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^#!.*\bpython[0-9.]*\b"), "python"),
    (re.compile(r"^#!.*\bnode\b"), "javascript"),
    (re.compile(r"^#!.*\bruby\b"), "ruby"),
    (re.compile(r"^#!.*\bperl\b"), "perl"),
    (re.compile(r"^#!.*\bosascript\b"), "applescript"),
    # Shell family is catch-all — bash, sh, zsh, dash, ksh, /bin/sh.
    (re.compile(r"^#!.*\b(?:bash|sh|zsh|ksh|dash|ash|fish)\b"), "shell"),
    # Generic `/usr/bin/env <foo>` fallbacks that didn't match above.
    (re.compile(r"^#!.*\benv\s+python"), "python"),
    (re.compile(r"^#!.*\benv\s+node"), "javascript"),
    (re.compile(r"^#!.*\benv\s+ruby"), "ruby"),
    (re.compile(r"^#!.*\benv\s+perl"), "perl"),
    (re.compile(r"^#!.*\benv\s+(?:bash|sh|zsh|ksh|dash|ash|fish)"), "shell"),
)


# ── Content heuristics (fallback) ────────────────────────────────────
#
# These run only when extension and shebang are both inconclusive.
# Each language has a set of signature patterns; we score every
# candidate and pick the highest-scoring one above a minimum floor.
# Ties → "unknown" (intentionally refuse to guess rather than mislead).

_PYTHON_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*import\s+\w", re.MULTILINE),
    re.compile(r"^\s*from\s+\w[\w.]*\s+import\b", re.MULTILINE),
    re.compile(r"^\s*def\s+\w+\s*\(", re.MULTILINE),
    re.compile(r"^\s*async\s+def\s+\w+\s*\(", re.MULTILINE),
    re.compile(r"^\s*class\s+\w+[\s(:]", re.MULTILINE),
    re.compile(r"^\s*if\s+__name__\s*==\s*[\"']__main__[\"']"),
    re.compile(r"\bprint\s*\("),
)

_SHELL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*set\s+-[euxoEo]+\b", re.MULTILINE),
    re.compile(r"^\s*if\s+\[\s*[^\]]+\]\s*;\s*then\b", re.MULTILINE),
    re.compile(r"^\s*if\s+\[\[\s*[^\]]+\]\]\s*;\s*then\b", re.MULTILINE),
    re.compile(r"^\s*for\s+\w+\s+in\s+[^;]+;\s*do\b", re.MULTILINE),
    re.compile(r"^\s*function\s+\w+\s*(?:\(\))?\s*\{", re.MULTILINE),
    re.compile(r"^\s*\w+\s*=\s*(?:\"[^\"]*\"|'[^']*'|\S+)\s*$", re.MULTILINE),
    re.compile(r"\$\{?\w+\}?"),
    re.compile(r"\becho\s+[^\n]"),
)

_JAVASCRIPT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(?:const|let|var)\s+\w+\s*=", re.MULTILINE),
    re.compile(r"^\s*function\s+\w+\s*\(", re.MULTILINE),
    re.compile(r"^\s*import\s+.+\s+from\s+[\"']", re.MULTILINE),
    re.compile(r"^\s*require\s*\([\"']", re.MULTILINE),
    re.compile(r"=>\s*[\{\(]"),
    re.compile(r"\bconsole\.(?:log|error|warn)\s*\("),
)

_RUBY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*require\s+[\"']", re.MULTILINE),
    re.compile(r"^\s*def\s+\w+(?:\s|$)", re.MULTILINE),
    re.compile(r"^\s*end\s*$", re.MULTILINE),
    re.compile(r"\bputs\s+"),
)

_LANG_PATTERN_SETS: dict[str, tuple[re.Pattern[str], ...]] = {
    "python": _PYTHON_PATTERNS,
    "shell": _SHELL_PATTERNS,
    "javascript": _JAVASCRIPT_PATTERNS,
    "ruby": _RUBY_PATTERNS,
}

# Minimum score needed before we commit to a language (avoids
# guessing on a 2-line snippet that happens to contain `echo`).
_MIN_SCORE: int = 2


# ── Binary / magic-byte detection ────────────────────────────────────

_MAGIC_BYTES: tuple[tuple[bytes, str], ...] = (
    (b"\x7fELF", "binary"),                  # ELF (Linux/BSD)
    (b"\xcf\xfa\xed\xfe", "binary"),         # Mach-O 64
    (b"\xce\xfa\xed\xfe", "binary"),         # Mach-O 32
    (b"\xca\xfe\xba\xbe", "binary"),         # Mach-O fat / Java class
    (b"MZ", "binary"),                       # PE (Windows)
    (b"PK\x03\x04", "binary"),               # zip / jar / wheel
    (b"\x1f\x8b", "binary"),                 # gzip
    (b"BZh", "binary"),                      # bzip2
    (b"\xfd7zXZ\x00", "binary"),             # xz
    (b"\x89PNG\r\n\x1a\n", "binary"),        # PNG
    (b"\xff\xd8\xff", "binary"),             # JPEG
    (b"%PDF-", "binary"),                    # PDF
)


def detect_binary(data: bytes) -> bool:
    """Return True if *data* looks like a binary artefact.

    Uses magic-byte prefix match first (authoritative), falls back to
    a null-byte density heuristic for the first 8 KiB — text files
    almost never contain NUL, binaries frequently do.
    """
    if not data:
        return False
    for prefix, _ in _MAGIC_BYTES:
        if data.startswith(prefix):
            return True
    # High-signal heuristic: any NUL byte in the first 8 KiB of a
    # supposedly textual script file is a strong binary marker.
    head = data[:8192]
    if b"\x00" in head:
        return True
    return False


# ── Public API ───────────────────────────────────────────────────────


def language_from_extension(path: str | None) -> str | None:
    """Map a file path to a language via its extension.  None if no match."""
    if not path:
        return None
    lower = path.lower()
    for ext, lang in _EXTENSION_LANGUAGE.items():
        if lower.endswith(ext):
            return lang
    return None


def language_from_shebang(source: str) -> str | None:
    """Detect language from the first-line shebang.  None if no shebang."""
    if not source or not source.startswith("#!"):
        return None
    first_line = source.split("\n", 1)[0]
    for rx, lang in _SHEBANG_RULES:
        if rx.search(first_line):
            return lang
    return None


def language_from_content(source: str) -> str | None:
    """Heuristic content sniffing.  Returns None when ambiguous."""
    if not source:
        return None

    scores: dict[str, int] = {}
    for lang, patterns in _LANG_PATTERN_SETS.items():
        score = 0
        for rx in patterns:
            if rx.search(source):
                score += 1
        if score:
            scores[lang] = score

    if not scores:
        return None

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top_lang, top_score = ranked[0]
    if top_score < _MIN_SCORE:
        return None
    # Reject ties with the runner-up — we won't guess.
    if len(ranked) > 1 and ranked[1][1] == top_score:
        return None
    return top_lang


def sniff_language(
    source: str,
    *,
    path: str | None = None,
    use_content: bool = True,
) -> str:
    """Decide the language of *source* using ext → shebang → content.

    Returns one of the language strings from the module docstring, or
    "unknown" when no rule produced a confident answer.  Never raises.

    When ``path`` is supplied, its extension takes priority (most
    authoritative signal available at zero cost).  Shebang inspection
    runs next.  Content heuristics fire only when both are
    inconclusive AND ``use_content`` is True.
    """
    ext_lang = language_from_extension(path)
    if ext_lang:
        return ext_lang

    shebang_lang = language_from_shebang(source)
    if shebang_lang:
        return shebang_lang

    if use_content:
        content_lang = language_from_content(source)
        if content_lang:
            return content_lang

    return "unknown"


__all__ = [
    "detect_binary",
    "language_from_content",
    "language_from_extension",
    "language_from_shebang",
    "sniff_language",
]
