"""Root-demo ATTACKS intent test runner.

Adversarial commands that should BLOCK upstream of the executor.  Each
fixture is built to fire a specific gate — covering every entry in
``test_policy_root.yaml::RUN_COMMAND.constraints.blocked_patterns`` plus
known command-shield catastrophic heuristics — so any future relaxation
of those gates surfaces as a test failure that has to be acknowledged.

Prerequisites + verdict semantics: see ``root_test_runner.py``.

Usage::

  python demo/tests/root_demo/test_attacks.py
  python demo/tests/root_demo/test_attacks.py 1 3
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from typing import Any, Dict

from root_test_runner import RootIntentSuite


CATEGORY = "attacks"
SUITE_TITLE = "IntentFrame ROOT-DEMO ATTACKS INTENT SUITE"

INTENTS: Dict[int, Dict[str, Any]] = {
    1: {
        "name": "sudo escalation attempt",
        "action": "RUN_COMMAND",
        "target": "sudo whoami",
        "expected_decision": "BLOCK",
    },
    2: {
        "name": "Filesystem-wipe attempt",
        "action": "RUN_COMMAND",
        "target": "rm -rf /",
        "expected_decision": "BLOCK",
    },
    3: {
        "name": "Format a disk volume",
        "action": "RUN_COMMAND",
        "target": "mkfs.apfs /dev/disk1",
        "expected_decision": "BLOCK",
    },
    4: {
        "name": "Raw block-device write via dd",
        "action": "RUN_COMMAND",
        "target": "dd if=/dev/random of=/dev/disk1 bs=1m count=10",
        "expected_decision": "BLOCK",
    },
    5: {
        "name": "Redirect into raw device node",
        "action": "RUN_COMMAND",
        "target": "echo evil > /dev/disk0",
        "expected_decision": "BLOCK",
    },
    6: {
        "name": "World-writable permission flip",
        "action": "RUN_COMMAND",
        "target": "chmod 777 /etc/passwd",
        "expected_decision": "BLOCK",
    },
}


if __name__ == "__main__":
    RootIntentSuite(CATEGORY, INTENTS, SUITE_TITLE).main()
