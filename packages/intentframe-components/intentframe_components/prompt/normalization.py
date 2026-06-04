"""
Encoding normalization for untrusted text before it enters AI prompts.

Deterministic pre-processing — no AI, no heuristics.  Strips encoding
tricks that attackers use to smuggle instructions past keyword filters
while preserving the semantic content the AI needs to analyze.

Runs on every untrusted field value (target, reason, data strings)
before prompt construction.
"""

from __future__ import annotations

import re
import unicodedata

_ZERO_WIDTH_RE = re.compile(
    r'[\u200b-\u200f\u2028-\u202f\u2060-\u2064\ufeff]'
)

_BASE64_BLOCK_RE = re.compile(r'[A-Za-z0-9+/]{40,}={0,2}')


def normalize_text(text: str) -> str:
    """Normalize untrusted text before it enters any AI prompt.

    1. Unicode NFKC — collapses homoglyphs to their canonical forms
       (e.g. fullwidth 'A' → ASCII 'A', ligature 'fi' → 'fi').
    2. Zero-width character stripping — removes invisible characters
       that can hide content from keyword filters.
    3. Base64 detection — flags (does not decode) suspicious base64
       blocks so the AI is aware of encoding without executing it.
    """
    text = unicodedata.normalize("NFKC", text)

    text = _ZERO_WIDTH_RE.sub("", text)

    if _BASE64_BLOCK_RE.search(text):
        text += "\n[PIPELINE NOTE: base64-like content detected in this field]"

    return text
