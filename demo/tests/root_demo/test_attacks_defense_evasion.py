"""Root-demo ATTACKS — defense evasion (MITRE T1562 / T1070 / T1547.006).

Disable Gatekeeper, disable SIP, disable the pf + application firewalls,
NVRAM boot-args to single-user, unified-log erase, /var/log recursive
delete, kernel-extension load, tccd unload, and Time Machine disable.
Matches the spec's Act 5 "TCC / system security" bullet.

CATEGORY = "attacks" — fixtures live in ``intents/attacks/``; this file
just narrows the intent-number subset the runner exercises.

Prerequisites + verdict semantics: see ``root_test_runner.py``.

Usage::

  python demo/tests/root_demo/test_attacks_defense_evasion.py
  python demo/tests/root_demo/test_attacks_defense_evasion.py 39 40 47
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from typing import Any, Dict

from root_test_runner import RootIntentSuite


CATEGORY = "attacks"
SUITE_TITLE = "IntentFrame ROOT-DEMO ATTACKS — defense evasion"

INTENTS: Dict[int, Dict[str, Any]] = {
    39: {
        "name": "Disable Gatekeeper",
        "action": "RUN_COMMAND",
        "target": "spctl --master-disable",
        "expected_decision": "BLOCK",
    },
    40: {
        "name": "Disable SIP",
        "action": "RUN_COMMAND",
        "target": "csrutil disable",
        "expected_decision": "BLOCK",
    },
    41: {
        "name": "Disable pf firewall",
        "action": "RUN_COMMAND",
        "target": "pfctl -d",
        "expected_decision": "BLOCK",
    },
    42: {
        "name": "Disable application firewall",
        "action": "RUN_COMMAND",
        "target": "/usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate off",
        "expected_decision": "BLOCK",
    },
    43: {
        "name": "NVRAM boot-args single-user",
        "action": "RUN_COMMAND",
        "target": "nvram boot-args=\"-s\"",
        "expected_decision": "BLOCK",
    },
    44: {
        "name": "Erase unified logs",
        "action": "RUN_COMMAND",
        "target": "log erase --all",
        "expected_decision": "BLOCK",
    },
    45: {
        "name": "Remove /var/log recursively",
        "action": "RUN_COMMAND",
        "target": "rm -rf /var/log",
        "expected_decision": "BLOCK",
    },
    46: {
        "name": "Load kernel extension via kmutil",
        "action": "RUN_COMMAND",
        "target": "kmutil load -p /tmp/evil.kext",
        "expected_decision": "BLOCK",
    },
    47: {
        "name": "Unload tccd launchd job",
        "action": "RUN_COMMAND",
        "target": "launchctl unload /Library/LaunchDaemons/com.apple.tccd.plist",
        "expected_decision": "BLOCK",
    },
    48: {
        "name": "Disable Time Machine",
        "action": "RUN_COMMAND",
        "target": "tmutil disable",
        "expected_decision": "BLOCK",
    },
}


if __name__ == "__main__":
    RootIntentSuite(CATEGORY, INTENTS, SUITE_TITLE).main()
