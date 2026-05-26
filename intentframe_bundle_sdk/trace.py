"""Bundle SDK lifecycle trace — internal audit surface for the bundle-runtime.

One JSON line per hook invocation (or deliberate skip) is written to
``~/.intentframe/logs/bundle-sdk.log``, following the same per-process log
convention as ``intentframe-core.log``, ``executor.log``, etc.

This module is the Bundle SDK's *own* observability layer and is completely
separate from :class:`~intentframe_bundle_sdk.types.BundleDeterministicResult`
(the external API surface that ``intentframe-core`` receives).  An auditor
queries the bundle-runtime process's own log; no trace data leaks into the
wire format.

Architecture note
-----------------
Today the SDK runs in-process inside ``intentframe-core``, so the trace logger
writes alongside the other per-process log files.  When bundle-runtime becomes
its own UDS process the trace file moves with it — no changes to this module.

Lanes
-----
``boot``       validate_constraints — called once at policy-seed load time
``lifecycle``  startup / aclose — called at server start / graceful shutdown
``handshake``  onboarding_guardrails — called when building the system prompt
``runtime``    every hook inside DeterministicRunner.run_action_bundle

Log format
----------
Each record is one minified JSON line::

    {"ts": "...", "lane": "runtime", "trace_id": "...", "phase": "enrich",
     "skipped": false, "elapsed_ms": 1.2,
     "inputs": {"intent": {...}, "permission": {...}, ...},
     "output": {...}, "raised": null}

Usage
-----
Only SDK-internal modules (runner, lifecycle, loader, onboarding) call the
helpers here.  External code that needs a non-default log directory may call
``intentframe_bundle_sdk.configure_trace_logging(log_dir)`` once at startup.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import logging.handlers
import os
import time
from pathlib import Path
from typing import Any

from intentframe_bundle_sdk.audit_dump import audit_dump


# ---------------------------------------------------------------------------
# Logger — one rotating file per SDK process
# ---------------------------------------------------------------------------

_LOGGER_NAME = "bundle_sdk.trace"
_LOG_FILENAME = "bundle-sdk.log"
_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_LOG_BACKUP_COUNT = 3

_trace_logger: logging.Logger = logging.getLogger(_LOGGER_NAME)
_handler_installed: bool = False


def _default_log_dir() -> Path:
    log_dir = os.environ.get("INTENTFRAME_LOG_DIR")
    if log_dir:
        return Path(log_dir)
    return Path(os.path.expanduser("~/.intentframe/logs"))


def configure_trace_logging(log_dir: Path | None = None) -> None:
    """Install a :class:`logging.handlers.RotatingFileHandler` on the trace logger.

    Idempotent — safe to call multiple times; subsequent calls are no-ops once
    the handler is installed.  Called automatically on the first
    ``traced_call`` / ``traced_acall`` / ``emit_skip`` if the handler has not
    been set up yet.

    ``log_dir`` defaults to ``~/.intentframe/logs`` or ``$INTENTFRAME_LOG_DIR``
    when set, matching every other IntentFrame service process.
    """
    global _handler_installed
    if _handler_installed:
        return

    resolved = (log_dir or _default_log_dir()).expanduser().resolve()
    active_handler: logging.Handler
    try:
        resolved.mkdir(parents=True, exist_ok=True)
        log_path = resolved / _LOG_FILENAME
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        file_handler.setLevel(logging.DEBUG)
        active_handler = file_handler
    except OSError:
        # Restricted environments (sandboxes, CI without home dir write access)
        # degrade to a no-op rather than crashing at import / first hook call.
        active_handler = logging.NullHandler()

    _trace_logger.setLevel(logging.DEBUG)
    _trace_logger.addHandler(active_handler)
    # Prevent records from leaking into the root logger (intentframe-core.log).
    _trace_logger.propagate = False
    _handler_installed = True


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _bind_inputs(hook_fn: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Bind positional and keyword args to their parameter names, then audit_dump each."""
    try:
        sig = inspect.signature(hook_fn)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        return {name: audit_dump(val) for name, val in bound.arguments.items()}
    except Exception:
        return {
            "_args": [audit_dump(a) for a in args],
            "_kwargs": {k: audit_dump(v) for k, v in kwargs.items()},
        }


