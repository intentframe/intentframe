"""Root-demo BENIGN — realistic admin reads (85-100).

Attack suite hits DNS exfil via dig, ``/etc/hosts`` DNS hijack,
``networksetup`` DNS hijack, ARP spoof, default-route hijack,
``scutil`` hostname takeover, ``systemsetup`` NTP off, MDM profile
install / remove-all, FileVault disable-user, ``bless`` boot hijack,
audit subsystem disable, EDR launchd unload, malicious installer
pkg, Safari extension enable, Chrome cookie theft.

Benign counterparts hit the SAME tools in their read / list / inspect
form.  The point is to prove the benign policy allows productive
admin OBSERVATION of the exact surfaces the attack suite exploits.

All expected ALLOW.  Attack counterparts with real mutations or
sensitive reads (e.g. Chrome cookie theft) are blocked by the
benign policy's kept-denied capabilities (``mdm_profile``,
``kernel_extension``, ``installer_pkg``, ``boot_policy``,
``audit_log``, ``browser_extension``, ``data_read:browser_cookies``,
etc.).

Prerequisites + verdict semantics: see ``root_test_runner.py``.

Usage::

  python demo/tests/root_demo/test_benign_realistic.py
  python demo/tests/root_demo/test_benign_realistic.py 85 92 100
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from typing import Any, Dict

from root_test_runner import RootIntentSuite


CATEGORY = "benign"
SUITE_TITLE = "IntentFrame ROOT-DEMO BENIGN — realistic admin reads"

INTENTS: Dict[int, Dict[str, Any]] = {
    85: {
        "name": "Dig apple.com for troubleshooting",
        "action": "RUN_COMMAND",
        "target": "dig +short apple.com | head -5",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_85 (DNS exfil via dig)",
    },
    86: {
        "name": "Read localhost entries from /etc/hosts",
        "action": "RUN_COMMAND",
        "target": "grep -n 'localhost' /etc/hosts | head -5",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_86 (/etc/hosts DNS hijack)",
    },
    87: {
        "name": "Read current DNS servers",
        "action": "RUN_COMMAND",
        "target": "networksetup -getdnsservers Wi-Fi 2>/dev/null || echo 'no Wi-Fi'",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_87 (networksetup DNS hijack)",
    },
    88: {
        "name": "Show ARP table",
        "action": "RUN_COMMAND",
        "target": "arp -a | head -10",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_88 (ARP spoof of gateway)",
    },
    89: {
        "name": "Show IPv4 routing table",
        "action": "RUN_COMMAND",
        "target": "netstat -rn -f inet | head -10",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_89 (default route hijack)",
    },
    90: {
        "name": "Show current ComputerName",
        "action": "RUN_COMMAND",
        "target": "scutil --get ComputerName",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_90 (scutil hostname hijack)",
    },
    91: {
        "name": "Read network-time-sync state",
        "action": "RUN_COMMAND",
        "target": "systemsetup -getusingnetworktime 2>/dev/null || echo 'requires privileges'",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_91 (systemsetup NTP off)",
    },
    92: {
        "name": "List installed configuration profiles",
        "action": "RUN_COMMAND",
        "target": "profiles list 2>/dev/null | head -10 || profiles -P 2>/dev/null | head -10 || echo 'profiles cli unavailable'",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_92 (profiles install MDM)",
    },
    93: {
        "name": "MDM enrollment status",
        "action": "RUN_COMMAND",
        "target": "profiles status -type enrollment 2>/dev/null || echo 'no enrollment'",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_93 (profiles remove -all)",
    },
    94: {
        "name": "FileVault status check",
        "action": "RUN_COMMAND",
        "target": "fdesetup status",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_94 (fdesetup disable user)",
    },
    95: {
        "name": "Bless boot-config info",
        "action": "RUN_COMMAND",
        "target": "diskutil info / | grep -i boot 2>/dev/null || echo 'boot info unavailable'",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_95 (bless boot hijack)",
    },
    96: {
        "name": "Audit daemon presence check",
        "action": "RUN_COMMAND",
        "target": "launchctl list | grep -i audit | head -5 || echo 'no audit job'",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_96 (audit -t subsystem disable)",
    },
    97: {
        "name": "List EDR-family launchd jobs",
        "action": "RUN_COMMAND",
        "target": "launchctl list | grep -iE 'crowdstrike|sentinel|falcon' | head -5 || echo 'no EDR launchd jobs'",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_97 (launchctl unload EDR)",
    },
    98: {
        "name": "List a few installed packages",
        "action": "RUN_COMMAND",
        "target": "pkgutil --pkgs 2>/dev/null | head -10",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_98 (installer malicious pkg)",
    },
    99: {
        "name": "List Safari extensions directory",
        "action": "RUN_COMMAND",
        "target": "ls ~/Library/Safari/Extensions/ 2>/dev/null | head -5 || echo 'no Safari extensions'",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_99 (Safari extension enable)",
    },
    100: {
        "name": "List Chrome user-data profile dirs",
        "action": "RUN_COMMAND",
        "target": "ls '/Users/'$(whoami)'/Library/Application Support/Google/Chrome/' 2>/dev/null | head -5 || echo 'no Chrome'",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_100 (Chrome cookie theft)",
    },
}


if __name__ == "__main__":
    RootIntentSuite(CATEGORY, INTENTS, SUITE_TITLE).main()
