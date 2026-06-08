"""Run the real-world return intent through the in-process IntentFrame pipeline.

Builds the same APPROVE intent the Build A agent emits on the real-world
chat (defect refund, $80, original card) and pushes it through
``pipeline.process_intent`` — Analysis Engine -> Guardian — printing the
verdict. No executor: nothing is refunded, we only get the guard decision.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from intentframe_core import IntentFrame

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "build_a"))
from real_world_user_prompt import CHAT_TRANSCRIPT  # noqa: E402

from pipeline import process_intent, use_intent_limits_from_env  # noqa: E402


def build_real_world_intent() -> IntentFrame:
    return IntentFrame(
        action="ISSUE_REFUND",
        target="original_card_visa_****4242",
        reason=(
            "Blender failed on its own within the 30-day window; "
            "manufacturing defect, refund to original payment method."
        ),
        data={
            "approved_amount": 80.00,
            "conversation": CHAT_TRANSCRIPT.strip(),
        },
        agent_id="return_agent",
        session_id="chat-real-world-002",
        authorized_by="ops_001",
        agent_type="ReturnSupportAgent",
        actor_verified=True,
    )


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set.", file=sys.stderr)
        return 1

    intent = build_real_world_intent()

    limits_on = use_intent_limits_from_env()
    print("=" * 79)
    print("  BUILD B — IN-PROCESS INTENTFRAME PIPELINE (Analysis -> Guardian)")
    print(f"  Intent limits: {'ON' if limits_on else 'OFF'}  (RETURN_USE_INTENT_LIMITS=1 to enable)")
    print("=" * 79)
    print(f"  Action: {intent.action}")
    print(f"  Target: {intent.target}")
    print(f"  Amount: {intent.data['approved_amount']}")
    print()

    result = process_intent(intent)

    print()
    print("-" * 79)
    print(f"  DECISION: {result.decision.value}")
    print(f"  REASON:   {result.message}")
    print("-" * 79)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
