"""
IntentFrame Runtime - Stateless Security Gateway

The Runtime receives pre-built IntentFrames (from Actor SDK over HTTP)
and runs them through the security pipeline:

    command_shield → context enrichment → AnalysisEngine → Guardian → Executor → Result

For RUN_COMMAND intents, command_shield.inspect_command() runs first:
- CATASTROPHIC: reject immediately, never enters the pipeline.
- NEEDS_REVIEW: structural signals are passed to the Analysis Engine
  so the AI has richer context.  Never fast-paths.
- SAFE: normal pipeline flow.

Runtime knows nothing about Actor.  Actor is an external SDK that agent
developers use.  Runtime just receives signed IntentFrames.

Guardian makes SECURITY decisions only:
- ALLOW: Action is authorized → Execute
- BLOCK: Policy violation → Reject

Guardian does NOT make business logic decisions.
If Agent wants to ask user about business logic (duplicates, etc.),
Agent sends ASK_USER intent, which Guardian validates as safe.
If an action is blocked, the agent (the domain expert) decides
what to do next — ask the user, retry differently, or skip.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from action_registry.types import ActionType
from command_shield import Verdict, inspect_command as shield_inspect
from intentframe_server.enrichers.email import enrich_intent as enrich_email_intent
from intentframe_core.enums import Decision, RiskLevel
from intentframe_core.types import (
    UserContext,
    ExecutionContext,
    ExecutionResult,
    IntentFrame,
    AgentCapabilities,
    RuntimeContext,
)
from intentframe_components.analysis import AnalysisEngine
from intentframe_components.guardian import Guardian
from intentframe_components.executor import Executor
from intentframe_components.onboarding import OnboardingEngine
from policy_registry.client import PolicyRegistryClient
from resource_registry.client import ResourceRegistryClient

logger = logging.getLogger(__name__)

_executor_logger: logging.Logger | None = None


def _get_executor_logger() -> logging.Logger:
    """Lazily initialise a file-only logger for executor action results."""
    global _executor_logger
    if _executor_logger is not None:
        return _executor_logger

    log_dir = Path(
        os.environ.get(
            "INTENTFRAME_LOG_DIR",
            os.path.expanduser("~/.intentframe/logs"),
        )
    )
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "executor_actions.log"

    fl = logging.getLogger("intentframe.executor_results")
    fl.setLevel(logging.DEBUG)
    fl.propagate = False

    if not fl.handlers:
        handler = logging.FileHandler(str(log_path), encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        fl.addHandler(handler)

    _executor_logger = fl
    return _executor_logger


class IntentFrameRuntime:
    """
    Stateless security gateway.

    Two main operations:

    1. HANDSHAKE (once per agent session):
        Agent capabilities + UserContext → OnboardingEngine → RuntimeContext

    2. INTENT PROCESSING (per action):
        IntentFrame → AnalysisEngine → Guardian → Executor → Result

    Runtime does NOT parse raw requests.  That is Actor's job (external SDK).
    Runtime only receives clean, signed IntentFrames.
    """

    def __init__(
        self,
        analysis_engine: AnalysisEngine,
        guardian: Guardian,
        executor: Executor,
        execution_context: Optional[ExecutionContext] = None,
        onboarding_engine: Optional[OnboardingEngine] = None,
        policy_client: Optional[PolicyRegistryClient] = None,
        resource_client: Optional[ResourceRegistryClient] = None,
        verbose: bool = True,
    ):
        self.analysis_engine = analysis_engine
        self.guardian = guardian
        self.executor = executor
        self._execution_context = execution_context or ExecutionContext()
        self.onboarding_engine = onboarding_engine
        self._policy_client = policy_client or PolicyRegistryClient()
        self._resource_client = resource_client or ResourceRegistryClient()
        self.verbose = verbose
        self.audit_log: list = []
        self._request_counter = 0
        self._lock = asyncio.Lock()

    @staticmethod
    def _log_executor_result(intent: IntentFrame, result: ExecutionResult) -> None:
        """Write every executor result (success or failure) to a dedicated log file."""
        data_summary: str | None = None
        if result.data:
            try:
                raw = json.dumps(result.data, default=str)
                data_summary = raw[:500] + "…" if len(raw) > 500 else raw
            except Exception:
                data_summary = str(result.data)[:500]

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": intent.action.value,
            "success": result.success,
            "target": intent.target or "",
            "command": (intent.data or {}).get("command", "")[:500],
            "error": result.error,
            "data": data_summary,
            "stderr": (result.data or {}).get("stderr", "")[:1000] if result.data else None,
            "return_code": (result.data or {}).get("return_code") if result.data else None,
        }
        level = logging.INFO if result.success else logging.WARNING
        try:
            _get_executor_logger().log(level, json.dumps(entry, default=str))
        except Exception:
            logger.debug("Could not write to executor action log", exc_info=True)

    def _resolve_user_context(self, user_context: UserContext) -> UserContext:
        """Look up the user's real policies from the policy registry.

        The agent only sends user_id — the server is the authority
        on allowed actions and their constraints.
        """
        try:
            policy = self._policy_client.get_user_policy(user_context.user_id)
            return UserContext(
                user_id=policy.user_id,
                allowed_actions=policy.allowed_actions,
                intent_limits=policy.intent_limits,
                domain_constraints=policy.domain_constraints,
                metadata=policy.metadata,
            )
        except KeyError:
            logger.warning(
                "No policy found for user '%s' — using defaults",
                user_context.user_id,
            )
            return user_context

    @staticmethod
    def _extract_safe_actions(user_context: UserContext) -> set[str]:
        """Extract the set of action types marked ``safe`` in user policy."""
        return {
            action
            for action, perm in user_context.allowed_actions.items()
            if perm.safe
        }

    @staticmethod
    def _extract_active_domains(user_context: UserContext) -> set[str]:
        """Extract domain strings the user has active rules for.

        Sources:
        - intent_limits[].domain  (e.g. "spending", "deletion")
        - domain_constraints keys (e.g. "finance", "deletion")

        These are passed to the Analysis Engine as trusted context so it
        knows which semantic domains the system cares about, without
        revealing any policy details (thresholds, effects, etc.).
        """
        domains: set[str] = set()
        if user_context.intent_limits:
            for limit in user_context.intent_limits:
                if limit.domain:
                    domains.add(limit.domain)
        if user_context.domain_constraints:
            domains.update(user_context.domain_constraints.keys())
        return domains

    def _resolve_workspace(self, workspace_id: str) -> tuple[list[str], dict[str, str]]:
        """Fetch the ClientView from the Resource Registry.

        Returns (virtual_paths, path_permissions) or empty defaults
        if the workspace doesn't exist yet.
        """
        try:
            view = self._resource_client.client_view(workspace_id)
            return view.virtual_paths, view.permissions
        except (KeyError, Exception) as exc:
            logger.debug("No workspace '%s' in resource registry: %s", workspace_id, exc)
            return [], {}

    async def handshake(
        self, 
        capabilities: AgentCapabilities, 
        user_context: UserContext
    ) -> RuntimeContext:
        """
        Perform handshake between agent and IntentFrame runtime.
        
        This is called ONCE when an agent connects, before any requests.
        
        Flow:
        1. Agent (via Actor SDK) provides capabilities and user_id
        2. Runtime looks up the user's real policies from the policy registry
        3. AI Onboarding Engine generates RuntimeContext with:
           - User's limits and policies (server-authoritative)
           - AI-generated guardrails specific to this agent
           - Warnings about agent capabilities
        4. Context is returned to Actor, which passes it to the agent
        
        Args:
            capabilities: What the agent does (from agent developer)
            user_context: Minimal context from agent (only user_id is trusted)
            
        Returns:
            RuntimeContext with everything agent needs to work effectively
        """
        user_context = self._resolve_user_context(user_context)
        virtual_paths, path_permissions = self._resolve_workspace(user_context.user_id)

        if not self.onboarding_engine:
            if self.verbose:
                print(f"\n    [HANDSHAKE] No Onboarding Engine - using basic context")

            context = RuntimeContext(
                user_id=user_context.user_id,
                allowed_actions=user_context.allowed_actions,
                metadata=user_context.metadata,
                guardrails=[],
                available_actions=capabilities.action_types,
                onboarded_agent_type=capabilities.agent_type,
                virtual_paths=virtual_paths,
                path_permissions=path_permissions,
            )
        else:
            num_actions = len(user_context.allowed_actions)
            if self.verbose:
                print(f"\n    ╔══════════════════════════════════════════════════════════╗")
                print(f"    ║  HANDSHAKE: Agent → IntentFrame Runtime                   ║")
                print(f"    ╠══════════════════════════════════════════════════════════╣")
                print(f"    ║  Agent: {capabilities.agent_type:<50} ║")
                print(f"    ║  User: {user_context.user_id:<51} ║")
                print(f"    ║  Allowed Actions: {num_actions:<40} ║")
                print(f"    ╚══════════════════════════════════════════════════════════╝")
            
            context = await self.onboarding_engine.onboard(
                capabilities, user_context,
                execution_context=self._execution_context,
            )
            context.virtual_paths = virtual_paths
            context.path_permissions = path_permissions

            if self.verbose:
                print(f"\n    ╔══════════════════════════════════════════════════════════╗")
                print(f"    ║  HANDSHAKE COMPLETE                                       ║")
                print(f"    ╠══════════════════════════════════════════════════════════╣")
                print(f"    ║  Allowed Actions: {len(context.allowed_actions):<40} ║")
                print(f"    ║  Guardrails: {len(context.guardrails):<45} ║")
                if context.warnings:
                    print(f"    ║  Warnings: {len(context.warnings):<47} ║")
                print(f"    ║  Confidence: {context.onboarding_confidence:.0%}                                         ║")
                print(f"    ╚══════════════════════════════════════════════════════════╝")
                
                # Show guardrails
                if context.guardrails:
                    print(f"\n    AI-Generated Guardrails:")
                    for i, guardrail in enumerate(context.guardrails, 1):
                        # Wrap guardrail text
                        words = guardrail.split()
                        lines = []
                        current_line = f"    {i}. "
                        for word in words:
                            if len(current_line) + len(word) + 1 <= 70:
                                current_line = current_line + " " + word if not current_line.endswith(". ") else current_line + word
                            else:
                                lines.append(current_line)
                                current_line = "       " + word
                        if current_line.strip():
                            lines.append(current_line)
                        for line in lines:
                            print(line)
                
                if context.warnings:
                    print(f"\n    ⚠️  Warnings:")
                    for warning in context.warnings:
                        print(f"       - {warning}")
        
        return context
    
    def clear_audit_log(self):
        """Clear audit log for new session"""
        self.audit_log = []
        self._request_counter = 0
    
    def get_audit_log(self) -> list:
        """Return audit log of all decisions"""
        return self.audit_log
    
    async def process_intent(
        self,
        intent: IntentFrame,
        user_context: UserContext,
    ) -> ExecutionResult:
        """
        Process a pre-built IntentFrame through the security pipeline.

        Actor (external SDK) has already parsed the raw request into an
        IntentFrame and sent it here over HTTP.  Runtime only does:
        Analysis → Guardian → Executor.
        """
        user_context = self._resolve_user_context(user_context)
        async with self._lock:
            return await self._process_intent_impl(intent, user_context)

    async def _process_intent_impl(
        self,
        intent: IntentFrame,
        user_context: UserContext,
    ) -> ExecutionResult:
        """Internal implementation of intent processing."""
        self._request_counter += 1
        req_num = self._request_counter

        if self.verbose:
            reason = intent.reason or ""

            print(f"\n    ╔══════════════════════════════════════════════════════════╗")
            print(f"    ║  INTENT #{req_num:<51} ║")
            print(f"    ╠══════════════════════════════════════════════════════════╣")
            print(f"    ║  Agent: {intent.agent_id:<50} ║")
            print(f"    ║  Action: {intent.action.value:<49} ║")
            print(f"    ║  Target: {str(intent.target)[:49]:<49} ║")
            if reason:
                print(f"    ╟──────────────────────────────────────────────────────────╢")
                print(f"    ║  Agent Reason:                                            ║")
                words = reason.split()
                lines: list[str] = []
                current_line = ""
                for word in words:
                    if len(current_line) + len(word) + 1 <= 52:
                        current_line = current_line + " " + word if current_line else word
                    else:
                        if current_line:
                            lines.append(current_line)
                        current_line = word
                if current_line:
                    lines.append(current_line)
                for line in lines:
                    print(f"    ║    {line:<54} ║")
            print(f"    ╚══════════════════════════════════════════════════════════╝")
        
        # ═══════════════════════════════════════════════════════════════
        # LAYER 2: COMMAND SHIELD - Deterministic structural pre-check
        # ═══════════════════════════════════════════════════════════════
        terminal_command_signals: tuple = ()
        if intent.action.value == ActionType.RUN_COMMAND.value:
            command = intent.target or (intent.data or {}).get("command", "")
            if command:
                report = shield_inspect(command)

                if self.verbose:
                    print(f"    ┌──────────────────────────────────────────────────────────┐")
                    print(f"    │  COMMAND SHIELD: Deterministic structural analysis        │")
                    print(f"    │  Verdict: {report.verdict.value:<47} │")
                    if report.signals:
                        print(f"    │  Signals: {len(report.signals):<48} │")
                    print(f"    └──────────────────────────────────────────────────────────┘")

                if report.verdict == Verdict.CATASTROPHIC:
                    reason = "; ".join(
                        s.description for s in report.signals[:3]
                    ) or "catastrophic command detected"

                    if self.verbose:
                        print(f"")
                        print(f"    ╔══════════════════════════════════════════════════════════╗")
                        print(f"    ║  COMMAND SHIELD: CATASTROPHIC — REJECTED                 ║")
                        print(f"    ╠══════════════════════════════════════════════════════════╣")
                        print(f"    ║  {reason[:56]:<56} ║")
                        print(f"    ╚══════════════════════════════════════════════════════════╝")
                        print(f"")

                    audit_entry = {
                        "action": intent.action.value,
                        "target": intent.target,
                        "data": intent.data,
                        "reason": intent.reason,
                        "decision": "BLOCK",
                        "message": f"command_shield: {reason}",
                        "decision_path": "command_shield",
                        "executed": False,
                    }
                    self.audit_log.append(audit_entry)

                    return ExecutionResult(
                        success=False,
                        error=f"Blocked by command_shield: {reason}",
                        data={
                            "decision": "BLOCK",
                            "reason": reason,
                            "layer": "command_shield",
                        },
                    )

                if report.verdict == Verdict.NEEDS_REVIEW:
                    terminal_command_signals = report.signals

        # ═══════════════════════════════════════════════════════════════
        # CONTEXT ENRICHMENT — deterministic metadata from system sources
        # ═══════════════════════════════════════════════════════════════
        intent = await enrich_email_intent(intent)

        # ═══════════════════════════════════════════════════════════════
        # LAYER 3: ANALYSIS ENGINE - Understand the intent
        # ═══════════════════════════════════════════════════════════════
        if self.verbose:
            print(f"    ┌──────────────────────────────────────────────────────────┐")
            print(f"    │  ANALYSIS ENGINE: Understanding intent                   │")
        
        safe_actions = self._extract_safe_actions(user_context)
        active_domains = self._extract_active_domains(user_context)
        analysis = await self.analysis_engine.analyze(
            intent,
            safe_actions=safe_actions,
            terminal_command_signals=terminal_command_signals,
            active_domains=active_domains,
            execution_context=self._execution_context,
        )
        
        if self.verbose:
            print(f"    │  AI analyzing: {intent.action.value}...")
            print(f"    │  Confidence: {analysis.confidence:.0%}                                        │")
            print(f"    │  Reversibility: {analysis.reversibility.value if analysis.reversibility else 'N/A':<41} │")
            if analysis.hidden_behaviors:
                print(f"    │  ⚠️  Hidden behaviors: {str(analysis.hidden_behaviors)[:33]:<33} │")
            if analysis.semantic_domains:
                domains_str = ", ".join(analysis.semantic_domains)
                print(f"    │  Domains: {domains_str:<48} │")
            if analysis.risk_factors:
                overall = max(analysis.risk_factors.values(), key=lambda r: list(RiskLevel).index(r))
                factors_str = ", ".join(f"{k}: {v.value}" for k, v in analysis.risk_factors.items())
                print(f"    │  Risk factors: {factors_str[:44]:<44} │")
            if analysis.scope_mismatch:
                print(f"    │  ⚠️  Scope mismatch detected                              │")
            print(f"    └──────────────────────────────────────────────────────────┘")
        
        # ═══════════════════════════════════════════════════════════════
        # LAYER 4: GUARDIAN - Validate SECURITY (not business logic!)
        # ═══════════════════════════════════════════════════════════════
        if self.verbose:
            print(f"    ┌──────────────────────────────────────────────────────────┐")
            print(f"    │  GUARDIAN: Security validation                           │")
            print(f"    │  (Checks authority, NOT business logic)                  │")
        
        validation = await self.guardian.validate(
            intent, analysis, user_context,
            active_domains=active_domains,
            execution_context=self._execution_context,
        )
        
        # ═══════════════════════════════════════════════════════════════
        # DECISION: ALLOW / BLOCK
        # ═══════════════════════════════════════════════════════════════
        
        is_fast_path = "fast-path" in (validation.message or "").lower()

        # Build audit entry
        audit_entry = {
            "action": intent.action.value,
            "target": intent.target,
            "data": intent.data,
            "reason": intent.reason,
            "decision": validation.decision.value,
            "message": validation.message,
            "decision_path": "fast_path" if is_fast_path else "ai_path",
            "risk_level": str(analysis.risk_factors) if analysis.risk_factors else None,
            "confidence": analysis.confidence,
        }
        
        if validation.decision == Decision.ALLOW:
            # ───────────────────────────────────────────────────────────
            # ALLOW - Execute the action
            # ───────────────────────────────────────────────────────────
            if self.verbose:
                print(f"    │                                                          │")
                print(f"    │  ✅ DECISION: ALLOW                                       │")
                print(f"    │  {validation.message:<56} │")
                print(f"    └──────────────────────────────────────────────────────────┘")
            
            # Layer 5: Executor
            if self.verbose:
                print(f"    ┌──────────────────────────────────────────────────────────┐")
                print(f"    │  EXECUTOR: Performing action                             │")
            
            intent_to_execute = validation.modified_intent or intent
            result = self.executor.execute(intent_to_execute)
            
            if self.verbose:
                status = 'Success' if result.success else 'Failed'
                print(f"    │  Result: {status:<49} │")
                action_name = intent.action.value
                if action_name in ("ASK_USER", "GET_CONFIRMATION", "SHOW_OPTIONS"):
                    prompt = (intent.data or {}).get("prompt", "")
                    if prompt:
                        prompt_short = prompt[:52] + "…" if len(prompt) > 52 else prompt
                        print(f"    │  Prompt: {prompt_short:<49} │")
                    if result.success and result.data:
                        resp = result.data.get("response") or result.data.get("selection") or ""
                        if resp:
                            resp_short = resp[:52] + "…" if len(resp) > 52 else resp
                            print(f"    │  User:   {resp_short:<49} │")
                elif action_name == "SHOW_MESSAGE":
                    msg = (intent.data or {}).get("message", "")
                    if msg:
                        msg_short = msg[:52] + "…" if len(msg) > 52 else msg
                        print(f"    │  Shown:  {msg_short:<49} │")
                if not result.success and result.error:
                    hint = result.error.replace("\n", " ")
                    hint = hint[:49] + "…" if len(hint) > 49 else hint
                    print(f"    │  Reason: {hint:<49} │")
                elif result.success and result.data:
                    try:
                        raw = json.dumps(result.data, default=str)
                    except Exception:
                        raw = str(result.data)
                    info = raw.replace("\n", " ")
                    info = info[:49] + "…" if len(info) > 49 else info
                    print(f"    │  Result Info:   {info:<49} │")
                print(f"    └──────────────────────────────────────────────────────────┘")

            self._log_executor_result(intent, result)
            
            # Log the outcome
            audit_entry["executed"] = result.success
            action_name = intent.action.value
            if result.success and result.data and action_name in (
                "ASK_USER", "SHOW_MESSAGE", "GET_CONFIRMATION", "SHOW_OPTIONS",
            ):
                audit_entry["user_prompt"] = (intent.data or {}).get("prompt", "")
                audit_entry["user_response"] = result.data
            self.audit_log.append(audit_entry)
            
            return result

        else:  # BLOCK
            # ───────────────────────────────────────────────────────────
            # BLOCK - Policy violation, action rejected
            # ───────────────────────────────────────────────────────────
            if self.verbose:
                print(f"    │                                                          │")
                print(f"    │  ⛔ DECISION: BLOCK                                       │")
                print(f"    │  {validation.message:<56} │")
                print(f"    └──────────────────────────────────────────────────────────┘")
                
                # Show block notification
                print(f"")
                print(f"    ╔══════════════════════════════════════════════════════════╗")
                print(f"    ║  ⛔ ACTION BLOCKED (Security)                             ║")
                print(f"    ╠══════════════════════════════════════════════════════════╣")
                print(f"    ║  {validation.message:<56} ║")
                print(f"    ║                                                          ║")
                print(f"    ║  Guardian blocked this action because it violates        ║")
                print(f"    ║  user policy. The agent decides what to do next.         ║")
                print(f"    ╚══════════════════════════════════════════════════════════╝")
                print(f"")
            
            # Log the block
            audit_entry["executed"] = False
            self.audit_log.append(audit_entry)
            
            return ExecutionResult(
                success=False,
                error=f"Blocked: {validation.message}",
                data={"decision": "BLOCK", "reason": validation.message}
            )
