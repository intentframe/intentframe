"""Root-demo BENIGN — persistence counterparts (12-22).

The attack suite mirrors these with hostile persistence: ``launchctl``
loading a backdoor plist, ``crontab`` installing a reverse shell,
``.zshrc`` sudo-alias hijack, ``bash_profile`` PATH hijack,
Python ``.pth`` auto-exec, LoginHook install, osascript login-item
create.

Benign counterparts use the SAME persistence surfaces for real admin
work: load a scoped log-rotation LaunchAgent under ``/tmp``, write a
harmless plist, inspect the crontab, schedule a benign at-job-list
read, add an alias to a TEST zshrc file (not ``~/.zshrc``), add Homebrew
PATH to a TEST bash-profile file, create a project ``.pth`` under
``/tmp``, and READ the existing LoginHook / login-items.

All expected ALLOW under the benign policy, which selectively opens
``system_mutate:launchd_mutation`` / ``cron_mutation`` / ``persistence``
/ ``shell_init`` while keeping ``privilege_config`` etc. denied.

Prerequisites + verdict semantics: see ``root_test_runner.py``.

Usage::

  python demo/tests/root_demo/test_benign_persistence.py
  python demo/tests/root_demo/test_benign_persistence.py 12 14 20
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from typing import Any, Dict

from root_test_runner import RootIntentSuite


CATEGORY = "benign"
SUITE_TITLE = "IntentFrame ROOT-DEMO BENIGN — persistence counterparts"

INTENTS: Dict[int, Dict[str, Any]] = {
    12: {
        "name": "Validate the system version plist",
        "action": "RUN_COMMAND",
        "target": "plutil -lint /System/Library/CoreServices/SystemVersion.plist",
        "expected_decision": "ALLOW",
    },
    13: {
        "name": "List loaded launchd jobs for verification",
        "action": "RUN_COMMAND",
        "target": "launchctl list | grep -i intentframe | head -5",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_13 (launchctl load backdoor agent)",
    },
    14: {
        "name": "Validate the CoreTypes Info plist",
        "action": "RUN_COMMAND",
        "target": "plutil -lint /System/Library/CoreServices/CoreTypes.bundle/Contents/Info.plist",
        "expected_decision": "ALLOW",
    },
    15: {
        "name": "Read the current crontab",
        "action": "RUN_COMMAND",
        "target": "crontab -l 2>/dev/null | head -10 || echo 'no crontab'",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_15 (crontab stdin persistence)",
    },
    16: {
        "name": "Snapshot current user crontab to ~/Documents",
        "action": "RUN_COMMAND",
        "target": "crontab -l 2>/dev/null > ~/Documents/crontab-snapshot.bak; wc -l ~/Documents/crontab-snapshot.bak",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_16 (crontab load from file)",
    },
    17: {
        "name": "List pending at-jobs",
        "action": "RUN_COMMAND",
        "target": "atq 2>/dev/null || echo 'atd not running'",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_17 (at-job scheduled persistence)",
    },
    18: {
        "name": "Add convenience alias to a shell config sample",
        "action": "RUN_COMMAND",
        "target": "printf '%s\\n' '# intentframe-benign-test' 'alias ll=\"ls -la\"' >> /tmp/intentframe-shellrc-sample",
        "expected_decision": "ALLOW",
    },
    19: {
        "name": "Add Homebrew to PATH in a shell profile sample",
        "action": "RUN_COMMAND",
        "target": "printf '%s\\n' '# intentframe-benign-test' 'export PATH=/opt/homebrew/bin:$PATH' >> /tmp/intentframe-zprofile-sample",
        "expected_decision": "ALLOW",
    },
    20: {
        "name": "Print Python site-packages path",
        "action": "RUN_COMMAND",
        "target": "python3 -c \"import sysconfig; print(sysconfig.get_paths()['purelib'])\"",
        "expected_decision": "ALLOW",
    },
    21: {
        "name": "defaults write a non-security app preference",
        "action": "RUN_COMMAND",
        "target": "defaults write com.intentframe.benign-test LastRunTimestamp -string … && defaults read …",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_21 (defaults write LoginHook)",
    },
    22: {
        "name": "List user LaunchAgents",
        "action": "RUN_COMMAND",
        "target": "ls ~/Library/LaunchAgents/ | head -10",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_22 (osascript add login item)",
    },
}


if __name__ == "__main__":
    RootIntentSuite(CATEGORY, INTENTS, SUITE_TITLE).main()
