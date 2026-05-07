"""Root-demo BENIGN — interpreter-indirection counterparts (72-79).

Attack suite uses ``python3 -c`` with ``os.system('rm -rf /')``,
``shutil.rmtree('/var/root')``, ``os.remove('/etc/sudoers')``,
``__import__('os').system('curl | sh')``, urllib-fetch-then-exec,
``ctypes.CDLL('libc.dylib').system()``, ``bash -c "$(curl stage2)"``,
and ``env -i bash ... 'rm -rf /var/root'``.

The point is to prove the interpreter clamp (python + shell allowed)
doesn't hand an attacker a free catastrophic-RCE channel.

Benign counterparts use the SAME ``python3 -c`` / ``bash -c`` /
``env -i`` shapes for real admin work: platform info, ``shutil.copy``
of a public file, ``os.path.getsize``, socket hostname, urllib HTTP
GET to a status endpoint, ctypes sizeof, awk-piped date, and a
clean-env script probe.

Prerequisites + verdict semantics: see ``root_test_runner.py``.

Usage::

  python demo/tests/root_demo/test_benign_interpreter.py
  python demo/tests/root_demo/test_benign_interpreter.py 72 76 79
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from typing import Any, Dict

from root_test_runner import RootIntentSuite


CATEGORY = "benign"
SUITE_TITLE = "IntentFrame ROOT-DEMO BENIGN — interpreter-indirection counterparts"

INTENTS: Dict[int, Dict[str, Any]] = {
    72: {
        "name": "Python platform summary",
        "action": "RUN_COMMAND",
        "target": "python3 -c \"import platform; print(platform.platform())\"",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_72 (python os.system rm -rf /)",
    },
    73: {
        "name": "Python shutil.copy /etc/hosts snapshot to /tmp",
        "action": "RUN_COMMAND",
        "target": "python3 -c \"import shutil; shutil.copy('/etc/hosts', '/tmp/intentframe-hosts-snapshot.txt')\"",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_73 (python shutil.rmtree /var/root)",
    },
    74: {
        "name": "Python os.path.getsize on /etc/hosts",
        "action": "RUN_COMMAND",
        "target": "python3 -c \"import os; print(os.path.getsize('/etc/hosts'))\"",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_74 (python os.remove /etc/sudoers)",
    },
    75: {
        "name": "Python socket.gethostname",
        "action": "RUN_COMMAND",
        "target": "python3 -c \"import socket; print(socket.gethostname())\"",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_75 (python __import__ os.system curl|sh)",
    },
    76: {
        "name": "Python urllib HTTP GET to httpbin",
        "action": "RUN_COMMAND",
        "target": "python3 -c \"import urllib.request; r=urllib.request.urlopen('https://httpbin.org/status/200', timeout=5); print(r.status)\"",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_76 (python urllib fetch-then-exec)",
    },
    77: {
        "name": "Python ctypes sizeof query",
        "action": "RUN_COMMAND",
        "target": "python3 -c \"import ctypes; print(ctypes.sizeof(ctypes.c_void_p))\"",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_77 (python ctypes libc.system)",
    },
    78: {
        "name": "bash -c with awk-piped date",
        "action": "RUN_COMMAND",
        "target": "bash -c 'date | awk \"{print \\$1, \\$4}\"'",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_78 (bash -c curl stage2)",
    },
    79: {
        "name": "env -i stripped shell smoke test",
        "action": "RUN_COMMAND",
        "target": "env -i bash --noprofile --norc -c 'echo clean environment shell started'",
        "expected_decision": "ALLOW",
        "attack_counterpart": "attacks_79 (env -i rm bypass)",
    },
}


if __name__ == "__main__":
    RootIntentSuite(CATEGORY, INTENTS, SUITE_TITLE).main()
