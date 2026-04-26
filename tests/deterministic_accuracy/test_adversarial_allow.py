"""Adversarial-ALLOW guard for the DG read-only fast-path.

The matrix test in :mod:`.test_profile_matrix` verifies DG's *intended*
ALLOW / BLOCK / UNDECIDED outcomes against a corpus of honest commands.
It catches over-blocking (false positives) \u2014 but by design it does not
catch the more dangerous direction: a command that *looks* read-only at
a glance but actually mutates state, causing the classifier to emit a
``capability:read_only:*`` tag and DG to fast-path ALLOW it (skipping
AE + AIGuardian entirely).

That is the shape of a true production compromise:

    classifier over-tag \u2192 DG fast-path ALLOW \u2192 state change with no AI review

This file pins the inverse.  Each case is a command where:

1. The surface form contains a read-only-looking head (``ls``, ``cat``,
   ``grep``, ``find``, ``git``, \u2026) but also contains destructive or
   side-effectful structure (composition tail, redirect, ``-exec`` /
   ``-delete`` flag, subshell, etc.).

2. The classifier MUST NOT emit any ``capability:read_only:*`` tag.

3. DG MUST NOT return ALLOW under *any* non-restrictive profile \u2014
   ``permissive`` is the worst case: if even a wide-open policy
   somehow fast-paths one of these, every profile does.

A failure here is a real security regression, not a usability one.
There are no xfails in this file \u2014 any failure is load-bearing.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from intentframe_components.guardian.deterministic import DeterministicDecision

from ._helpers import build_shield_view, run_dg
from .policies import PROFILES


@dataclass(frozen=True)
class Adversarial:
    command: str
    note: str


# Each of these has at least one read-only-looking head but a destructive
# or side-effectful structure.  The classifier must refuse to emit any
# ``capability:read_only:*`` tag; DG must refuse to ALLOW.
_ADVERSARIAL: list[Adversarial] = [
    # ── Composition with destructive tail ────────────────────────────
    Adversarial(
        command="ls -la && rm file.txt",
        note="and-chain: read-only head, destructive tail",
    ),
    Adversarial(
        command="ls; rm file.txt",
        note="semicolon chain: read-only head, destructive tail",
    ),
    Adversarial(
        command="cat a && echo overwritten > b",
        note="and-chain with write-redirect in tail",
    ),

    # ── Redirect turns a read into a write ───────────────────────────
    Adversarial(
        command="cat file.txt > other.txt",
        note="cat + overwrite redirect",
    ),
    Adversarial(
        command="cat file.txt >> other.txt",
        note="cat + append redirect",
    ),
    Adversarial(
        command="ls > /etc/passwd",
        note="ls with redirect to sensitive path",
    ),
    Adversarial(
        command="grep pattern file.txt | tee output.txt",
        note="grep piped into tee (writes)",
    ),
    Adversarial(
        command="ls | tee file",
        note="ls piped into tee (writes)",
    ),

    # ── Destructive flags on read-looking tools ──────────────────────
    Adversarial(
        command="find . -exec rm {} \\;",
        note="find with destructive -exec",
    ),
    Adversarial(
        command="find . -delete",
        note="find with -delete flag",
    ),

    # ── Git commands that mutate ─────────────────────────────────────
    Adversarial(
        command="git pull",
        note="git pull modifies working tree (not vcs_inspect)",
    ),
    Adversarial(
        command="git clone https://example.com/repo",
        note="git clone writes to filesystem + network",
    ),
]


def _id(adv: Adversarial) -> str:
    return f"{adv.command}"


@pytest.mark.parametrize("adv", _ADVERSARIAL, ids=_id)
def test_classifier_does_not_tag_adversarial_as_read_only(adv: Adversarial) -> None:
    """Classifier contract: adversarial commands never carry read_only:*.

    If this fails, DG will fast-path ALLOW the command under any profile
    that permits RUN_COMMAND \u2014 a production compromise.
    """
    view = build_shield_view(adv.command)
    read_only_caps = [c for c in view.capabilities if c.startswith("capability:read_only:")]
    assert not read_only_caps, (
        f"\n  command: {adv.command!r}"
        f"\n  note:    {adv.note}"
        f"\n  verdict: {view.verdict}"
        f"\n  caps:    {list(view.capabilities)}"
        f"\n  BUG: classifier emitted read_only tag(s) {read_only_caps!r} on an "
        f"adversarial command \u2014 DG will now fast-path ALLOW this under any "
        f"profile that permits RUN_COMMAND."
    )


@pytest.mark.parametrize("adv", _ADVERSARIAL, ids=_id)
@pytest.mark.parametrize("profile_name", list(PROFILES.keys()))
def test_dg_does_not_allow_adversarial(adv: Adversarial, profile_name: str) -> None:
    """DG contract: adversarial commands never reach ALLOW.

    The matrix test verifies the *expected* decision.  This one pins the
    weaker but security-critical invariant: decision is **not** ALLOW.
    BLOCK or UNDECIDED are both acceptable outcomes \u2014 either the
    deterministic gate caught it, or AE gets to decide.  What must
    not happen is DG short-circuiting ALLOW.
    """
    user_context = PROFILES[profile_name]()
    result, view = run_dg(adv.command, user_context)
    assert result.decision is not DeterministicDecision.ALLOW, (
        f"\n  command: {adv.command!r}"
        f"\n  profile: {profile_name}"
        f"\n  note:    {adv.note}"
        f"\n  classifier verdict={view.verdict} caps={list(view.capabilities)}"
        f" edge={view.has_edge_signals} findings={view.has_code_intel_findings}"
        f"\n  gate:    {result.matched_gate}"
        f"\n  reason:  {result.reason}"
        f"\n  COMPROMISE: DG fast-pathed ALLOW for a command with a "
        f"destructive / side-effectful structure.  AE + AIGuardian were "
        f"skipped.  This is the production-compromise shape."
    )
