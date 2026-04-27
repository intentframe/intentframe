"""Regenerate ``command_shield/COVERAGE.md`` from the YAML corpus.

``COVERAGE.md`` is the written exit criterion for the classifier: it
enumerates every sensitive capability tag, the MITRE ATT&CK tactic it
rolls up to, and the technique IDs it is meant to catch.  A blank
``TODO`` row is the signal that a technique is known-unmapped and
warrants a new rule; the absence of rows is the signal that the
classifier is **done** for that tactic and further additions need
either a new MITRE technique being published or a production miss.

Regenerate after editing any YAML file::

    .venv/bin/python scripts/generate_coverage_md.py
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from command_shield.capabilities import CORPUS


HEADER = """# Command Shield — Classifier Coverage Map

> **This file is auto-generated from
> `command_shield/capabilities/*.yaml` by
> `scripts/generate_coverage_md.py`.  Do not hand-edit — update the
> YAML and regenerate.**

The classifier's sensitive-surface capability families map 1:1 to
MITRE ATT&CK (Enterprise) tactics.  Each row is a rule in the YAML
corpus; the `capability` column is the literal ID the classifier
emits and that `SENSITIVE_SURFACE_DENY_CAPABILITIES` clamps.

When every MITRE tactic a shell-and-python operator can reasonably
reach has at least one row, the classifier is **done** for that
tactic — further additions require either a newly published MITRE
technique or a production miss found via the telemetry hook in
`command_shield.telemetry`.  Speculative additions are out of scope;
write the evidence down before opening a PR.

Tactics not currently mapped (intentional out-of-scope for a
shell+python operator — listed here so reviewers know the gap is
deliberate):

- `initial_access` — handled upstream by the gateway, not by the
  command classifier.
- `reconnaissance`, `resource_development` — pre-compromise; no
  on-host shell shape to tag.
- `impact` — destructive shapes (``rm -rf /``, ``mkfs``, ``dd``)
  are caught by the catastrophic pattern layer in
  `command_shield/patterns/catastrophic.json`, not by a
  `capability:impact:*` tag.

---

"""

TACTIC_BLURB: dict[str, str] = {
    "credential_access": (
        "Reads that yield credentials (tokens, keys, password-manager "
        "vaults, keychain material, dotenv secrets).  The classifier "
        "emits ``capability:data_read:*`` with the "
        "read-only-incompatible gate active so a matching command can "
        "never also be tagged ``read_only:*``."
    ),
    "collection": (
        "Reads that yield non-credential PII / session state / "
        "contacts / mail / chat history.  Same emission shape as "
        "``credential_access`` (``capability:data_read:*``); the "
        "distinction is the MITRE tactic mapping, not the tag prefix."
    ),
    "persistence": (
        "Shapes that plant long-lived execution or config "
        "(scheduled tasks, launchd, systemd, browser extensions, "
        "MDM profiles, boot-chain trust, account mutation).  Emitted "
        "as ``capability:system_mutate:*``."
    ),
    "defense_evasion": (
        "Shapes that disable, degrade, or tamper with host telemetry "
        "and trust surfaces (security daemons, audit / unified "
        "logging, TCC, firewall rules, kernel tunables, /etc/hosts). "
        " Emitted as ``capability:system_mutate:*``."
    ),
    "privilege_escalation": (
        "Shapes that rewrite the privilege graph itself — sudoers / "
        "PAM / passwd / shadow / group writes.  Emitted as "
        "``capability:system_mutate:privilege_config``."
    ),
    "exfiltration": (
        "Shapes whose primary effect is moving local-host data "
        "outbound (HTTP upload, scp / rsync outbound, ssh tunnels, "
        "cloud-bucket upload).  Emitted as "
        "``capability:network_exfil:*`` with the same "
        "read-only-incompatible gate as ``data_read:*``."
    ),
    "lateral_movement": (
        "Shapes that pivot to another host — SSH port forwarding, "
        "ARD kickstart, Windows Remote Management invocations.  "
        "Currently overlaps with the ``exfiltration`` and "
        "``defense_evasion`` tactics in this corpus (e.g. an SSH "
        "tunnel is tagged ``network_exfil:ssh_tunnel`` but maps to "
        "both T1572 and T1021.004)."
    ),
    "discovery": (
        "Reads that map the target environment (known_hosts, "
        "process lists, filesystem enumeration).  Currently "
        "represented only by ``data_read:ssh_known_hosts``; "
        "generic filesystem listing is covered by the "
        "``read_only:filesystem_list`` family and is not "
        "classified as a sensitive surface."
    ),
    "execution": (
        "Shapes that run code — already covered by "
        "``capability:script_execution:*``, "
        "``capability:stdin_exec:*``, and "
        "``capability:download_and_exec``; not re-enumerated here "
        "since none of them are members of "
        "``SENSITIVE_SURFACE_DENY_CAPABILITIES``."
    ),
    "impact": (
        "Destructive shapes — caught by the catastrophic pattern "
        "layer (``command_shield/patterns/catastrophic.json``), not "
        "by the sensitive-surface classifier."
    ),
    "command_and_control": (
        "Outbound connect-back shapes.  Currently overlaps with "
        "``exfiltration`` (a reverse SSH tunnel is both), and with "
        "``network_probe:*`` for generic outbound network probes; "
        "no dedicated sub-tags yet."
    ),
}


def main() -> None:
    by_tactic: dict[str, list] = defaultdict(list)
    for rule in CORPUS.rules:
        by_tactic[rule.mitre_family].append(rule)

    lines: list[str] = [HEADER]

    for tactic in sorted(by_tactic):
        rules = by_tactic[tactic]
        blurb = TACTIC_BLURB.get(tactic, "")
        lines.append(f"## `{tactic}`\n")
        if blurb:
            lines.append(blurb + "\n")
        lines.append("")
        lines.append("| Rule ID | Capability tag | MITRE technique(s) | Source YAML |")
        lines.append("|---|---|---|---|")
        for rule in sorted(rules, key=lambda r: (r.family, r.suffix, r.id)):
            techniques = ", ".join(rule.mitre_techniques) or "_(none)_"
            cap = f"`capability:{rule.family}:{rule.suffix}`"
            lines.append(
                f"| `{rule.id}` | {cap} | {techniques} | "
                f"`command_shield/capabilities/{rule.family}.yaml` |"
            )
        lines.append("")

    lines.append("---\n")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total sensitive-surface rules:** {len(CORPUS.rules)}")
    lines.append(
        f"- **Distinct capability tags:** "
        f"{len(CORPUS.sensitive_capability_ids())}"
    )
    lines.append(f"- **Tactics covered:** {len(by_tactic)}")
    lines.append("")
    lines.append(
        "Per-tactic counts (unique `capability:<family>:<suffix>` pairs; "
        "a suffix split across multiple regex rows — e.g. "
        "`data_read:cloud_tokens` file-shape and verb-shape — counts once):"
    )
    lines.append("")
    counts: list[tuple[str, int]] = []
    for tactic, rules in by_tactic.items():
        caps = {(r.family, r.suffix) for r in rules}
        counts.append((tactic, len(caps)))
    counts.sort(key=lambda x: (-x[1], x[0]))
    for tactic, n in counts:
        lines.append(f"- `{tactic}`: **{n}**")
    lines.append("")

    out = Path("command_shield/COVERAGE.md")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out} ({sum(len(v) for v in by_tactic.values())} rules)")


if __name__ == "__main__":
    main()
