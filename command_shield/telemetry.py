"""Classifier coverage telemetry.

Records structured log lines when the command_shield pipeline rates a
command BLOCK/CATASTROPHIC/NEEDS_REVIEW **without** attaching any
sensitive-family capability tag.  These are the commands our verdict
layer already knows are dangerous but our tag taxonomy has no name
for — i.e. the evidence for the next rule addition.

Design stance
-------------
The critique this module answers is "the current process is anecdote-
driven: someone runs the demo, ``plutil`` of a cookie slips through,
so we bolt on a rule".  The fix is to replace anecdote with count:
log the shape, count the shapes over a window, and add rules to the
top N — stopping when the counter flat-lines.  Until that counter
exists, the classifier's coverage argument is untestable.

Disabled by default (log level DEBUG) so turning telemetry on is an
opt-in decision.  Enable via :data:`LOG_NAME` at DEBUG in the caller's
logging config:

.. code-block:: python

    logging.getLogger("command_shield.telemetry").setLevel(logging.DEBUG)

Each emitted record is a single-line ``extra``-loaded log entry; the
caller's structlog / JSON formatter picks the fields up as structured
data.  We deliberately avoid pulling structlog in here so the module
stays importable from any part of the pipeline without pulling a
runtime dep onto the classifier.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from command_shield.verdict import Verdict


LOG_NAME: Final[str] = "command_shield.telemetry"
_logger = logging.getLogger(LOG_NAME)


# Capability prefixes that count as "already covered by a
# sensitive-surface tag" for the purposes of this hook.  The first
# three are Command Shield's native emitted families; the MITRE-aligned
# prefixes are retained as accepted presentation aliases for callers
# that choose to normalize tags before recording telemetry.
_SENSITIVE_CAPABILITY_PREFIXES: Final[frozenset[str]] = frozenset({
    "capability:data_read:",
    "capability:system_mutate:",
    "capability:network_exfil:",
    "capability:credential_access:",
    "capability:persistence:",
    "capability:defense_evasion:",
    "capability:exfiltration:",
    "capability:collection:",
    "capability:privilege_escalation:",
    "capability:discovery:",
    "capability:lateral_movement:",
    "capability:command_and_control:",
    "capability:impact:",
})


# Verdicts we consider "the classifier already called this risky".
_HIGH_VERDICT_NAMES: Final[frozenset[str]] = frozenset({
    "BLOCK",
    "NEEDS_REVIEW",
    "CATASTROPHIC",
})


def _has_sensitive_tag(capabilities: tuple[str, ...]) -> bool:
    for cap in capabilities:
        for prefix in _SENSITIVE_CAPABILITY_PREFIXES:
            if cap.startswith(prefix):
                return True
    return False


def record_classification(
    command: str,
    verdict: "Verdict",
    capabilities: tuple[str, ...],
    *,
    matched_patterns: tuple[str, ...] = (),
) -> None:
    """Emit a telemetry line when *verdict* is high and no tag is sensitive.

    Parameters
    ----------
    command
        The raw command string.  Truncated to 200 chars in the log
        line so a pathologically long command doesn't blow up the
        logging backend.
    verdict
        The :class:`command_shield.verdict.Verdict` enum value.
    capabilities
        The emitted ``capability:<family>:<suffix>`` IDs on this
        command.
    matched_patterns
        Optional list of pattern IDs from
        ``command_shield/patterns/*.json`` that fired on this
        command.  Shown in the log line so the reviewer can tell
        whether the BLOCK came from the pattern layer (verdict-
        bearing) or from a downstream signal.

    Behaviour:
        - Only emits when ``verdict.name`` is in
          :data:`_HIGH_VERDICT_NAMES`.
        - Skips the emission if *any* capability tag starts with a
          prefix in :data:`_SENSITIVE_CAPABILITY_PREFIXES` — that
          command is already covered by the taxonomy.
        - Otherwise emits a single ``logging.DEBUG`` line (so it is
          silent in production unless the logger is turned up) with
          structured ``extra`` fields that a JSON / structlog
          formatter will preserve.
    """
    verdict_name = getattr(verdict, "name", str(verdict))
    if verdict_name not in _HIGH_VERDICT_NAMES:
        return
    if _has_sensitive_tag(capabilities):
        return

    _logger.debug(
        "classifier-coverage-gap verdict=%s command=%r caps=%s patterns=%s",
        verdict_name,
        command[:200],
        sorted(capabilities),
        sorted(matched_patterns),
        extra={
            "event": "classifier_coverage_gap",
            "verdict": verdict_name,
            "command": command[:200],
            "capabilities": sorted(capabilities),
            "matched_patterns": sorted(matched_patterns),
        },
    )


__all__ = [
    "LOG_NAME",
    "record_classification",
]
