"""Data-driven classifier capability rules.

This package is the source of truth for Command Shield's capability
emission rules.  Each capability family has its own YAML file under
``command_shield/capabilities/``:

Sensitive-surface families (rows marked ``sensitive: true`` feed
:meth:`CapabilityCorpus.sensitive_capability_ids`):

- ``capability:data_read:*`` (`data_read.yaml`)
- ``capability:system_mutate:*`` (`system_mutate.yaml`)
- ``capability:network_exfil:*`` (`network_exfil.yaml`)

Execution families:

- ``capability:script_execution:*`` (`script_execution.yaml`)
- ``capability:stdin_exec[:*]`` (`stdin_exec.yaml`)
- ``capability:package_install:*`` (`package_install.yaml`)
- ``capability:compilation`` (`compilation.yaml`)

Network / process / filesystem families:

- ``capability:network_bind`` (`network_bind.yaml`)
- ``capability:network_probe:*`` (`network_probe.yaml`)
- ``capability:background_exec`` (`background_exec.yaml`)
- ``capability:download_and_exec`` (`download_and_exec.yaml`)
- ``capability:binary_download`` (`binary_download.yaml`)
- ``capability:process_signal`` (`process_signal.yaml`)
- ``capability:spawns_process`` (`spawns_process.yaml`)
- ``capability:filesystem_write`` (`filesystem_write.yaml`)

Positive (fast-path) family:

- ``capability:read_only:*`` (`read_only.yaml`)

Each YAML file is a list of rules with the following shape::

    - id:               <family>__<suffix>[__<n>]   # unique across all files
      family:           family name (lower_snake_case)
      suffix:           snake_case sub-tag name (optional; empty → emit
                        ``capability:<family>`` with no suffix)
      pattern:          Python regex (compiled with re.compile, no flags)
      description:      short human description shown by the classifier
                        when the tag fires (optional)
      sensitive:        true | false     # included in sensitive-tag summaries
      mitre_family:     MITRE ATT&CK tactic (credential_access, persistence,
                                             defense_evasion, collection,
                                             exfiltration, privilege_escalation,
                                             impact, discovery, execution,
                                             lateral_movement, command_and_control)
                        — REQUIRED when ``sensitive: true``; otherwise optional
                        presentation metadata.
      mitre_techniques: list of MITRE ATT&CK technique IDs (T####[.###])

Adding a new rule is a data-first change inside Command Shield:
append a row to the relevant YAML and add a fixture.  The classifier
and the coverage map in ``command_shield/COVERAGE.md`` are derived
from this data; downstream consumers decide independently how to use
the emitted ``capability:*`` tags.
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
    pattern: re.Pattern[str]
    suffix: str = ""
    sensitive: bool = False
    mitre_family: str | None = None
    mitre_techniques: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""

    def capability_tag(self) -> str:
        """Return the literal ``capability:*`` tag this rule emits."""
        if self.suffix:
            return f"capability:{self.family}:{self.suffix}"
        return f"capability:{self.family}"


@dataclass(frozen=True)
class CapabilityCorpus:
    """The full loaded corpus, indexed a few different ways."""

    rules: tuple[CapabilityRule, ...]

    def by_family(self, family: str) -> tuple[CapabilityRule, ...]:
        """Rules whose ``family`` matches *family* (e.g. ``data_read``)."""
        return tuple(r for r in self.rules if r.family == family)

    def sensitive_capability_ids(self) -> frozenset[str]:
        """Set of ``capability:<family>:<suffix>`` IDs where ``sensitive``.

        Stable across ordering: de-duplicates the
        ``<family>:<suffix>`` pair across rows that share a suffix
        (e.g. ``data_read:cloud_tokens`` splits across file and verb
        shapes but is a single emitted capability tag).
        """
        return frozenset(
            r.capability_tag()
            for r in self.rules
            if r.sensitive
        )

    def mitre_alias_map(self) -> dict[str, str]:
        """Map each emitted tag to its MITRE-aligned alias.

        Only rules that declare a ``mitre_family`` participate.  The
        classifier still emits Command Shield's native families
        (``capability:data_read:*``, ``capability:system_mutate:*``,
        ``capability:network_exfil:*``).  This helper exposes the
        documentation mapping to MITRE-aligned names without changing
        that emission contract.
        """
        out: dict[str, str] = {}
        for r in self.rules:
            if not r.mitre_family:
                continue
            legacy = r.capability_tag()
            if r.suffix:
                mitre = f"capability:{r.mitre_family}:{r.suffix}"
            else:
                mitre = f"capability:{r.mitre_family}"
            out[legacy] = mitre
        return out

    def mitre_family_names(self) -> frozenset[str]:
        """Set of MITRE tactic names referenced by any rule.

        Useful for coverage summaries and presentations that group
        Command Shield's native emitted tags by MITRE tactic.
        """
        return frozenset(r.mitre_family for r in self.rules if r.mitre_family)


def _load_family(path: Path) -> list[CapabilityRule]:
    with path.open(encoding="utf-8") as f:
        rows = yaml.safe_load(f) or []
    if not isinstance(rows, list):
        raise ValueError(
            f"{path.name}: top-level must be a YAML list of rule dicts"
        )

    compiled: list[CapabilityRule] = []
    for raw in rows:
        for key in ("id", "family", "pattern"):
            if key not in raw:
                raise ValueError(f"{path.name}: rule missing '{key}': {raw!r}")

        sensitive = bool(raw.get("sensitive", False))
        mitre_family = raw.get("mitre_family")
        if sensitive and not mitre_family:
            raise ValueError(
                f"{path.name}: sensitive rule {raw['id']!r} must declare a "
                f"mitre_family"
            )
        if mitre_family is not None and mitre_family not in _ALLOWED_MITRE_FAMILIES:
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
            suffix=raw.get("suffix") or "",
            pattern=pattern,
            sensitive=sensitive,
            mitre_family=mitre_family,
            mitre_techniques=tuple(raw.get("mitre_techniques") or ()),
            description=raw.get("description") or "",
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
