"""Tests for the capability-tag matcher used by TerminalChecker.

The matcher supports exact strings and trailing ``:*`` prefix-globs.
Anything else must fail closed — a typo in a policy pattern should
never silently widen the allow/deny surface.
"""

from __future__ import annotations

import pytest

from intentframe_native_kit.intentframe_native_bundles.actions.terminal._capability_match import (
    any_tag_matches,
    matches,
    matches_any,
)


class TestExactMatch:
    def test_identical_tags_match(self):
        assert matches("capability:network_bind", "capability:network_bind")

    def test_different_tags_do_not_match(self):
        assert not matches("capability:network_bind", "capability:network_exfil")

    def test_empty_tag_never_matches(self):
        assert not matches("", "capability:foo")

    def test_empty_pattern_never_matches(self):
        assert not matches("capability:foo", "")


class TestPrefixGlob:
    def test_trailing_star_matches_family(self):
        assert matches(
            "capability:package_install:pip",
            "capability:package_install:*",
        )

    def test_trailing_star_matches_another_family_member(self):
        assert matches(
            "capability:package_install:apt",
            "capability:package_install:*",
        )

    def test_trailing_star_does_not_match_other_family(self):
        assert not matches(
            "capability:network_bind",
            "capability:package_install:*",
        )

    def test_trailing_star_requires_at_least_one_remainder_char(self):
        # "capability:package_install:" alone shouldn't match
        # "capability:package_install:*" — the "*" must cover
        # at least one character of a sub-tag.
        assert not matches(
            "capability:package_install:",
            "capability:package_install:*",
        )


class TestMalformedPatternsFailClosed:
    @pytest.mark.parametrize(
        "pattern",
        [
            "*",                              # lone star
            "capa*",                          # partial-segment glob
            "capability:*:pip",               # middle glob
            "capability:package_install:*:x", # multi-star
            "capability:foo*",                # trailing without colon boundary
        ],
    )
    def test_malformed_patterns_return_false(self, pattern):
        assert not matches("capability:package_install:pip", pattern)


class TestMatchesAny:
    patterns = (
        "capability:package_install:*",
        "capability:network_bind",
    )

    def test_hit_in_prefix_glob(self):
        assert matches_any("capability:package_install:pip", self.patterns)

    def test_hit_in_exact(self):
        assert matches_any("capability:network_bind", self.patterns)

    def test_miss(self):
        assert not matches_any("capability:network_exfil", self.patterns)

    def test_empty_patterns_always_misses(self):
        assert not matches_any("capability:package_install:pip", ())


class TestAnyTagMatches:
    patterns = (
        "capability:package_install:*",
        "capability:network_bind",
    )

    def test_returns_first_matching_tag(self):
        tags = (
            "capability:read_only:file",
            "capability:package_install:pip",
            "capability:network_bind",
        )
        assert any_tag_matches(tags, self.patterns) == "capability:package_install:pip"

    def test_returns_none_on_no_match(self):
        assert any_tag_matches(
            ("capability:read_only:file", "capability:network_exfil"),
            self.patterns,
        ) is None

    def test_returns_none_on_empty_patterns(self):
        assert any_tag_matches(
            ("capability:package_install:pip",),
            (),
        ) is None

    def test_returns_none_on_empty_tags(self):
        assert any_tag_matches((), self.patterns) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