def _emit(
    *,
    lane: str,
    trace_id: str,
    phase: str,
    inputs: dict[str, Any] | None,
    output: Any = None,
    raised: str | None = None,
    elapsed_ms: float | None = None,
    skipped: bool = False,
    skipped_reason: str | None = None,
) -> None:
    if not _handler_installed:
        configure_trace_logging()
    payload: dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "lane": lane,
        "trace_id": trace_id,
        "phase": phase,
        "skipped": skipped,
        "skipped_reason": skipped_reason,
        "elapsed_ms": round(elapsed_ms, 3) if elapsed_ms is not None else None,
        "inputs": inputs,
        "output": output,
        "raised": raised,
    }
    _trace_logger.debug(json.dumps(payload, default=str))


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def emit_skip(
    *,
    lane: str,
    trace_id: str,
    phase: str,
    reason: str,
) -> None:
    """Emit a trace record for a hook that was deliberately not called."""
    _emit(
        lane=lane,
        trace_id=trace_id,
        phase=phase,
        inputs=None,
        skipped=True,
        skipped_reason=reason,
    )


def traced_call(
    hook_fn: Any,
    /,
    *args: Any,
    lane: str,
    trace_id: str,
    phase: str,
    **kwargs: Any,
) -> Any:
    """Call a synchronous hook, emit a full trace record, and return the result.

    All positional and keyword arguments to ``hook_fn`` are bound by name via
    :func:`inspect.signature` and serialised with :func:`audit_dump` — no
    field selection, no manual mapping.

    On exception the record is emitted with ``raised`` set to ``repr(exc)``
    and the original exception is re-raised unchanged.
    """
    inputs = _bind_inputs(hook_fn, args, kwargs)
    t0 = time.perf_counter()
    raised_repr: str | None = None
    result: Any = None
    try:
        result = hook_fn(*args, **kwargs)
        return result
    except Exception as exc:
        raised_repr = repr(exc)
        raise
    finally:
        elapsed = (time.perf_counter() - t0) * 1000
        _emit(
            lane=lane,
            trace_id=trace_id,
            phase=phase,
            inputs=inputs,
            output=audit_dump(result) if raised_repr is None else None,
            raised=raised_repr,
            elapsed_ms=elapsed,
        )


async def traced_acall(
    hook_fn: Any,
    /,
    *args: Any,
    lane: str,
    trace_id: str,
    phase: str,
    timeout_s: float | None = None,
    **kwargs: Any,
) -> Any:
    """Await an asynchronous hook, emit a full trace record, and return the result.

    All arguments to ``hook_fn`` are bound by name via :func:`inspect.signature`
    and serialised with :func:`audit_dump` — full function dump, no selection.

    When ``timeout_s`` is given the coroutine is wrapped with
    :func:`asyncio.wait_for`.  The original exception (``TimeoutError``,
    ``NotImplementedError``, or any other) is re-raised after the record is
    emitted; callers decide how to convert errors.
    """
    inputs = _bind_inputs(hook_fn, args, kwargs)
    t0 = time.perf_counter()
    coro = hook_fn(*args, **kwargs)
    raised_repr: str | None = None
    result: Any = None
    try:
        if timeout_s is not None:
            result = await asyncio.wait_for(coro, timeout=timeout_s)
        else:
            result = await coro
        return result
    except Exception as exc:
        raised_repr = repr(exc)
        raise
    finally:
        elapsed = (time.perf_counter() - t0) * 1000
        _emit(
            lane=lane,
            trace_id=trace_id,
            phase=phase,
            inputs=inputs,
            output=audit_dump(result) if raised_repr is None else None,
            raised=raised_repr,
            elapsed_ms=elapsed,
        )


def make_trace_id(intent: Any, bundle_id: str) -> str:
    """Build a stable per-intent trace identifier from the IntentFrame.

    Format: ``{agent_id}:{session_suffix}:{sequence_id}:{bundle_id}``
    """
    try:
        agent = intent.agent_id or "unknown"
        seq = intent.sequence_id or 0
        session = (intent.session_id or "").split("_")[-1]
        return f"{agent}:{session}:{seq}:{bundle_id}"
    except Exception:
        return f"unknown:0:{bundle_id}"
