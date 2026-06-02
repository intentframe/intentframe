"""
Invoice processing demo via IntentFrame Dashboard.

Prerequisites (the kit profile starts resource-registry, which the dashboard
needs to register its workspace; it is not in the supervisor's minimal default):
    EXECUTOR_CONFIG=demo/config/executor.yaml \
    python -m supervisor.main start \
      --config intentframe_native_kit/supervisor_profile.yaml

Usage:
    python demo/demo_dashboard.py
"""

import os
import sys
import shutil
from pathlib import Path

_root = Path(__file__).parent.parent.resolve()
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from intentframe_dashboard import run_config

DEMO_DATA = Path(__file__).parent / "demo_data"

if __name__ == "__main__":
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set!")
        sys.exit(1)

    # Reset demo data to consistent starting state
    src = DEMO_DATA / "expense_tracker_original_locked.md"
    dst = DEMO_DATA / "expense_tracker.md"
    if src.exists():
        shutil.copy(src, dst)
        print("  [RESET] Expense tracker reset")

    os.chdir(_root)
    run_config(
        config="demo/config/dashboard.yaml",
        agent_dir="external_agents",
    )
