#!/usr/bin/env python3
"""
Inspect hardened prompts — prints the EXACT prompts that AE and Guardian
would send to the LLM, using real objects (no mocks).

Run:  .venv/bin/python tests/inspect_hardened_prompts.py
"""

from __future__ import annotations

import asyncio

from action_registry.types import ActionType
from intentframe_native_bundles.actions.email.bundle import EmailActionBundle
from intentframe_native_bundles.actions.files.bundle import FilesActionBundle
from intentframe_native_bundles.actions.terminal.bundle import TerminalActionBundle
from intentframe_native_bundles.actions.terminal.evidence import CommandIntel
from intentframe_native_bundles.actions.files.evidence_keys import FILE_INTEL_KEY
from intentframe_native_bundles.actions.files.file_intel import build_file_intel
from intentframe_native_bundles.actions.terminal.evidence import (
    COMMAND_INTEL_KEY,
    TERMINAL_COMMAND_SIGNALS_KEY,
)
from intentframe_bundle_sdk.types import ActionPermission as SdkActionPermission
from intentframe_bundle_sdk.types import BundleAIContext, BundleContext, bundle_ai_context_or_empty
from intentframe_core.types import IntentFrame, AnalysisReport, UserContext
from intentframe_core.enums import RiskLevel, Reversibility
from policy_registry.models import ActionPermission, SemanticIntentLimit
from command_shield.verdict import Signal

from intentframe_components.analysis.engine import AIAnalysisEngine
from intentframe_components.guardian.engine import AIGuardian
from intentframe_server.pipeline import IntentFrameRuntime


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

SEPARATOR = "═" * 72

_NO_PERM = SdkActionPermission(safe=True, constraints=None)

ae = AIAnalysisEngine(verbose=False)
gu = AIGuardian(verbose=False)
email_bundle = EmailActionBundle()


def _bundle_ctx(intent: IntentFrame, **evidence) -> BundleContext:
    ctx = BundleContext(intent=intent)
    ctx.evidence.update(evidence)
    return ctx


def _ai_ctx(intent: IntentFrame, bundle, **evidence) -> BundleAIContext:
    ctx = _bundle_ctx(intent, **evidence)
    return asyncio.run(bundle.build_ai_context(ctx.effective_intent, _NO_PERM, ctx))


def _ae_system_instructions(ai_ctx: BundleAIContext) -> str:
    return ae._resolve_system_instructions(bundle_ai_context_or_empty(ai_ctx))


def _gu_system_instructions(ai_ctx: BundleAIContext) -> str:
    return gu._resolve_system_instructions(bundle_ai_context_or_empty(ai_ctx))


def section(title: str) -> None:
    print(f"\n{SEPARATOR}")
    print(f"  {title}")
    print(SEPARATOR)


send_email_ai_ctx = _ai_ctx(intent, email_bundle)

section("1. ANALYSIS ENGINE — SYSTEM PROMPT (agent.instructions)")
print()
print(ae._get_agent(_ae_system_instructions(send_email_ai_ctx)).instructions)

section("2. ANALYSIS ENGINE — PER-REQUEST PROMPT (_build_analysis_prompt)")
print()
ae_prompt = ae._build_analysis_prompt(intent, send_email_ai_ctx, active_domains=active_domains)
print(ae_prompt)

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
terminal_bundle = TerminalActionBundle()
files_bundle = FilesActionBundle()

run_cmd_ai_ctx = _ai_ctx(
    run_cmd_intent,
    terminal_bundle,
    **{
        COMMAND_INTEL_KEY: run_cmd_intel,
        TERMINAL_COMMAND_SIGNALS_KEY: signals,
    },
)
ae_run_cmd_label = run_cmd_ai_ctx.ae_prompt_label or "fallback_default"
gu_run_cmd_label = gu._resolve_prompt_label(run_cmd_ai_ctx)
ae_prompt_signals = ae._build_analysis_prompt(
    run_cmd_intent,
    run_cmd_ai_ctx,
    active_domains=active_domains,
)
print(ae_prompt_signals)

section(f"3b. ANALYSIS ENGINE — RUN_COMMAND SYSTEM PROMPT ({ae_run_cmd_label})")
print()
print(ae._get_agent(_ae_system_instructions(run_cmd_ai_ctx)).instructions)

section("4. GUARDIAN — SYSTEM PROMPT (agent.instructions)")
print()
print(gu._get_agent(_gu_system_instructions(send_email_ai_ctx)).instructions)

section(f"4b. GUARDIAN — RUN_COMMAND SYSTEM PROMPT ({gu_run_cmd_label})")
print()
print(gu._get_agent(_gu_system_instructions(run_cmd_ai_ctx)).instructions)

section("5. GUARDIAN — PER-REQUEST PROMPT (_build_validation_prompt)")
print()
from intentframe_bundle_sdk.types import ConstraintPromptContext

gu_prompt = gu._build_validation_prompt(
    intent,
    analysis,
    user_context,
    permission,
    active_domains=active_domains,
    bundle_ai_context=BundleAIContext(
        constraint_context=ConstraintPromptContext(
            action_constraints="No specific constraints",
        )
    ),
)
print(gu_prompt)

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
write_ai_ctx = _ai_ctx(write_file_intent, files_bundle, **{FILE_INTEL_KEY: write_file_intel})
ae_write_file_label = write_ai_ctx.ae_prompt_label or "fallback_default"
gu_write_file_label = gu._resolve_prompt_label(write_ai_ctx)
ae_prompt_write_file = ae._build_analysis_prompt(
    write_file_intent,
    write_ai_ctx,
    active_domains=active_domains,
)
print(ae_prompt_write_file)

section(f"6b. ANALYSIS ENGINE — WRITE_FILE SYSTEM PROMPT ({ae_write_file_label})")
print()
print(ae._get_agent(_ae_system_instructions(write_ai_ctx)).instructions)

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

section(f"7b. GUARDIAN — WRITE_FILE SYSTEM PROMPT ({gu_write_file_label})")
print()
print(gu._get_agent(_gu_system_instructions(write_ai_ctx)).instructions)

section("SUMMARY")
print()
print(f"  Analysis Engine system prompt:    {len(ae._get_agent(_ae_system_instructions(send_email_ai_ctx)).instructions):,} chars")
print(f"  Analysis Engine request prompt:   {len(ae_prompt):,} chars")
print(f"  Analysis Engine w/ signals:       {len(ae_prompt_signals):,} chars")
print(f"  Analysis Engine w/ file_intel:    {len(ae_prompt_write_file):,} chars")
print(f"  Guardian system prompt:           {len(gu._get_agent(_gu_system_instructions(send_email_ai_ctx)).instructions):,} chars")
print(f"  Guardian request prompt:          {len(gu_prompt):,} chars")
print(f"  Guardian WRITE_FILE request:      {len(gu_prompt_write_file):,} chars")
print()
