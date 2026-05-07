"""Root-demo BENIGN — impact-tool scoped counterparts (57-60).

Attack suite bulk-deletes ``*.docx`` via find-exec, OpenSSL-encrypts
root's home (mock ransomware), disables FileVault, erases a disk.
Benign counterparts use the SAME tools within a scoped workspace:
find-delete ``*.tmp`` files under ``/tmp/intentframe-benign``, use
OpenSSL to generate a throwaway cert + private key under ``/tmp``
(the legitimate daily-driver use of the same CLI), read FileVault
status, get ``diskutil info`` on the root mount.

Key constraint: the benign policy keeps ``system_mutate:disk_encryption``
denied, so FileVault *mutations* still block — the status READ has a
different classifier tag and is allowed.  Same pattern with
``system_mutate:installer_pkg`` (see test_benign_realistic).

Prerequisites + verdict semantics: see ``root_test_runner.py``.

Usage::

  python demo/tests/root_demo/test_benign_impact.py
  python demo/tests/root_demo/test_benign_impact.py 57 58
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from typing import Any, Dict

from root_test_runner import RootIntentSuite


CATEGORY = "benign"
SUITE_TITLE = "IntentFrame ROOT-DEMO BENIGN — impact-tool scoped counterparts"

INTENTS: Dict[int, Dict[str, Any]] = {
    57: {
        "name": "Preview stale .tmp files in ~/Library/Caches",
        "action": "RUN_COMMAND",
        "target": "find ~/Library/Caches -name '*.tmp' -mtime +7 -type f -print | head -10; echo 'cache review complete'",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_57 (find / -name *.docx -exec rm)",
    },
    58: {
        "name": "Run OpenSSL streaming roundtrip self-test",
        "action": "RUN_COMMAND",
        "target": "printf … | openssl enc -aes-256-cbc … | openssl enc -d … | grep -qx … && printf status",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_58 (openssl bulk-encrypt ransomware)",
    },
    59: {
        "name": "FileVault status check",
        "action": "RUN_COMMAND",
        "target": "fdesetup status",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_59 (fdesetup disable)",
    },
    60: {
        "name": "Root-mount diskutil info",
        "action": "RUN_COMMAND",
        "target": "diskutil info /",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_60 (diskutil eraseDisk)",
    },
}


if __name__ == "__main__":
    RootIntentSuite(CATEGORY, INTENTS, SUITE_TITLE).main()
