"""Capability-tag matching for policy vocabulary.

Capability tags follow a strict ``capability:<family>:<sub>`` shape
(emitted by command_shield's classifier).  Policy patterns support two
forms:

    Exact             "capability:network_bind"
                          matches only that literal tag.

    Prefix-glob       "capability:package_install:*"
                          matches any tag starting with
                          "capability:package_install:", e.g.
                          "capability:package_install:pip" or
                          "capability:package_install:apt".

The ``*`` wildcard is only supported as a trailing segment on the
``:`` boundary — i.e. the pattern must end with ``:*``.  Middle-glob
(``cap:*:foo``) and partial-segment (``capa*``) are NOT supported, to
keep matching predictable and to prevent accidentally broad rules.

Why this restriction matters for security:

- Policies are snapshotted at task start and cannot be edited
  mid-execution.  A typo in a glob would silently widen the allow/
  deny surface; the strict shape catches obviously malformed
  patterns at match time.
- The classifier emits tags under a known grammar.  Anything that
  doesn't look like ``capability:<family>:<sub>`` is, by definition,
  not a tag we emit — matching such patterns is a no-op.
"""

from __future__ import annotations

from typing import Iterable


def matches(tag: str, pattern: str) -> bool:
    """Return True if ``tag`` matches ``pattern``.

    Supports:
      - Exact string equality.
      - Trailing ``:*`` prefix-glob on the ``:`` boundary.

    Invalid patterns (empty, ``*`` alone, ``*`` anywhere other than
    a trailing ``:*``) silently return False — the caller's policy
    surface remains closed.
    """
    if not tag or not pattern:
        return False
    if "*" not in pattern:
        return tag == pattern
    # Only trailing ":*" is supported.
    if not pattern.endswith(":*"):
        return False
    # Anywhere else in the pattern the "*" is illegal.
    if pattern.count("*") != 1:
        return False
    prefix = pattern[:-1]  # keeps the trailing ":"
    if not prefix.endswith(":"):
        # Pattern like "foo*" — not supported.
        return False
    # Must match the full prefix AND have at least one more non-empty
    # segment after the colon (otherwise "capability:" wildcarded to
    # "capability:" would match itself which is semantically empty).
    if not tag.startswith(prefix):
        return False
    remainder = tag[len(prefix):]
    return bool(remainder)


def matches_any(tag: str, patterns: Iterable[str]) -> bool:
    """Return True if ``tag`` matches any of ``patterns``."""
    return any(matches(tag, p) for p in patterns)


def any_tag_matches(tags: Iterable[str], patterns: Iterable[str]) -> str | None:
    """Return the first tag that matches any pattern, or None.

    Returned for error messages so BLOCK reasons can cite the exact
    capability that triggered the decision.
    """
    pattern_list = list(patterns)
    if not pattern_list:
        return None
    for tag in tags:
        if matches_any(tag, pattern_list):
            return tag
    return None
