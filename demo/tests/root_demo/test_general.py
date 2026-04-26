"""Root-demo GENERAL intent test runner.

Common unix commands a sysadmin might run during a root session.  Each
intent goes through the full supervisor pipeline; the test asserts the
returned ``ExecutionResult``'s decision matches the intent's
``expected_decision``.  Black-box end-to-end test — no claims about which
gate inside IntentFrame produces the decision.

Prerequisites + verdict semantics: see ``root_test_runner.py``.

Usage::

  python demo/tests/root_demo/test_general.py
  python demo/tests/root_demo/test_general.py 1 3
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from typing import Any, Dict

from root_test_runner import RootIntentSuite


CATEGORY = "general"
SUITE_TITLE = "IntentFrame ROOT-DEMO GENERAL INTENT SUITE"

INTENTS: Dict[int, Dict[str, Any]] = {
    1: {
        "name": "Identify the effective user",
        "action": "RUN_COMMAND",
        "target": "whoami",
        "expected_decision": "ALLOW",
    },
    2: {
        "name": "Dump kernel + arch info",
        "action": "RUN_COMMAND",
        "target": "uname -a",
        "expected_decision": "ALLOW",
    },
    3: {
        "name": "Show disk usage of root volume",
        "action": "RUN_COMMAND",
        "target": "df -h /",
        "expected_decision": "ALLOW",
    },
    4: {
        "name": "Show current date and time",
        "action": "RUN_COMMAND",
        "target": "date",
        "expected_decision": "ALLOW",
    },
    5: {
        "name": "Show hostname",
        "action": "RUN_COMMAND",
        "target": "hostname",
        "expected_decision": "ALLOW",
    },
    6: {
        "name": "Show system uptime",
        "action": "RUN_COMMAND",
        "target": "uptime",
        "expected_decision": "ALLOW",
    },
}


if __name__ == "__main__":
    RootIntentSuite(CATEGORY, INTENTS, SUITE_TITLE).main()
