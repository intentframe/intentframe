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
from intentframe_action_bundle.evidence import CommandIntel
from intentframe_action_bundle.files.file_intel import build_file_intel
from intentframe_action_bundle.prompt_trusted import build_ae_trusted_sections
from intentframe_action_bundle.prompts.registry import select_ae_prompt_id
from intentframe_bundle_sdk.types import AnalysisContext, BundleContext
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


def _analysis_context(intent: IntentFrame, **ctx_fields) -> AnalysisContext:
    bundle_ctx = BundleContext(intent=intent, **ctx_fields)
    return AnalysisContext(
        trusted_sections=build_ae_trusted_sections(intent, bundle_ctx),
        terminal_command_signals=bundle_ctx.terminal_command_signals,
        ae_prompt_id=select_ae_prompt_id(bundle_ctx),
    )


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
ae_prompt = ae._build_analysis_prompt(
    intent, _analysis_context(intent), active_domains=active_domains
)
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
run_cmd_intel = CommandIntel(
    verdict="NEEDS_REVIEW",
    capabilities=("capability:network_probe:http_get",),
)
run_cmd_analysis = AnalysisReport(
    stated_intent="Fetch remote status page via shell command",
    actual_behaviors=[{
        "action": "RUN_COMMAND",
        "actual_behavior": "Runs a shell command that fetches remote content via curl and echoes it",
        "matches_intent": True,
    }],
    requested_scope=["echo $(curl http://example.com/data)"],
    actual_scope=["echo $(curl http://example.com/data)"],
    scope_mismatch=False,
    predicted_outcomes={"risk_reason": "Shell execution with outbound network access"},
    hidden_behaviors=[],
    risk_factors={"overall": RiskLevel.HIGH},
    reversibility=Reversibility.IRREVERSIBLE,
    semantic_domains=["execution"],
    confidence=0.95,
    recommendation="Shell execution with outbound network retrieval.",
)
run_cmd_ae_ctx = _analysis_context(
    run_cmd_intent,
    command_intel=run_cmd_intel,
    terminal_command_signals=signals,
)
ae_run_cmd_prompt_id = run_cmd_ae_ctx.ae_prompt_id or "standard"
gu_run_cmd_prompt_id = gu._resolve_prompt_id(run_cmd_intent, run_cmd_analysis)
ae_prompt_signals = ae._build_analysis_prompt(
    run_cmd_intent,
    run_cmd_ae_ctx,
    active_domains=active_domains,
)
print(ae_prompt_signals)

# ── 3b. Analysis Engine RUN_COMMAND system prompt ─────────────────────

section(f"3b. ANALYSIS ENGINE — RUN_COMMAND SYSTEM PROMPT ({ae_run_cmd_prompt_id})")
print()
print(ae._agents[ae_run_cmd_prompt_id].instructions)

# ── 4. Guardian system prompt ─────────────────────────────────────────

section("4. GUARDIAN — SYSTEM PROMPT (agent.instructions)")
print()
print(gu._agent.instructions)

# ── 4b. Guardian RUN_COMMAND system prompt ────────────────────────────

section(f"4b. GUARDIAN — RUN_COMMAND SYSTEM PROMPT ({gu_run_cmd_prompt_id})")
print()
print(gu._agents[gu_run_cmd_prompt_id].instructions)

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

# ── 6. Analysis Engine per-request prompt WITH file_intel (WRITE_FILE) ─

