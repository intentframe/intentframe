"""Executor-venv resolution for sandboxed RUN_COMMAND.

The executor ships with its own Python venv (default
``~/.intentframe-venvs/executor``) so that agent-driven ``pip install X`` and
script execution happen in an isolated interpreter — never in the source-code
venv under ``<repo>/.venv`` and never in user site-packages.

The venv lives at ``~/.intentframe-venvs/`` rather than under ``~/.intentframe/``
because the latter is in ``NON_NEGOTIABLE_DENY_ACCESS`` (it holds runtime
internals — audit logs, SQLite DBs, PID/socket files, credential-adjacent
state) and every template including ``UNRESTRICTED`` denies reads under that
subpath. Putting the venv inside that deny zone would make ``exec`` of the
interpreter fail with "Operation not permitted", since the kernel can't
read the binary. ``~/.intentframe-venvs/`` is a sibling directory outside
that perimeter, reserved for agent-reachable execution environments
(executor venv now, per-agent venvs later).

The sandbox engine takes an absolute venv path and adds ``VIRTUAL_ENV``,
``PATH`` prepend, and ``PYTHONNOUSERSITE=1`` to the subprocess environment.
Path resolution lives here, not in the engine, so the engine stays pure
plumbing and the identity-sensitive part (``~`` expansion under root vs.
normal user) has one well-defined home.

Resolution is identity-aware so the design works whether the executor runs
as a regular user or as root:

    1. ``SandboxConfig.executor_venv_path`` — if set, that's the path.
       ``~`` in the configured value expands against the *owning* user's
       HOME, not whatever HOME the process happens to have.
    2. ``SUDO_USER`` env var — we were elevated via sudo; the owning user
       is ``$SUDO_USER`` and ``~`` means their HOME.
    3. Normal uid — the running process's own HOME.
    4. Bare root with no ``SUDO_USER`` — no well-defined owning user;
       returns ``None`` and the caller (main.py) fails loud when
       ``executor_venv_required=True``.

The engine never expands ``~`` itself. All paths it sees are absolute and
realpath-resolved.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from executor_sdk import owner_home

from .config import SandboxConfig

logger = logging.getLogger(__name__)

_DEFAULT_VENV_RELATIVE = ".intentframe-venvs/executor"


def resolve_executor_venv_path(config: SandboxConfig) -> str | None:
    """Resolve the absolute, realpath'd executor-venv path.

    Does not check whether the venv exists on disk. Use
    :func:`validate_executor_venv` for that.

    Returns ``None`` when no path can be resolved — happens only when the
    executor is running as bare root with no ``SUDO_USER`` and
    ``SandboxConfig.executor_venv_path`` is unset. In that case the caller
    decides whether to fail (``executor_venv_required=True``) or proceed
    without a venv override (falls back to system python3).
    """
    configured = config.executor_venv_path
    if configured:
        if configured.startswith("~"):
            home = owner_home()
            if home is None:
                logger.error(
                    "executor_venv_path=%r uses ~ but running as bare root "
                    "with no SUDO_USER; cannot expand",
                    configured,
                )
                return None
            configured = home + configured[1:]
        if not os.path.isabs(configured):
            logger.error(
                "executor_venv_path=%r is not absolute after ~ expansion; "
                "refusing to resolve",
                configured,
            )
            return None
        return os.path.realpath(configured)

    home = owner_home()
    if home is None:
        return None
    return os.path.realpath(os.path.join(home, _DEFAULT_VENV_RELATIVE))


def validate_executor_venv(path: str) -> bool:
    """Return True if *path* points to a usable venv.

    A usable venv has an executable ``bin/python3`` (or ``bin/python`` on
    some distros). We don't validate the interpreter version — that's a
    provisioning concern handled by ``intentframe_setup.sh``.
    """
    p = Path(path)
    python3 = p / "bin" / "python3"
    python = p / "bin" / "python"
    return (python3.is_file() and os.access(python3, os.X_OK)) or (
        python.is_file() and os.access(python, os.X_OK)
    )
