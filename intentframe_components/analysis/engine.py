"""
AI-Powered Analysis Engine

Uses OpenAI Agents to semantically understand what an intent will REALLY do.

This is the "brain" of the system - it provides UNDERSTANDING, not decisions.
Guardian uses this understanding to make policy decisions.

Fast-path optimisation:
    For actions that are pre-approved by user policy AND are inherently
    passive system reads (READ_FILE, LIST_DIRECTORY etc.), the engine returns
    a minimal deterministic AnalysisReport without calling AI.

    User-facing IO actions (ASK_USER, SHOW_MESSAGE, GET_CONFIRMATION) are
    NOT eligible for fast-path because their prompt content must be
    analysed for social engineering / phishing patterns.  Guardian relies
    on this analysis to protect the user.
"""

from enum import IntEnum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from agents import Agent, Runner

from action_registry.types import ActionType
from intentframe_core.types import IntentFrame, AnalysisReport
from intentframe_core.enums import Reversibility, RiskLevel
from intentframe_components.analysis.base import AnalysisEngine
from intentframe_components.prompt import format_intent_data
from intentframe_components.prompt.hardening import PromptHardening
from intentframe_components.prompt.roles import ANALYSIS_ENGINE_ROLE


# ============================================================
# AE Output Field Limits
# ============================================================
# OpenAI structured output enforces these via JSON Schema maxLength /
# maxItems.  The model writes complete text within the budget — no
# post-hoc truncation needed.  These limits are generous: legitimate
# AE output rarely exceeds half the cap.  They exist to structurally
# bound the surface available for a transitive injection payload.

class AEFieldLimit(IntEnum):
    STATED_INTENT = 400
    ACTUAL_BEHAVIOR = 600
    RISK_REASON = 400
    SCOPE_ANALYSIS = 400
    RECOMMENDATION = 600
    HIDDEN_BEHAVIOR_ITEM = 300
    HIDDEN_BEHAVIORS_MAX_ITEMS = 10
    SEMANTIC_DOMAIN_ITEM = 80
    SEMANTIC_DOMAINS_MAX_ITEMS = 15


# ============================================================
# Structured Output for AI Analysis
# ============================================================

_BoundedBehavior = Annotated[str, StringConstraints(max_length=AEFieldLimit.HIDDEN_BEHAVIOR_ITEM)]
_BoundedDomain = Annotated[str, StringConstraints(max_length=AEFieldLimit.SEMANTIC_DOMAIN_ITEM)]


class AIAnalysisOutput(BaseModel):
    """Structured output from the AI Analysis Agent"""

    stated_intent: str = Field(
        max_length=AEFieldLimit.STATED_INTENT,
        description="One sentence: what the agent claims to want to do",
    )
    actual_behavior: str = Field(
        max_length=AEFieldLimit.ACTUAL_BEHAVIOR,
        description="What this action will ACTUALLY do in the real world",
    )

    risk_level: str = Field(
        description="Risk level: LOW, MEDIUM, HIGH, or CRITICAL",
    )
    risk_reason: str = Field(
        max_length=AEFieldLimit.RISK_REASON,
        description="Brief explanation of why this risk level was assigned",
    )

    reversibility: str = Field(
        description="How reversible is this action: FULLY_REVERSIBLE, PARTIALLY_REVERSIBLE, TIME_LIMITED, IRREVERSIBLE, or UNKNOWN",
    )

    hidden_behaviors: list[_BoundedBehavior] = Field(
        default_factory=list,
        max_length=AEFieldLimit.HIDDEN_BEHAVIORS_MAX_ITEMS,
        description="Any hidden or non-obvious behaviors this action might cause",
    )

    scope_analysis: str = Field(
        max_length=AEFieldLimit.SCOPE_ANALYSIS,
        description="What resources/data will this action affect?",
    )
    scope_mismatch: bool = Field(
        default=False,
        description="Does the actual scope exceed what was stated/expected?",
    )

    semantic_domains: list[_BoundedDomain] = Field(
        default_factory=list,
        max_length=AEFieldLimit.SEMANTIC_DOMAINS_MAX_ITEMS,
        description="Human-level domains this action falls under: spending, communication, deletion, data_access, scheduling, etc. Empty list if none apply clearly.",
    )

    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence in this analysis (0.0 to 1.0)",
    )
    recommendation: str = Field(
        max_length=AEFieldLimit.RECOMMENDATION,
        description="One-sentence neutral summary of the analysis (no allow/block language)",
    )


