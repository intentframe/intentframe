"""
Intent data formatting for AI prompts.

Data-in-prompt policy
─────────────────────
All intent data keys are always shown so the AI knows what the intent
carries.  Each *value* is included verbatim only when it fits within
``MAX_VALUE_LENGTH``.  Values that exceed the cap are replaced with a
size note (e.g. ``[skipped — 6,230 chars]``) so the AI is still aware
of the field and its magnitude without the full content bloating the
prompt or expanding the injection surface.

Why per-value cap (not whole-dict cap):
    A single large payload field (``body``, ``content``) must not hide
    short governance-critical fields (``to``, ``command``, ``subject``)
    from the AI.  Per-value capping ensures governance fields always
    survive while oversized payloads are cleanly skipped.

Why skip instead of truncate:
    A truncated value is a half-truth — the AI sees partial content and
    may draw incorrect conclusions about intent-vs-content coherence.
    Skipping is honest: the AI knows a field exists, knows its size,
    and knows it has NOT seen the content.

Future: tool-based data access
    A dedicated tool will let the IF AI components read, search, or
    index skipped data on demand — accessing subsets, ranges, or
    running keyword searches against large payloads.  This keeps the
    default prompt lean while preserving full inspection capability
    when the AI decides it needs deeper context.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

MAX_VALUE_LENGTH = 5000


def format_intent_data(
    data: Optional[Dict[str, Any]],
    *,
    max_value_length: int = MAX_VALUE_LENGTH,
) -> str:
    """Format intent data for inclusion in an AI prompt.

    Every key is always present in the output.  Values within
    *max_value_length* are included verbatim; oversized values are
    replaced with a ``[skipped — N chars]`` note.

    Returns an empty string when *data* is ``None`` or empty so callers
    can unconditionally append the result.
    """
    if not data:
        return ""

    lines = ["Data:"]
    for key, value in data.items():
        str_value = str(value)
        if len(str_value) > max_value_length:
            lines.append(f"  {key}: [skipped — {len(str_value):,} chars]")
        else:
            lines.append(f"  {key}: {str_value}")

    return "\n".join(lines) + "\n"
