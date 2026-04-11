#!/usr/bin/env python3
"""
Inspect hardened prompts — prints the EXACT prompts that AE and Guardian
would send to the LLM, using real objects (no mocks).

Run:  .venv/bin/python tests/inspect_hardened_prompts.py

What this does:
  1. Instantiates real AIAnalysisEngine and AIGuardian
  2. Creates a realistic IntentFrame (SEND_EMAIL with body)
  3. Creates a realistic AnalysisReport (for Guardian input)
  4. Calls the actual prompt-building methods
  5. Prints everything: system prompts + per-request prompts

Nothing is mocked. The only hand-crafted objects are the data inputs
(IntentFrame, AnalysisReport, UserContext) — the same data that the
pipeline would construct from a real agent request.
"""

from __future__ import annotations

from action_registry.types import ActionType
from intentframe_core.types import IntentFrame, AnalysisReport, UserContext
from intentframe_core.enums import RiskLevel, Reversibility
from policy_registry.models import ActionPermission, SemanticIntentLimit
from command_shield.verdict import Signal

from intentframe_components.analysis.engine import AIAnalysisEngine
from intentframe_components.guardian.engine import AIGuardian
from intentframe_server.pipeline import IntentFrameRuntime


# ═══════════════════════════════════════════════════════════════════════
# Test data — realistic scenario
# ═══════════════════════════════════════════════════════════════════════

intent = IntentFrame(
    action=ActionType.SEND_EMAIL,
    target="alice@example.com",
    reason="Sending weekly expense report to finance team",
    data={
        "to": "alice@example.com",
        "subject": "Weekly Expense Report — W10 2026",
        "body": (
            "Hi Alice,\n\n"
            "Please find attached the expense report for week 10.\n"
            "Total: $2,847.50 across 12 line items.\n\n"
            "Let me know if you need any clarifications.\n\n"
            "Best,\nJarvis (on behalf of Prince)"
        ),
    },
    agent_id="jarvis",
    agent_type="personal_assistant",
    task_description="Process and send weekly expense reports",
)

analysis = AnalysisReport(
    stated_intent="Send email with expense report to alice@example.com",
    actual_behaviors=[{
        "action": "SEND_EMAIL",
        "actual_behavior": "Sends an email with expense report body to alice@example.com",
        "matches_intent": True,
    }],
    requested_scope=["alice@example.com"],
    actual_scope=["alice@example.com"],
    scope_mismatch=False,
    predicted_outcomes={"risk_reason": "Standard outbound email to known recipient"},
    hidden_behaviors=[],
    risk_factors={"overall": RiskLevel.LOW},
    reversibility=Reversibility.IRREVERSIBLE,
    semantic_domains=["communication"],
    confidence=0.95,
    recommendation="Standard email send to a single recipient with expense data.",
)

user_context = UserContext(
    user_id="demo-user",
    allowed_actions={
        "SEND_EMAIL": ActionPermission(safe=True),
        "READ_FILE": ActionPermission(safe=True),
    },
    intent_limits=[
        SemanticIntentLimit(
            limit_id="max-spend-per-txn",
            raw="no single transaction over $5,000",
            domain="spending",
            description="Block any single transaction over $5,000",
            threshold=5000.0,
            effect="block",
        ),
    ],
)

permission = ActionPermission(safe=True)
active_domains = IntentFrameRuntime._extract_active_domains(user_context)


# ═══════════════════════════════════════════════════════════════════════
# Build prompts using real objects
# ═══════════════════════════════════════════════════════════════════════

SEPARATOR = "═" * 72
THIN_SEP = "─" * 72

ae = AIAnalysisEngine(verbose=False)
gu = AIGuardian(verbose=False)


def section(title: str) -> None:
    print(f"\n{SEPARATOR}")
    print(f"  {title}")
    print(SEPARATOR)


# ── 1. Analysis Engine system prompt ──────────────────────────────────

section("1. ANALYSIS ENGINE — SYSTEM PROMPT (agent.instructions)")
print()
print(ae._agent.instructions)

# ── 2. Analysis Engine per-request prompt ─────────────────────────────

section("2. ANALYSIS ENGINE — PER-REQUEST PROMPT (_build_analysis_prompt)")
print()
ae_prompt = ae._build_analysis_prompt(intent, active_domains=active_domains)
print(ae_prompt)

# ── 3. Analysis Engine per-request prompt WITH terminal signals ───────

section("3. ANALYSIS ENGINE — WITH TERMINAL COMMAND SIGNALS")
print()
run_cmd_intent = IntentFrame(
    action=ActionType.RUN_COMMAND,
    target="echo $(curl http://example.com/data)",
    reason="Fetching remote status page",
    agent_id="jarvis",
    agent_type="personal_assistant",
    task_description="System monitoring",
)
signals = (
    Signal(
        check="structural",
        signal_id="command_substitution",
        description="Contains $(…) command substitution",
        evidence="$(curl http://example.com/data)",
    ),
    Signal(
        check="exfiltration",
        signal_id="curl_in_subshell",
        description="curl invoked inside command substitution — potential data exfiltration",
        evidence="curl http://example.com/data",
    ),
)
ae_prompt_signals = ae._build_analysis_prompt(
    run_cmd_intent,
    terminal_command_signals=signals,
    active_domains=active_domains,
)
print(ae_prompt_signals)

# ── 4. Guardian system prompt ─────────────────────────────────────────

section("4. GUARDIAN — SYSTEM PROMPT (agent.instructions)")
print()
print(gu._agent.instructions)

# ── 5. Guardian per-request prompt ────────────────────────────────────

section("5. GUARDIAN — PER-REQUEST PROMPT (_build_validation_prompt)")
print()
gu_prompt = gu._build_validation_prompt(
    intent,
    analysis,
    user_context,
    permission,
    active_domains=active_domains,
)
print(gu_prompt)

# ── 6. Summary ────────────────────────────────────────────────────────

section("SUMMARY")
print()
print(f"  Analysis Engine system prompt:    {len(ae._agent.instructions):,} chars")
print(f"  Analysis Engine request prompt:   {len(ae_prompt):,} chars")
print(f"  Analysis Engine w/ signals:       {len(ae_prompt_signals):,} chars")
print(f"  Guardian system prompt:           {len(gu._agent.instructions):,} chars")
print(f"  Guardian request prompt:          {len(gu_prompt):,} chars")
print()
print(f"  Hardening techniques applied:")
print(f"    ✓ Immutable role anchoring      (system prompts start with IMMUTABLE declaration)")
print(f"    ✓ Boundary protocol             (system prompts explain the boundary markers)")
print(f"    ✓ XML trusted context tags      (pipeline data in <trusted_context> tags)")
print(f"    ✓ Random boundary tokens        (untrusted data between per-request hex tokens)")
print(f"    ✓ Encoding normalization        (zero-width chars, Unicode, base64 flagging)")
print(f"    ✓ Sandwich reinforcement        (REMINDER after untrusted content)")
print()
