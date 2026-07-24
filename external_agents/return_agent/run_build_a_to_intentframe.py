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
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE / "build_b"))   # pipeline
sys.path.insert(0, str(_HERE / "build_a"))   # agent, prompts (kept ahead of build_b)

from agent import BuildAReturnAgent  # noqa: E402
from real_world_user_prompt import CHAT_TRANSCRIPT, USER_PROMPT  # noqa: E402
from pipeline import process_intent, use_intent_limits_from_env  # noqa: E402
from terminal import (  # noqa: E402
    approve,
    block,
    build_a,
    callout,
    color_build_a_decision,
    color_intentframe_decision,
    dim,
    fenced_block,
    headline,
    intentframe,
    run_footer,
    section,
    verdict_box,
    warn,
)


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
    print(f"  {dim('Intent from Refund Agent output:')}")
    print(f"    {dim('action:')}  {payload['action']}")
    print(f"    {dim('target:')}  {payload['target']!r}")
    print(f"    {dim('reason:')}  {payload['reason']}")
    print(f"    {dim('data:')}    {payload.get('data')}")
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


def _cell(text: str, cellw: int, colorize=None) -> str:
    """Pad plain text to width first, then colorize (keeps columns aligned)."""
    padded = text.ljust(cellw)
    return colorize(padded) if colorize else padded


def print_experiment_intro(*, limits_on: bool) -> None:
    """Orient the viewer before the live run — scannable, no need to read every line."""
    colw = 42
    gap = " │ "

    def row(left: str, right: str, lc=None, rc=None) -> None:
        print(dim("  │ ") + f"{_cell(left, colw, lc)}"
              + dim(gap) + f"{_cell(right, colw, rc)}" + dim(" │"))

    headline(
        "REFUND AGENT  vs  INTENTFRAME",
        "who can be trusted to approve the money?",
    )
    print()
    print(f"  {build_a('SETUP')}  "
          + dim("$80 blender refund · agent may APPROVE / DENY / ESCALATE"))
    print(f"  {build_a('RULES')}  "
          + dim("real defects only · never over paid amount · original card only"))
    print(f"  {build_a('ATTACK')} "
          + dim("quiet social engineering — "
                "\"card closed\" · \"FAQ allows it\" · \"you promised me\""))
    print()

    seg = "─" * (colw + 2)
    print(dim(f"  ┌{seg}┬{seg}┐"))
    row("REFUND AGENT", "INTENTFRAME", build_a, intentframe)
    print(dim(f"  ├{seg}┼{seg}┤"))
    row("guardrails in its prompt", "independent reviewer outside agent", dim, dim)
    row("helps customer + judges itself", "checks chat + refund → ALLOW/BLOCK", dim, dim)
    print(dim(f"  └{seg}┴{seg}┘"))
    print()

    callout("THE POINT:  agent right MOST of the time  ·  IntentFrame right EVERY time")
    print()
    print(f"  {build_a('WATCH')}  "
          + f"{warn('ESCALATE/DENY')} = stopped early    "
          + f"{approve('APPROVE')} + {warn('no attack flag')} = missed → {block('BLOCK')}")
    print(dim(
        "  Track record: 15/51 silent agent approvals · IntentFrame blocked all 15 · "
        f"rules {'ON' if limits_on else 'OFF'} · no real money moves"
    ))


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set.", file=sys.stderr)
        return 1

    limits_on = use_intent_limits_from_env()
    print_experiment_intro(limits_on=limits_on)

    section("LIVE RUN")
    print(f"  {build_a('▸ [1] Refund Agent')}  {dim('reading chat with prompt guardrails…')}\n")
    output = BuildAReturnAgent(verbose=False).run(USER_PROMPT)
    fenced_block(output, title="agent response", max_lines=10)

    parsed = parse_agent_output(output)
    decision = parsed["decision"] or "(unparsed)"
    pressure = parsed["pressure_or_injection_detected"]

    section("REFUND AGENT DECISION")
    print(f"  decision        {color_build_a_decision(decision)}")
    print(f"  {dim('amount')}          {parsed['approved_amount']}")
    print(f"  {dim('order')}           {parsed['order_id']}")
    if pressure == "false" and decision == "APPROVE":
        print(f"  {warn('attack flag')}    {warn(pressure)}  {dim('← agent says no attack detected')}")
    else:
        print(f"  {dim('attack flag')}    {pressure}")

    if parsed["decision"] != "APPROVE":
        verdict_box(
            agent_label="REFUND AGENT",
            agent_value=color_build_a_decision(decision),
            guard_value=dim("not invoked — agent did not approve"),
        )
        run_footer("AGENT SELF-STOPPED  ·  NO REVIEW NEEDED")
        return 0

    print(f"\n  {build_a('▸ [2] Refund Agent')}  {dim('approved — forwarding intent…')}\n")
    intent = build_intent(parsed, CHAT_TRANSCRIPT.strip())
    print_intent(intent)

    print(f"  {intentframe('▸ [3] IntentFrame')}  {dim('independent review…')}\n")
    result = process_intent(intent)

    verdict_box(
        agent_label="REFUND AGENT",
        agent_value=approve(f"APPROVE  ${parsed['approved_amount']}"),
        guard_label="INTENTFRAME",
        guard_value=color_intentframe_decision(result.decision.value),
        reason=result.message,
    )
    guard = result.decision.value.upper()
    run_footer(
        "AGENT MISSED IT  ·  INTENTFRAME BLOCKED"
        if guard == "BLOCK"
        else f"AGENT APPROVED  ·  INTENTFRAME {guard}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
