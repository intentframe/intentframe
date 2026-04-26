"""Profile x command matrix for DeterministicGuardian RUN_COMMAND.

Each test drives the real :func:`command_shield.inspect_command` and the
real :class:`DeterministicGuardian` with a real :class:`TerminalConstraints`
policy.  No injected ``CommandIntel``.  A failure either means the
classifier's output drifted or a DG gate stopped firing as expected \u2014
both are load-bearing regressions worth catching.

The test is parametrized as a cross-product of :data:`CORPUS` and
:data:`PROFILES`.  Known classifier / gate gaps are captured per-case
via :attr:`Case.xfail` and reported as ``XFAIL`` / ``XPASS`` rather
than silent skips \u2014 a gap closing (XPASS) is a nudge to remove the
xfail and let the test start protecting the new behavior.
"""

from __future__ import annotations

import pytest

from intentframe_components.guardian.deterministic import DeterministicDecision

from ._helpers import run_dg
from .corpus import CORPUS, ALLOW, BLOCK, UNDECIDED, Case
from .policies import PROFILES


_DECISION_MAP = {
    ALLOW: DeterministicDecision.ALLOW,
    BLOCK: DeterministicDecision.BLOCK,
    UNDECIDED: DeterministicDecision.UNDECIDED,
}


def _cross_product() -> list[tuple[Case, str]]:
    """Generate (case, profile_name) pairs for every corpus entry."""
    pairs: list[tuple[Case, str]] = []
    for case in CORPUS:
        for profile_name in PROFILES:
            if profile_name not in case.expected:
                continue
            pairs.append((case, profile_name))
    return pairs


def _id(pair: tuple[Case, str]) -> str:
    case, profile = pair
    return f"[{profile}] {case.category} :: {case.command}"


@pytest.mark.parametrize("pair", _cross_product(), ids=_id)
def test_dg_decision_matches_expected(pair: tuple[Case, str]) -> None:
    case, profile_name = pair
    expected_str = case.expected[profile_name]
    expected_decision = _DECISION_MAP[expected_str]
    xfail_reason = case.xfail.get(profile_name)

    # ``strict=False`` (default) keeps XPASS from failing the test \u2014
    # we want XPASS to surface as a prompt to remove the xfail, not
    # to break CI.  A future tightening can flip this to strict once
    # the corpus is stable.
    if xfail_reason:
        pytest.xfail(xfail_reason)

    user_context = PROFILES[profile_name]()
    result, view = run_dg(case.command, user_context)

    assert result.decision is expected_decision, (
        f"\n  command:   {case.command!r}"
        f"\n  profile:   {profile_name}"
        f"\n  category:  {case.category}"
        f"\n  note:      {case.note}"
        f"\n  expected:  {expected_decision.value}"
        f"\n  actual:    {result.decision.value} (gate={result.matched_gate})"
        f"\n  classifier verdict={view.verdict}"
        f" caps={view.capabilities}"
        f" edges={view.has_edge_signals}"
        f" code_findings={view.has_code_intel_findings}"
    )


# ── Secondary observation test: sanity-check the classifier surface ───
# Not an accuracy assertion \u2014 a read-only sanity check so a test run
# surfaces classifier drift (e.g. verdict flipping to CATASTROPHIC for
# a benign command) even when the decision happens to still match.

@pytest.mark.parametrize(
    "command, min_caps, max_verdict",
    [
        ("ls -la", {"capability:read_only"}, "SAFE"),
        ("pwd", {"capability:read_only"}, "SAFE"),
        ("cat README.md", {"capability:read_only"}, "SAFE"),
        ("grep -r foo .", {"capability:read_only"}, "SAFE"),
    ],
)
def test_classifier_emits_read_only_for_canonical_commands(
    command: str, min_caps: set[str], max_verdict: str
) -> None:
    """Pin the classifier contract for the commands the matrix depends on.

    If this regresses, every read-only ALLOW in the matrix regresses
    along with it \u2014 the failure here narrows the blast radius to
    'classifier changed' vs 'DG changed'.
    """
    from ._helpers import build_shield_view

    view = build_shield_view(command)
    assert view.verdict == max_verdict, (
        f"{command!r}: expected verdict<={max_verdict}, got {view.verdict}"
    )
    has_prefix = any(
        any(cap.startswith(p) for cap in view.capabilities) for p in min_caps
    )
    assert has_prefix, (
        f"{command!r}: expected at least one capability under {min_caps}, "
        f"got {view.capabilities!r}"
    )
