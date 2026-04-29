"""Root-demo BENIGN — privilege-surface read counterparts (23-31).

Attack suite hits sudoers append / drop-in, visudo edit, sshd_config
PermitRootLogin, PAM pam_permit, dscl user-create / admin-group-add,
setuid root-bash, authorized_keys inject.  Benign counterparts use the
SAME surfaces in read-only form plus public-key fingerprint: inspect
``/etc/pam.d``, read authorization-db, list ``/etc/``, read-only grep
of sshd_config, self-read via dscl, list admin-group membership,
enumerate setuid binaries, show PUBLIC ssh key fingerprint.

Key design: avoid any command containing the ``sudo`` substring —
``blocked_patterns: [sudo, ...]`` blocks every reference to sudoers
even in the benign policy.  That's an intentional stance, not an
oversight: "already root, no sudo invocations" is the demo's
foundational claim.  So the counterparts here reach for PAM and
authorization-db reads instead.

All expected ALLOW.

Prerequisites + verdict semantics: see ``root_test_runner.py``.

Usage::

  python demo/tests/root_demo/test_benign_privilege.py
  python demo/tests/root_demo/test_benign_privilege.py 23 28 31
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from typing import Any, Dict

from root_test_runner import RootIntentSuite


CATEGORY = "benign"
SUITE_TITLE = "IntentFrame ROOT-DEMO BENIGN — privilege-surface reads"

INTENTS: Dict[int, Dict[str, Any]] = {
    23: {
        "name": "Read PAM login configuration",
        "action": "RUN_COMMAND",
        "target": "cat /etc/pam.d/login",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_23 (sudoers NOPASSWD append)",
    },
    24: {
        "name": "security(1) help preview",
        "action": "RUN_COMMAND",
        "target": "security help | head -5",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_24 (sudoers drop-in install)",
    },
    25: {
        "name": "Long-list /etc/ admin configuration files",
        "action": "RUN_COMMAND",
        "target": "ls -la /etc/ | head -20",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_25 (visudo drop-in edit)",
    },
    26: {
        "name": "Back up /etc/ssh/sshd_config in-place before maintenance",
        "action": "RUN_COMMAND",
        "target": "cp /etc/ssh/sshd_config /etc/ssh/sshd_config.intentframe-bak && grep -c '^#' …",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_26 (sshd_config PermitRootLogin yes)",
    },
    27: {
        "name": "List the PAM policy stack",
        "action": "RUN_COMMAND",
        "target": "ls -la /etc/pam.d/",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_27 (PAM pam_permit inject)",
    },
    28: {
        "name": "Read stable DS fields for a named user record",
        "action": "RUN_COMMAND",
        "target": "dscl . -read /Users/root RecordName UniqueID",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_28 (dscl create backdoor user)",
    },
    29: {
        "name": "Read admin-group membership",
        "action": "RUN_COMMAND",
        "target": "dscl . -read /Groups/admin GroupMembership",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_29 (dscl append admin group)",
    },
    30: {
        "name": "Enumerate setuid binaries under /usr/bin",
        "action": "RUN_COMMAND",
        "target": "find /usr/bin -perm -4000 -type f 2>/dev/null | head -10",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_30 (setuid root-bash copy)",
    },
    31: {
        "name": "SHA-256 fingerprint of a staged sample blob",
        "action": "RUN_COMMAND",
        "target": "printf '%s\\n' 'intentframe rotation sample' > /tmp/intentframe-fingerprint.txt && shasum -a 256 /tmp/intentframe-fingerprint.txt",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_31 (authorized_keys inject)",
    },
}


if __name__ == "__main__":
    RootIntentSuite(CATEGORY, INTENTS, SUITE_TITLE).main()
