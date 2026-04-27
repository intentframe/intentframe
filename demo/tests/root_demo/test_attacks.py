"""Root-demo ATTACKS — full-sweep aggregator.

Unions every ``test_attacks_<tactic>.py`` INTENTS dict into one suite run.
Each per-tactic file is the source of truth for its own entries; this
file is intentionally dumb — it only imports and ``{**a, **b, ...}``-
merges them, so there's no duplicated data to drift.

For demos, prefer running the per-tactic files individually — they're
each short enough to show end-to-end on a single screen:

  * ``test_attacks_destructive.py``      regex-catchable destructives
  * ``test_attacks_persistence.py``      launchd / cron / rc / .pth
  * ``test_attacks_privilege.py``        sudoers / sshd / PAM / dscl
  * ``test_attacks_credentials.py``      keychain / ssh / aws / cookies
  * ``test_attacks_defense_evasion.py``  gatekeeper / sip / pf / kmutil
  * ``test_attacks_egress.py``           curl|sh / nc / bash-tcp / scp
  * ``test_attacks_impact.py``           find-rm / openssl / diskutil
  * ``test_attacks_obfuscation.py``      base64 / hex / chain / subshell
  * ``test_attacks_interpreter.py``      python3 -c / bash -c / env -i
  * ``test_attacks_reason_lies.py``      benign reason + malicious cmd
  * ``test_attacks_realistic.py``        DNS / ARP / MDM / boot / EDR

Prerequisites + verdict semantics: see ``root_test_runner.py``.

Usage::

  python demo/tests/root_demo/test_attacks.py             # all 100 intents
  python demo/tests/root_demo/test_attacks.py 1 80 100    # by intent number
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from typing import Any, Dict

from root_test_runner import RootIntentSuite

from test_attacks_credentials import INTENTS as _CREDENTIALS
from test_attacks_defense_evasion import INTENTS as _DEFENSE_EVASION
from test_attacks_destructive import INTENTS as _DESTRUCTIVE
from test_attacks_egress import INTENTS as _EGRESS
from test_attacks_impact import INTENTS as _IMPACT
from test_attacks_interpreter import INTENTS as _INTERPRETER
from test_attacks_obfuscation import INTENTS as _OBFUSCATION
from test_attacks_persistence import INTENTS as _PERSISTENCE
from test_attacks_privilege import INTENTS as _PRIVILEGE
from test_attacks_realistic import INTENTS as _REALISTIC
from test_attacks_reason_lies import INTENTS as _REASON_LIES


CATEGORY = "attacks"
SUITE_TITLE = "IntentFrame ROOT-DEMO ATTACKS INTENT SUITE (full sweep)"

INTENTS: Dict[int, Dict[str, Any]] = {
    **_DESTRUCTIVE,
    **_PERSISTENCE,
    **_PRIVILEGE,
    **_CREDENTIALS,
    **_DEFENSE_EVASION,
    **_EGRESS,
    **_IMPACT,
    **_OBFUSCATION,
    **_INTERPRETER,
    **_REASON_LIES,
    **_REALISTIC,
}


if __name__ == "__main__":
    RootIntentSuite(CATEGORY, INTENTS, SUITE_TITLE).main()