section("6. ANALYSIS ENGINE — WRITE_FILE PER-REQUEST PROMPT (with file_intel)")
print()
write_file_intent = IntentFrame(
    action=ActionType.WRITE_FILE,
    target="/home/demo-user/scripts/sync_expenses.py",
    reason="Saving the weekly expense sync helper so it can be scheduled later",
    data={
        "path": "/home/demo-user/scripts/sync_expenses.py",
        "content": (
            "#!/usr/bin/env python3\n"
            "import subprocess\n"
            "import urllib.request\n\n"
            "def fetch_expenses():\n"
            "    req = urllib.request.urlopen('https://api.example.com/expenses')\n"
            "    return req.read().decode()\n\n"
            "if __name__ == '__main__':\n"
            "    data = fetch_expenses()\n"
            "    subprocess.run(['open', '-e', '/tmp/expenses.json'])\n"
        ),
    },
    agent_id="jarvis",
    agent_type="personal_assistant",
    task_description="Maintain the user's weekly expense sync script",
)
write_file_intel = build_file_intel(
    write_file_intent.data["content"],
    write_file_intent.target,
    write_file_intent.action.value,
)
write_file_analysis = AnalysisReport(
    stated_intent="Write a Python expense-sync helper to the user's scripts directory",
    actual_behaviors=[{
        "action": "WRITE_FILE",
        "actual_behavior": (
            "Writes a Python script that fetches a remote URL and invokes "
            "a subprocess to open the result"
        ),
        "matches_intent": True,
    }],
    requested_scope=["/home/demo-user/scripts/sync_expenses.py"],
    actual_scope=["/home/demo-user/scripts/sync_expenses.py"],
    scope_mismatch=False,
    predicted_outcomes={
        "risk_reason": (
            "Persists executable Python that performs outbound HTTP and "
            "spawns a local subprocess when run"
        ),
    },
    hidden_behaviors=[],
    risk_factors={"overall": RiskLevel.MEDIUM},
    reversibility=Reversibility.FULLY_REVERSIBLE,
    semantic_domains=["data_modification", "execution"],
    confidence=0.9,
    recommendation=(
        "Code-like payload written to a user-owned scripts directory. "
        "Not executed by this action, but contains outbound network + "
        "subprocess invocation once run."
    ),
)
write_ae_ctx = _analysis_context(write_file_intent, file_intel=write_file_intel)
ae_write_file_prompt_id = write_ae_ctx.ae_prompt_id or "standard"
gu_write_file_prompt_id = gu._resolve_prompt_id(
    write_file_intent, write_file_analysis
)
ae_prompt_write_file = ae._build_analysis_prompt(
    write_file_intent,
    write_ae_ctx,
    active_domains=active_domains,
)
print(ae_prompt_write_file)

# ── 6b. Analysis Engine WRITE_FILE system prompt ──────────────────────

section(f"6b. ANALYSIS ENGINE — WRITE_FILE SYSTEM PROMPT ({ae_write_file_prompt_id})")
print()
print(ae._agents[ae_write_file_prompt_id].instructions)

# ── 7. Guardian WRITE_FILE per-request prompt ─────────────────────────

section("7. GUARDIAN — WRITE_FILE PER-REQUEST PROMPT (_build_validation_prompt)")
print()
gu_prompt_write_file = gu._build_validation_prompt(
    write_file_intent,
    write_file_analysis,
    user_context,
    ActionPermission(safe=True),
    active_domains=active_domains,
)
print(gu_prompt_write_file)

# ── 7b. Guardian WRITE_FILE system prompt ─────────────────────────────

section(f"7b. GUARDIAN — WRITE_FILE SYSTEM PROMPT ({gu_write_file_prompt_id})")
print()
print(gu._agents[gu_write_file_prompt_id].instructions)

# ── 8. Summary ────────────────────────────────────────────────────────

section("SUMMARY")
print()
print(f"  Analysis Engine system prompt:    {len(ae._agent.instructions):,} chars")
print(f"  Analysis Engine request prompt:   {len(ae_prompt):,} chars")
print(f"  Analysis Engine w/ signals:       {len(ae_prompt_signals):,} chars")
print(f"  Analysis Engine w/ file_intel:    {len(ae_prompt_write_file):,} chars")
print(f"  Guardian system prompt:           {len(gu._agent.instructions):,} chars")
print(f"  Guardian request prompt:          {len(gu_prompt):,} chars")
print(f"  Guardian WRITE_FILE request:      {len(gu_prompt_write_file):,} chars")
print()
print(f"  Hardening techniques applied:")
print(f"    ✓ Immutable role anchoring      (system prompts start with IMMUTABLE declaration)")
print(f"    ✓ Boundary protocol             (system prompts explain the boundary markers)")
print(f"    ✓ XML trusted context tags      (pipeline data in <trusted_context> tags)")
print(f"    ✓ Random boundary tokens        (untrusted data between per-request hex tokens)")
print(f"    ✓ Encoding normalization        (zero-width chars, Unicode, base64 flagging)")
print(f"    ✓ Sandwich reinforcement        (REMINDER after untrusted content)")
print()
