"""Language detection for commands.

Determines the programming language, interpreter, and
whether code is inline (-c/-e) or file-based from a command string.
"""

from __future__ import annotations

import shlex

from command_shield.review.types import LanguageInfo

_INTERPRETER_LANGUAGE: dict[str, str] = {
    "python": "python",
    "python3": "python",
    "python2": "python",
    "bash": "shell",
    "sh": "shell",
    "zsh": "shell",
    "dash": "shell",
    "ksh": "shell",
    "node": "javascript",
    "deno": "javascript",
    "bun": "javascript",
    "perl": "perl",
    "ruby": "ruby",
    "osascript": "applescript",
    "java": "java",
    "go": "go",
    "dotnet": "dotnet",
    "php": "php",
    "lua": "lua",
    "Rscript": "r",
    "julia": "julia",
    "swift": "swift",
    "awk": "awk",
    "gawk": "awk",
    "mawk": "awk",
}

_INLINE_FLAGS = frozenset({"-c", "-e", "--eval"})

_EXTENSION_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "javascript",
    ".pl": "perl",
    ".rb": "ruby",
    ".scpt": "applescript",
    ".jar": "java",
    ".class": "java",
    ".dll": "dotnet",
    ".php": "php",
    ".lua": "lua",
    ".R": "r",
    ".r": "r",
    ".jl": "julia",
    ".swift": "swift",
}


def detect_language(command: str) -> LanguageInfo:
    """Detect language / interpreter from a command string.

    Returns LanguageInfo with language, interpreter, and whether
    the code is inline or file-based.  Never raises.
    """
    if not command or not command.strip():
        return LanguageInfo(
            language="shell", interpreter=None,
            is_inline=False, is_file_exec=False,
        )

    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    if not tokens:
        return LanguageInfo(
            language="shell", interpreter=None,
            is_inline=False, is_file_exec=False,
        )

    verb = tokens[0].split("/")[-1]

    if verb in _INTERPRETER_LANGUAGE:
        lang = _INTERPRETER_LANGUAGE[verb]
        is_inline = False
        is_file_exec = False

        for i, tok in enumerate(tokens[1:], start=1):
            if tok in _INLINE_FLAGS and i + 1 <= len(tokens) - 1:
                is_inline = True
                break
            if not tok.startswith("-"):
                for ext, ext_lang in _EXTENSION_LANGUAGE.items():
                    if tok.endswith(ext):
                        is_file_exec = True
                        lang = ext_lang
                        break
                if not is_file_exec:
                    is_file_exec = True
                break

        return LanguageInfo(
            language=lang, interpreter=verb,
            is_inline=is_inline, is_file_exec=is_file_exec,
        )

    # Not a known interpreter — treat as a shell tool / utility
    return LanguageInfo(
        language="shell", interpreter=verb,
        is_inline=False, is_file_exec=False,
    )


def extract_inline_code(command: str, language_info: LanguageInfo) -> str | None:
    """Extract inline code payload from a command like `python -c "code"`.

    Returns None if the command has no inline code.
    """
    if not language_info.is_inline:
        return None

    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    for i, tok in enumerate(tokens):
        if tok in _INLINE_FLAGS and i + 1 < len(tokens):
            return tokens[i + 1]

    return None
