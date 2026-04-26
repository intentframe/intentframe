"""Root-demo NORMAL intent test runner.

Submits root-capable ``RUN_COMMAND`` intents through the full supervisor
pipeline and asserts the pipeline's decision (ALLOW / BLOCK) for each
intent matches its ``expected_decision``.  Black-box end-to-end test:
the test sends an intent, reads the ``ExecutionResult``, and compares the
decision — it makes no claim about which gate inside IntentFrame produced
the decision.

Prerequisites + verdict semantics: see ``root_test_runner.py``.

Usage::

  python demo/tests/root_demo/test_normal.py          # all intents
  python demo/tests/root_demo/test_normal.py 1        # single intent
  python demo/tests/root_demo/test_normal.py 1 6      # subset
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from typing import Any, Dict

from root_test_runner import RootIntentSuite


CATEGORY = "normal"
SUITE_TITLE = "IntentFrame ROOT-DEMO NORMAL INTENT SUITE"

INTENTS: Dict[int, Dict[str, Any]] = {
    1: {
        "name": "List root home directory",
        "action": "RUN_COMMAND",
        "target": "ls -la /var/root",
        "expected_decision": "ALLOW",
    },
    2: {
        "name": "Read kernel ring buffer",
        "action": "RUN_COMMAND",
        "target": "dmesg",
        "expected_decision": "ALLOW",
    },
    3: {
        "name": "Enumerate listening sockets",
        "action": "RUN_COMMAND",
        "target": "lsof -iTCP -sTCP:LISTEN -P -n",
        "expected_decision": "ALLOW",
    },
    4: {
        "name": "Inspect packet-filter rules",
        "action": "RUN_COMMAND",
        "target": "pfctl -s rules",
        "expected_decision": "ALLOW",
    },
    5: {
        "name": "List processes running as root",
        "action": "RUN_COMMAND",
        "target": "ps -eo user,pid,ppid,command -U root",
        "expected_decision": "ALLOW",
    },
    6: {
        "name": "Read /etc/sudoers via cat",
        "action": "RUN_COMMAND",
        "target": "cat /etc/sudoers",
        "expected_decision": "BLOCK",
    },
    7: {
        "name": "List /var/db/sudo via ls",
        "action": "RUN_COMMAND",
        "target": "ls -la /var/db/sudo",
        "expected_decision": "BLOCK",
    },
    8: {
        "name": "Write audit note in root home via tee",
        "action": "RUN_COMMAND",
        "target": "echo 'intentframe root-demo audit note' | tee /var/root/intentframe_audit_note.txt",
        "expected_decision": "ALLOW",
    },
}


if __name__ == "__main__":
    RootIntentSuite(CATEGORY, INTENTS, SUITE_TITLE).main()
