"""Clean environment builder for subprocess execution.

Filters os.environ to a safe set of keys, preventing secret leakage
(AWS_SECRET_ACCESS_KEY, OPENAI_API_KEY, DATABASE_URL, etc.) into
agent-spawned commands.
"""

from __future__ import annotations

import os

_SAFE_ENV_KEYS = frozenset({
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "SHELL",
    "TMPDIR",
    "XPC_FLAGS",
    "XPC_SERVICE_NAME",
    "__CF_USER_TEXT_ENCODING",
})


def clean_env() -> dict[str, str]:
    """Return a filtered copy of os.environ with only safe keys."""
    return {k: v for k, v in os.environ.items() if k in _SAFE_ENV_KEYS}
