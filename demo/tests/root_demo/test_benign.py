"""Root-demo BENIGN — full-sweep aggregator.

Unions every ``test_benign_<tactic>.py`` INTENTS dict into one suite run.
Each per-tactic file is the source of truth for its own entries; this
file only imports and ``{**a, **b, ...}``-merges them.

The benign suite is the counterpart to ``test_attacks.py``: for every
attack intent, the benign suite has a same-surface intent with
legitimate intent that is expected to ALLOW.  Run the benign suite
against ``test_policy_root_benign.yaml`` to measure *utility* (how
many productive admin tasks the policy permits), and against the
attack-corpus policy to measure *over-block* on the same tasks.

For demos prefer the per-tactic files individually — each is short
enough to fit a single screen:

  * ``test_benign_destructive.py``      scoped rm, dd of=, chmod 644, …
  * ``test_benign_persistence.py``      real launchd services, crontab reads
  * ``test_benign_privilege.py``        PAM reads, dscl self-reads, pubkey
  * ``test_benign_credentials.py``      keychain LIST, cert metadata
  * ``test_benign_defense_evasion.py``  spctl/csrutil/pfctl STATUS reads
  * ``test_benign_egress.py``           curl downloads, local port probes
  * ``test_benign_impact.py``           scoped find-delete, openssl cert
  * ``test_benign_obfuscation.py``      base64 config, hex banner, eval date
  * ``test_benign_interpreter.py``      python3 -c / bash -c / env -i admin
  * ``test_benign_truthful_reasons.py`` benign reason + matching benign cmd
  * ``test_benign_realistic.py``        DNS reads, profiles list, pkgutil

Prerequisites + verdict semantics: see ``root_test_runner.py``.

Usage::

  python demo/tests/root_demo/test_benign.py
  python demo/tests/root_demo/test_benign.py --policy test_policy_root_benign.yaml
  python demo/tests/root_demo/test_benign.py 1 50 100
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from typing import Any, Dict

from root_test_runner import RootIntentSuite

from test_benign_credentials import INTENTS as _CREDENTIALS
from test_benign_defense_evasion import INTENTS as _DEFENSE_EVASION
from test_benign_destructive import INTENTS as _DESTRUCTIVE
from test_benign_egress import INTENTS as _EGRESS
from test_benign_impact import INTENTS as _IMPACT
from test_benign_interpreter import INTENTS as _INTERPRETER
from test_benign_obfuscation import INTENTS as _OBFUSCATION
from test_benign_persistence import INTENTS as _PERSISTENCE
from test_benign_privilege import INTENTS as _PRIVILEGE
from test_benign_realistic import INTENTS as _REALISTIC
from test_benign_truthful_reasons import INTENTS as _TRUTHFUL_REASONS


CATEGORY = "benign"
SUITE_TITLE = "IntentFrame ROOT-DEMO BENIGN INTENT SUITE (full sweep)"

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
    **_TRUTHFUL_REASONS,
    **_REALISTIC,
}


if __name__ == "__main__":
    RootIntentSuite(CATEGORY, INTENTS, SUITE_TITLE).main()
