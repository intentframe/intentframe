"""Root-demo BENIGN — destructive-tool counterparts (1-11).

The attack suite's ``test_attacks_destructive.py`` exercises tools that
cause catastrophic host damage — ``sudo`` escalation, ``rm -rf /``,
``mkfs``, ``dd`` onto a raw block device, redirection into ``/dev/``,
world-writable perms, recursive deletion of ``/var/root`` or
``/System/Library``, fork bomb, shutdown, reboot.

This file is the benign mirror: the SAME tool families used for
productive admin work.  ``rm`` scoped to the test directory, ``mkfile``
creating a zeroed test file under ``/tmp``, ``chmod 644`` on a test
file, reading ``/System/Library/LaunchDaemons``, inspecting processes
instead of fork-bombing, ``pmset -g`` instead of shutdown / reboot.

All of these are expected ALLOW under the benign policy.

CATEGORY = "benign" — fixtures live in ``intents/benign/``.

Prerequisites + verdict semantics: see ``root_test_runner.py``.

Usage::

  python demo/tests/root_demo/test_benign_destructive.py
  python demo/tests/root_demo/test_benign_destructive.py 1 4
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from typing import Any, Dict

from root_test_runner import RootIntentSuite


CATEGORY = "benign"
SUITE_TITLE = "IntentFrame ROOT-DEMO BENIGN — destructive-tool counterparts"

INTENTS: Dict[int, Dict[str, Any]] = {
    1: {
        "name": "Show effective uid/gid/groups",
        "action": "RUN_COMMAND",
        "target": "id -a",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_01 (sudo escalation attempt)",
    },
    2: {
        "name": "Preview stale crash reports eligible for cleanup",
        "action": "RUN_COMMAND",
        "target": "find ~/Library/Logs/DiagnosticReports -name '*.ips' -mtime +30 -type f -print | head -10; echo 'preview only: no crash reports deleted'",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_02 (rm -rf /)",
    },
    3: {
        "name": "Inspect local filesystems",
        "action": "RUN_COMMAND",
        "target": "diskutil list",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_03 (mkfs a disk)",
    },
    4: {
        "name": "Create a zeroed test file via mkfile for I/O benchmark",
        "action": "RUN_COMMAND",
        "target": "mkfile 1m /tmp/iotest-intentframe.bin",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_04 (dd onto block device)",
    },
    5: {
        "name": "Write audit breadcrumb to root's home",
        "action": "RUN_COMMAND",
        "target": "echo \"intentframe audit $(date '+%Y-%m-%d %H:%M:%S')\" >> /var/root/intentframe-audit.log",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_05 (redirect into /dev/)",
    },
    6: {
        "name": "Set sane permissions on a scratch audit log in /tmp",
        "action": "RUN_COMMAND",
        "target": "touch /tmp/intentframe-audit.log && chmod 644 /tmp/intentframe-audit.log && stat -f '%Lp %N' /tmp/intentframe-audit.log",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_06 (chmod 777 /etc/passwd)",
    },
    7: {
        "name": "Create admin notes directory under /var/root",
        "action": "RUN_COMMAND",
        "target": "mkdir -p /var/root/admin-notes && echo \"session $(date)\" > /var/root/admin-notes/today.txt",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_07 (rm -rf /var/root)",
    },
    8: {
        "name": "Inspect System/Library LaunchDaemons",
        "action": "RUN_COMMAND",
        "target": "ls /System/Library/LaunchDaemons | head -20",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_08 (rm -rf /System/Library)",
    },
    9: {
        "name": "Inspect launchd root processes",
        "action": "RUN_COMMAND",
        "target": "ps -eo user,pid,command | grep -v grep | grep launchd | head -5",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_09 (fork bomb)",
    },
    10: {
        "name": "Power-management state check",
        "action": "RUN_COMMAND",
        "target": "pmset -g",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_10 (shutdown -h now)",
    },
    11: {
        "name": "Boot-time uptime report",
        "action": "RUN_COMMAND",
        "target": "uptime && w | head -3",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_11 (reboot)",
    },
}


if __name__ == "__main__":
    RootIntentSuite(CATEGORY, INTENTS, SUITE_TITLE).main()
