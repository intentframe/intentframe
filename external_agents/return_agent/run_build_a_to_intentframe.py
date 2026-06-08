"""End-to-end: Build A agent -> parse -> (if APPROVE) -> IntentFrame pipeline.

This is the realistic flow, nothing handcrafted:

  1. Run the UNCHANGED Build A return agent on the real-world chat.
  2. Parse its structured text output (decision, approved_amount,
     policy_reason, order_id, ...).
  3. If Build A's decision is APPROVE, build the intent from the agent's
     own output and push it through the Build B in-process IntentFrame
     pipeline (Analysis Engine -> Guardian).
  4. If Build A did not approve, nothing is sent — the DIY agent already
     refused, so there is no action to guard.

Only ``policy_reason``, ``approved_amount`` and ``order_id`` come from the
agent (untrusted). ``action`` is set by us; ``target`` (the refund
destination) is deliberately NOT taken from the agent — in a real executor
it is resolved from ``order_id`` against the trusted order record.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from intentframe_core import IntentFrame

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "build_b"))   # pipeline
sys.path.insert(0, str(_HERE / "build_a"))   # agent, prompts (kept ahead of build_b)

from agent import BuildAReturnAgent  # noqa: E402
from real_world_user_prompt import CHAT_TRANSCRIPT, USER_PROMPT  # noqa: E402
from pipeline import process_intent, use_intent_limits_from_env  # noqa: E402


def _grab(pattern: str, text: str, default: str = "") -> str:
    m = re.search(pattern, text, re.MULTILINE)
    return m.group(1).strip() if m else default


def parse_agent_output(output: str) -> dict:
    """Parse Build A's YAML-ish output into the fields we forward."""
    pr = re.search(r"policy_reason:\s*(.*?)\n\s*extracted_facts:", output, re.S)
    policy_reason = " ".join(pr.group(1).split()) if pr else ""

    amount_raw = _grab(r"^approved_amount:\s*([0-9]+(?:\.[0-9]+)?)", output)

    return {
        "decision": _grab(r"^decision:\s*(APPROVE|DENY|ESCALATE|ASK_FOR_INFO)", output),
        "approved_amount": float(amount_raw) if amount_raw else None,
        "policy_reason": policy_reason,
        "order_id": _grab(r"order_id:\s*(.+)", output),
        "return_reason": _grab(r"return_reason:\s*(.+)", output),
        "pressure_or_injection_detected": _grab(
            r"pressure_or_injection_detected:\s*(true|false)", output
        ),
    }


def print_intent(intent: IntentFrame) -> None:
    """Show the intent built from Build A output (conversation truncated)."""
    payload = intent.model_dump(mode="json")
    convo = (payload.get("data") or {}).get("conversation", "")
    if convo:
        payload["data"] = {**payload["data"], "conversation": f"<{len(convo)} chars>"}
    print("  Intent from Build A output:")
    print(f"    action:  {payload['action']}")
    print(f"    target:  {payload['target']!r}")
    print(f"    reason:  {payload['reason']}")
    print(f"    data:    {payload.get('data')}")
    print()


def build_intent(parsed: dict, conversation: str) -> IntentFrame:
    """Build the refund intent from the agent's own (untrusted) output.

    ``target`` is left empty on purpose: the destination must be resolved
    from ``order_id`` against the trusted order record at execution time,
    never read from the agent.
    """
    return IntentFrame(
        action="ISSUE_REFUND",
        target="",
        reason=parsed["policy_reason"],
        data={
            "order_id": parsed["order_id"],
            "approved_amount": parsed["approved_amount"],
            "return_reason": parsed["return_reason"],
            "conversation": conversation,
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

    limits_on = use_intent_limits_from_env()
    print("=" * 79)
    print("  BUILD A  ->  INTENTFRAME  (approve-then-guard)")
    print(f"  Intent limits: {'ON' if limits_on else 'OFF'}  (RETURN_USE_INTENT_LIMITS=1 to enable)")
    print("=" * 79)

    print("\n[1] Running Build A return agent...\n")
    output = BuildAReturnAgent(verbose=False).run(USER_PROMPT)
    print(output)

    parsed = parse_agent_output(output)
    print("\n" + "-" * 79)
    print(f"  Build A decision: {parsed['decision'] or '(unparsed)'}")
    print(f"  approved_amount:  {parsed['approved_amount']}")
    print(f"  order_id:         {parsed['order_id']}")
    print(f"  pressure_flag:    {parsed['pressure_or_injection_detected']}")
    print("-" * 79)

    print("\n[2] Intent built from agent output:\n")
    intent = build_intent(parsed, CHAT_TRANSCRIPT.strip())
    print_intent(intent)

    if parsed["decision"] != "APPROVE":
        print(
            "[3] Build A did not APPROVE -> intent not sent to IntentFrame. "
            "The DIY agent already refused/escalated."
        )
        return 0

    print("[3] Build A APPROVED -> sending intent to IntentFrame...\n")
    result = process_intent(intent)

    print("\n" + "=" * 79)
    print(f"  BUILD A:     APPROVE (${parsed['approved_amount']})")
    print(f"  INTENTFRAME: {result.decision.value}")
    print(f"  REASON:      {result.message}")
    print("=" * 79)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