# ============================================================
# AI Analysis Engine
# ============================================================

class AIAnalysisEngine(AnalysisEngine):
    """
    AI-powered Analysis Engine using OpenAI Agents.
    
    Provides deep semantic understanding of:
    - What actions will ACTUALLY do
    - Hidden or non-obvious behaviors
    - Risk factors
    - Reversibility
    
    Does NOT make allow/block decisions - that's Guardian's job.

    Supports two deterministic fast-paths that skip AI:

    1. Safe passive reads — actions the user marked safe that are
       inherently read-only. Returns a minimal LOW-risk report.

    2. Catastrophic commands — RUN_COMMAND with patterns the engine
       already understands (sudo, rm -rf /, mkfs, etc.). The engine
       knows what these do without AI. Returns a deterministic
       CRITICAL-risk IRREVERSIBLE report. Guardian will block these;
       the engine's job is just to provide understanding, fast.

    User-facing IO (ASK_USER, SHOW_MESSAGE, GET_CONFIRMATION) always
    goes through full AI analysis so that prompt content is inspected
    for phishing / social engineering.  Guardian depends on this.
    """

    # Patterns the Analysis Engine already understands — no AI needed.
    # These are the engine's own knowledge, not imported from Guardian
    # or Policy. Each component independently knows what's dangerous.
    _CATASTROPHIC_COMMAND_PATTERNS: dict[str, str] = {
        "sudo":       "Privilege escalation — runs command as superuser",
        "rm -rf /":   "Recursive forced deletion of root filesystem",
        "mkfs":       "Filesystem format — destroys all data on target device",
        "dd if=":     "Raw disk write — overwrites device blocks directly",
        "> /dev/":    "Direct write to device file — bypasses filesystem",
        "chmod 777":  "World-writable permissions — removes all access control",
    }

    _PASSIVE_READ_ACTIONS: set[str] = {
        # File
        ActionType.READ_FILE.value,
        ActionType.LIST_DIRECTORY.value,
        # Calendar
        ActionType.LIST_CALENDARS.value,
        ActionType.LIST_EVENTS.value,
        ActionType.SEARCH_EVENTS.value,
        # Reminders
        ActionType.LIST_REMINDERS.value,
        ActionType.LIST_REMINDER_LISTS.value,
        # Contacts
        ActionType.SEARCH_CONTACTS.value,
        ActionType.GET_CONTACT.value,
        # Notes
        ActionType.LIST_NOTES.value,
        ActionType.READ_NOTE.value,
        # Messages
        ActionType.READ_MESSAGES.value,
        # Email
        ActionType.READ_EMAIL.value,
        ActionType.SEARCH_EMAIL.value,
        ActionType.GET_EMAIL.value,
        ActionType.DOWNLOAD_ATTACHMENT.value,
        # Clipboard
        ActionType.GET_CLIPBOARD.value,
        # Search
        ActionType.SEARCH_SPOTLIGHT.value,
        # System (read-only)
        ActionType.GET_SYSTEM_INFO.value,
        ActionType.GET_BRIGHTNESS.value,
        ActionType.GET_VOLUME.value,
        ActionType.GET_MUTE.value,
        ActionType.GET_DARK_MODE.value,
    }

    _hardener = PromptHardening()

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        verbose: bool = True,
    ):
        self.model = model
        self.verbose = verbose

        self._agent = Agent(
            name="Analysis Engine",
            instructions=self._hardener.harden_system_prompt(
                base_instructions=self._base_instructions(),
                role_preamble=ANALYSIS_ENGINE_ROLE,
            ),
            model=self.model,
            output_type=AIAnalysisOutput,
        )
    
    @staticmethod
    def _base_instructions() -> str:
        return """You receive an IntentFrame and produce a factual analysis. No policy enforcement.

Your responsibilities:
1. Describe the actual behavior of the action (what changes, what is accessed)
2. Describe the scope of resources touched (requested vs actual)
3. Classify which semantic domains this action falls under (see rules below)
4. Identify hidden behaviors (see rules below)
5. Determine reversibility (can it be undone)
6. Provide confidence in your analysis

You do NOT decide allow/block. You do NOT apply user policies.
You provide understanding only.

Semantic domains — classify what this action MEANS at a human level:
- Tag the action with domains like: spending, communication, deletion, data_access,
  data_modification, scheduling, execution, etc.
- Base this on what the action ACTUALLY DOES, not its ActionType.
- Be comprehensive: if an action can be part of multiple domains, include all relevant domains.
- Examples (but not exhaustive):
  HTTP_POST to stripe.com/charges → ["spending"]
  HTTP_POST to slack.com/messages → ["communication"]
  APPEND_ROW with amount data to an expense tracker → ["spending", "data_modification"]
  DELETE_FILE → ["deletion"]
  READ_FILE → ["data_access"]
- Return an empty list only if the action genuinely doesn't fall under any domain.

Hidden behaviors — STRICT rules:
- A hidden behavior is something the action WILL DO that the agent DID NOT STATE.
  Example: agent says "send email" but the action also CC's an admin → hidden behavior.
  Example: agent says "delete file" but the action also wipes audit metadata → hidden behavior.
- Do NOT report speculative side effects. If appending to a file, do NOT imagine
  that "linked reports might update" or "other systems might react." You cannot see
  those systems. Report only what THIS action does on THIS target.
- Do NOT report normal, expected consequences of the stated action.
  Writing to a file creates/modifies the file — that is the stated intent, not hidden.
- If there are no hidden behaviors, return an EMPTY list. An empty list is the correct
  answer for most straightforward actions.

For risk_level and risk_reason:
- Assess based on the direct impact of THIS action (how much would change if executed)
- Do not speculate about downstream systems or theoretical cascading effects
- Do not make policy judgments or recommendations

For recommendation:
- Provide a neutral summary of the analysis (no allow/block language)

Be thorough but concise. Your output feeds the Guardian for policy decisions."""

    # ── Fast-path logic ─────────────────────────────────────────────

    def _try_fast_path(
        self,
        intent: IntentFrame,
        safe_actions: set[str],
    ) -> AnalysisReport | None:
        """Return a minimal deterministic report if the action qualifies.

        Qualifies when:
        1. Action is marked ``safe`` in user policy
        2. Action is a passive system read (no user-facing content)

        User-facing IO (ASK_USER, SHOW_MESSAGE, GET_CONFIRMATION) never
        qualifies because their prompt content must be inspected for
        social engineering / phishing.

        Returns None when full AI analysis is required.
        """
        action_value = intent.action.value

        if action_value not in safe_actions:
            return None

        if action_value not in self._PASSIVE_READ_ACTIONS:
            return None

        return AnalysisReport(
            stated_intent=f"{action_value} on {intent.target}",
            actual_behaviors=[{
                "action": action_value,
                "actual_behavior": f"Standard {action_value.lower().replace('_', ' ')} operation",
                "matches_intent": True,
            }],
            requested_scope=[intent.target],
            actual_scope=[intent.target],
            scope_mismatch=False,
            predicted_outcomes={"risk_reason": "Pre-approved passive read"},
            hidden_behaviors=[],
            risk_factors={"overall": RiskLevel.LOW},
            reversibility=Reversibility.FULLY_REVERSIBLE,
            confidence=1.0,
            recommendation=f"Deterministic analysis: {action_value} is a pre-approved passive read.",
        )

    # ── Catastrophic command recognition ─────────────────────────────

    def _try_catastrophic_report(self, intent: IntentFrame) -> AnalysisReport | None:
        """Return a deterministic CRITICAL report if the command is catastrophic.

        The Analysis Engine already knows what 'sudo rm -rf /' does —
        no LLM needed. This is the engine's own understanding, not
        imported from Guardian or the policy registry.

        Returns None when full AI analysis is required.
        """
        if intent.action.value != ActionType.RUN_COMMAND.value:
            return None

        command = intent.target or (intent.data or {}).get("command", "")
        if not command:
            return None

        for pattern, description in self._CATASTROPHIC_COMMAND_PATTERNS.items():
            if pattern in command:
                return AnalysisReport(
                    stated_intent=f"RUN_COMMAND: {command[:100]}",
                    actual_behaviors=[{
                        "action": "RUN_COMMAND",
                        "actual_behavior": description,
                        "matches_intent": True,
                    }],
                    requested_scope=[command],
                    actual_scope=["system-wide"],
                    scope_mismatch=False,
                    predicted_outcomes={
                        "risk_reason": f"Catastrophic operation: {description}",
                    },
                    hidden_behaviors=[],
                    risk_factors={"overall": RiskLevel.CRITICAL},
                    reversibility=Reversibility.IRREVERSIBLE,
                    confidence=1.0,
                    recommendation=f"Deterministic analysis: catastrophic command ({pattern}).",
                )

        return None

    # ── Main analysis entry point ────────────────────────────────────

    async def analyze(
        self,
        intent: IntentFrame,
        safe_actions: set[str] | None = None,
        terminal_command_signals: tuple = (),
    ) -> AnalysisReport:
        """
        Analyze what an intent will REALLY do.

        Tries deterministic paths first:
        1. Safe passive reads → minimal LOW-risk report (no AI)
        2. Catastrophic commands → CRITICAL-risk report (no AI)
        Falls back to full AI analysis for everything else.

        terminal_command_signals only applies to RUN_COMMAND intents.
        When present the signals are injected into the AI prompt for
        richer context.  Fast-path decisions are unaffected — they
        apply to their own intent types independently.
        """
        # ── Fast path: safe read-only ────────────────────────────────
        fast = self._try_fast_path(intent, safe_actions or set())
        if fast is not None:
            if self.verbose:
                print(f"    │  ⚡ Fast-path analysis: {intent.action.value} (safe, passive read)")
            return fast

        # ── Fast path: catastrophic command (already understood) ─────
        catastrophic = self._try_catastrophic_report(intent)
        if catastrophic is not None:
            if self.verbose:
                print(f"    │  ⚡ Deterministic analysis: {intent.action.value} (catastrophic command)")
            return catastrophic

        # ── AI path: full semantic analysis ──────────────────────────
        if terminal_command_signals and self.verbose:
            print(f"    │  Terminal command signals ({len(terminal_command_signals)}) — enriching AI prompt")

        prompt = self._build_analysis_prompt(
            intent, terminal_command_signals=terminal_command_signals,
        )
        
        if self.verbose:
            print(f"    │  AI analyzing: {intent.action.value}...")
        
        result = await Runner.run(self._agent, prompt)
        
        return self._convert_to_report(
            intent, result.final_output,
            terminal_command_signals=terminal_command_signals,
        )
    
    def _build_analysis_prompt(
        self,
        intent: IntentFrame,
        terminal_command_signals: tuple = (),
    ) -> str:
        """Build a hardened prompt for the AI agent.

        Trusted section: action (enum-validated), agent metadata,
        task description, terminal command signals (from command_shield).
        Untrusted section: target, reason, data — the fields the agent
        LLM actually controls.
        """
        # ── Trusted: pipeline-controlled context ──────────────────
        trusted_lines = [
            f"Action: {intent.action.value}",
            f"Agent: {intent.agent_type or intent.agent_id}",
            f"Task: {intent.task_description or 'Not specified'}",
        ]

        if terminal_command_signals:
            trusted_lines.append(
                "\nTERMINAL COMMAND — STRUCTURAL SIGNALS:\n"
                "Before this command reached you, deterministic static analysis "
                "(AST parsing, pattern matching, normalisation) detected the "
                "following structural concerns. Factor them into your risk "
                "assessment and hidden-behavior analysis:"
            )
            for sig in terminal_command_signals:
                line = f"  - [{sig.check}:{sig.signal_id}] {sig.description}"
                if sig.evidence:
                    line += f"  (evidence: {sig.evidence[:120]})"
                trusted_lines.append(line)

        # ── Untrusted: agent-controlled fields ────────────────────
        untrusted = {"Target": intent.target, "Reason": intent.reason}

        data_section = format_intent_data(intent.data)
        if data_section:
            untrusted["Data"] = data_section

        return self._hardener.build_hardened_prompt(
            trusted_sections={"Context": "\n".join(trusted_lines)},
            untrusted_fields=untrusted,
            closing_instruction="Analyze what this action will REALLY do.",
        )
    
    _FIELD_BOUNDS: dict[str, int] = {
        "stated_intent": AEFieldLimit.STATED_INTENT,
        "actual_behavior": AEFieldLimit.ACTUAL_BEHAVIOR,
        "risk_reason": AEFieldLimit.RISK_REASON,
        "scope_analysis": AEFieldLimit.SCOPE_ANALYSIS,
        "recommendation": AEFieldLimit.RECOMMENDATION,
    }
    _LIST_BOUNDS: dict[str, tuple[int, int]] = {
        "hidden_behaviors": (AEFieldLimit.HIDDEN_BEHAVIORS_MAX_ITEMS, AEFieldLimit.HIDDEN_BEHAVIOR_ITEM),
        "semantic_domains": (AEFieldLimit.SEMANTIC_DOMAINS_MAX_ITEMS, AEFieldLimit.SEMANTIC_DOMAIN_ITEM),
    }

    def _convert_to_report(
        self,
        intent: IntentFrame,
        ai_output: AIAnalysisOutput,
        terminal_command_signals: tuple = (),
    ) -> AnalysisReport:
        """Convert AI output to AnalysisReport format.

        Includes a deterministic backstop: if any field exceeds the
        schema-defined bound (which should never happen when OpenAI
        structured output is enforcing maxLength), the report is flagged
        with ae_output_anomaly so Guardian treats it as elevated risk.
        """
        anomaly = self._detect_overflow(ai_output)

        risk_level_map = {
            "LOW": RiskLevel.LOW,
            "MEDIUM": RiskLevel.MEDIUM,
            "HIGH": RiskLevel.HIGH,
            "CRITICAL": RiskLevel.CRITICAL,
        }
        risk_level = risk_level_map.get(ai_output.risk_level.upper(), RiskLevel.MEDIUM)

        reversibility_map = {
            "FULLY_REVERSIBLE": Reversibility.FULLY_REVERSIBLE,
            "PARTIALLY_REVERSIBLE": Reversibility.PARTIALLY_REVERSIBLE,
            "TIME_LIMITED": Reversibility.TIME_LIMITED,
            "IRREVERSIBLE": Reversibility.IRREVERSIBLE,
            "UNKNOWN": Reversibility.UNKNOWN,
        }
        reversibility = reversibility_map.get(
            ai_output.reversibility.upper(),
            Reversibility.UNKNOWN,
        )

        serialized_signals = [
            {
                "check": s.check,
                "signal_id": s.signal_id,
                "description": s.description,
                "evidence": s.evidence,
            }
            for s in terminal_command_signals
        ]

        return AnalysisReport(
            stated_intent=ai_output.stated_intent,
            actual_behaviors=[{
                "action": intent.action.value,
                "actual_behavior": ai_output.actual_behavior,
                "matches_intent": not ai_output.scope_mismatch,
            }],
            requested_scope=[intent.target],
            actual_scope=[ai_output.scope_analysis],
            scope_mismatch=ai_output.scope_mismatch,
            predicted_outcomes={
                "risk_reason": ai_output.risk_reason,
            },
            hidden_behaviors=ai_output.hidden_behaviors,
            risk_factors={"overall": risk_level},
            reversibility=reversibility,
            semantic_domains=ai_output.semantic_domains,
            confidence=ai_output.confidence,
            recommendation=ai_output.recommendation,
            terminal_command_signals=serialized_signals,
            ae_output_anomaly=anomaly,
        )

    def _detect_overflow(self, ai_output: AIAnalysisOutput) -> bool:
        """Return True if any AI output field exceeds its schema bound."""
        for field_name, limit in self._FIELD_BOUNDS.items():
            if len(getattr(ai_output, field_name, "")) > limit:
                return True
        for field_name, (max_items, per_item_limit) in self._LIST_BOUNDS.items():
            items = getattr(ai_output, field_name, [])
            if len(items) > max_items:
                return True
            if any(len(item) > per_item_limit for item in items):
                return True
        return False
