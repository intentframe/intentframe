"""Data-driven classifier capability rules.

This package is the source of truth for the three refined
sensitive-surface capability families:

- ``capability:data_read:*`` (`data_read.yaml`)
- ``capability:system_mutate:*`` (`system_mutate.yaml`)
- ``capability:network_exfil:*`` (`network_exfil.yaml`)

Each YAML file is a list of rules with the following shape::

    - id:               <family>__<suffix>[__<n>]   # unique across all files
      family:           data_read | system_mutate | network_exfil
      suffix:           snake_case sub-tag name
      pattern:          Python regex (compiled with re.compile, no flags)
      sensitive:        true | false     # auto-derives the deny clamp
      mitre_family:     MITRE ATT&CK tactic (credential_access, persistence,
                                             defense_evasion, collection,
                                             exfiltration, privilege_escalation,
                                             impact, discovery, execution,
                                             lateral_movement, command_and_control)
      mitre_techniques: list of MITRE ATT&CK technique IDs (T####[.###])

Adding a new sub-tag is now a pure data PR: append a row to the
relevant YAML and add a fixture.  The classifier, the policy frozen-
sets in :mod:`intentframe_gateway.bootstrap` and
:mod:`jarvis_pa.seed_policies`, and the coverage map in
``command_shield/COVERAGE.md`` are all auto-derived from this data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import yaml


_CAPABILITIES_DIR: Final[Path] = Path(__file__).parent

# MITRE ATT&CK tactics we currently map to.  Validated at load time so
# a typo in a YAML file ("defence_evasion") fails loudly at import
# rather than silently bucketing rules into their own family.
_ALLOWED_MITRE_FAMILIES: Final[frozenset[str]] = frozenset({
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


@dataclass(frozen=True)
class CapabilityRule:
    """One row of a capability YAML file, compiled and normalised."""

    id: str
    family: str
    suffix: str
    pattern: re.Pattern[str]
    sensitive: bool
    mitre_family: str
    mitre_techniques: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CapabilityCorpus:
    """The full loaded corpus, indexed a few different ways."""

    rules: tuple[CapabilityRule, ...]

    def by_family(self, family: str) -> tuple[CapabilityRule, ...]:
        """Rules whose ``family`` matches *family* (e.g. ``data_read``)."""
        return tuple(r for r in self.rules if r.family == family)

    def sensitive_capability_ids(self) -> frozenset[str]:
        """Set of ``capability:<family>:<suffix>`` IDs where ``sensitive``.

        Used by the bootstrap / seeder frozen-sets as the single source
        of truth for which tags are denied by the default terminal
        constraints.  Stable across ordering: de-duplicates the
        ``<family>:<suffix>`` pair across rows that share a suffix
        (e.g. ``data_read:cloud_tokens`` splits across file and verb
        shapes but is a single deny-list entry).
        """
        return frozenset(
            f"capability:{r.family}:{r.suffix}"
            for r in self.rules
            if r.sensitive
        )

    def mitre_alias_map(self) -> dict[str, str]:
        """Map each emitted tag to its MITRE-aligned alias.

        Returns a ``dict[str, str]`` of the form::

            {
                "capability:data_read:browser_cookies":
                    "capability:credential_access:browser_cookies",
                "capability:system_mutate:launchd_mutation":
                    "capability:persistence:launchd_mutation",
                "capability:network_exfil:http_upload":
                    "capability:exfiltration:http_upload",
                ...
            }

        Consumed by :mod:`policy_registry.constraints._capability_match`
        so a policy expressed against MITRE tactic names (``capability:
        credential_access:*``, ``capability:persistence:*``) matches
        today's legacy ``capability:data_read:*`` /
        ``capability:system_mutate:*`` / ``capability:network_exfil:*``
        tags without requiring the classifier to emit two IDs per rule.
        This is the "one-release alias" layer: new policies can use
        MITRE names now; old policies using legacy names keep working;
        whenever emission flips to MITRE names the alias map becomes
        the legacy-compat shim.
        """
        out: dict[str, str] = {}
        for r in self.rules:
            legacy = f"capability:{r.family}:{r.suffix}"
            mitre = f"capability:{r.mitre_family}:{r.suffix}"
            out[legacy] = mitre
        return out

    def mitre_family_names(self) -> frozenset[str]:
        """Set of MITRE tactic names referenced by any rule.

        Used to decide whether a policy pattern like
        ``capability:credential_access:*`` is a MITRE-alias pattern
        (in which case it needs the alias lookup) or a legacy
        top-level pattern (``capability:data_read:*``, straight match).
        """
        return frozenset(r.mitre_family for r in self.rules)


def _load_family(path: Path) -> list[CapabilityRule]:
    with path.open(encoding="utf-8") as f:
        rows = yaml.safe_load(f) or []
    if not isinstance(rows, list):
        raise ValueError(
            f"{path.name}: top-level must be a YAML list of rule dicts"
        )

    compiled: list[CapabilityRule] = []
    for raw in rows:
        for key in ("id", "family", "suffix", "pattern", "mitre_family"):
            if key not in raw:
                raise ValueError(f"{path.name}: rule missing '{key}': {raw!r}")

        mitre_family = raw["mitre_family"]
        if mitre_family not in _ALLOWED_MITRE_FAMILIES:
            raise ValueError(
                f"{path.name}: rule {raw['id']!r} has unknown mitre_family "
                f"{mitre_family!r}; allowed: "
                f"{sorted(_ALLOWED_MITRE_FAMILIES)}"
            )

        try:
            pattern = re.compile(raw["pattern"])
        except re.error as exc:
            raise ValueError(
                f"{path.name}: rule {raw['id']!r} has invalid regex: {exc}"
            ) from exc

        compiled.append(CapabilityRule(
            id=raw["id"],
            family=raw["family"],
            suffix=raw["suffix"],
            pattern=pattern,
            sensitive=bool(raw.get("sensitive", False)),
            mitre_family=mitre_family,
            mitre_techniques=tuple(raw.get("mitre_techniques") or ()),
        ))
    return compiled


def _load_all() -> CapabilityCorpus:
    rules: list[CapabilityRule] = []
    for path in sorted(_CAPABILITIES_DIR.glob("*.yaml")):
        rules.extend(_load_family(path))

    # Invariant: rule IDs are globally unique so the coverage map and
    # telemetry hook can cite them without family disambiguation.
    seen: set[str] = set()
    for r in rules:
        if r.id in seen:
            raise ValueError(f"duplicate capability rule id: {r.id!r}")
        seen.add(r.id)

    return CapabilityCorpus(rules=tuple(rules))


CORPUS: Final[CapabilityCorpus] = _load_all()


__all__ = [
    "CapabilityCorpus",
    "CapabilityRule",
    "CORPUS",
]
