"""
IntentFrame Runtime - Stateless Security Gateway

The Runtime receives pre-built IntentFrames (from Actor SDK over HTTP)
and runs them through the security pipeline:

    DeterministicGuardian (bundles) → AnalysisEngine → Guardian → Executor → Result

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
import inspect
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from intentframe_core.enums import Decision, RiskLevel
from intentframe_core.types import (
    UserContext,
    AnalysisReport,
    ExecutionContext,
    ExecutionResult,
    IntentFrame,
    AgentCapabilities,
    RuntimeContext,
    ValidationResult,
)
from intentframe_components.analysis import AnalysisEngine
from intentframe_components.guardian import (
    DeterministicDecision,
    DeterministicGuardian,
    Guardian,
)
from intentframe_components.executor import Executor
from intentframe_components.onboarding import OnboardingEngine
from intentframe_server.runtime_context_for_llms import (
    SubstrateContext,
    analysis_runtime_context_for_llm,
    guardian_runtime_context_for_llm,
    onboarding_runtime_context_for_llm,
)
from policy_registry.client import PolicyRegistryClient

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
        deterministic_guardian: Optional[DeterministicGuardian] = None,
        verbose: bool = True,
    ):
        self.analysis_engine = analysis_engine
        self.guardian = guardian
        self.executor = executor
        self._execution_context = execution_context or ExecutionContext()
        self._substrate_contexts = (
            SubstrateContext(execution=self._execution_context),
        )
        self.onboarding_engine = onboarding_engine
        self._policy_client = policy_client or PolicyRegistryClient()
        self.deterministic_guardian = deterministic_guardian or DeterministicGuardian(
            verbose=verbose,
        )
        self.verbose = verbose
        self.audit_log: list = []
        self._request_counter = 0
        self._lock = asyncio.Lock()

    async def startup(self) -> None:
        """Warm bundle-owned resources after registration."""
        from intentframe_bundle_sdk.lifecycle import startup_bundles

        await startup_bundles()

    async def aclose(self) -> None:
        """Release runtime-owned and bundle-owned resources."""
        from intentframe_bundle_sdk.lifecycle import shutdown_bundles

        try:
            await shutdown_bundles()
        finally:
            await self._close_executor()

    @staticmethod
    async def _close_executor_resource(executor: Executor) -> None:
        """Call ``aclose`` or ``close`` on an executor; await if async."""
        for name in ("aclose", "close"):
            method = getattr(executor, name, None)
            if method is None:
                continue
            result = method()
            if inspect.isawaitable(result):
                await result
            return

    async def _close_executor(self) -> None:
        await self._close_executor_resource(self.executor)

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
            "error": result.error,
            "data": data_summary,
        }
        level = logging.INFO if result.success else logging.WARNING
        try:
            _get_executor_logger().log(level, json.dumps(entry, default=str))
        except Exception:
            logger.debug("Could not write to executor action log", exc_info=True)

    def _resolve_user_context(self, user_context: UserContext) -> UserContext:
        """Look up the (user, agent) policy from the policy registry.

        The agent only sends ``user_id`` and ``agent_id`` — the server
        is the authority on allowed actions and their constraints.
        Lookup is keyed on the ``(user_id, agent_id)`` pair so two
        agents owned by the same user have isolated policies.
        """
        try:
            policy = self._policy_client.get_user_policy(
                user_context.user_id, user_context.agent_id
            )
            return UserContext(
                user_id=policy.user_id,
                agent_id=policy.agent_id,
                allowed_actions=policy.allowed_actions,
                intent_limits=policy.intent_limits,
                domain_constraints=policy.domain_constraints,
                metadata=policy.metadata,
            )
        except KeyError:
            logger.warning(
                "No policy found for user=%r agent=%r — using defaults",
                user_context.user_id,
                user_context.agent_id,
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
    def _enrichment_audit_fields(det_result) -> dict:
        """Bundle context audit: enrichment ledger + constraint-checker skip."""
        from intentframe_bundle_sdk.types import enrichment_audit_fields

        return enrichment_audit_fields(
            det_result.bundle_context if det_result is not None else None
        )

    @staticmethod
    def _bundle_sdk_audit_fields(det_result) -> dict:
        """Full Bundle SDK forensic snapshot for audit logs."""
        from intentframe_bundle_sdk.audit_dump import (
            dump_bundle_ai_context,
            dump_bundle_context,
        )

        fields: dict[str, object] = {}
        bundle_context = dump_bundle_context(
            det_result.bundle_context if det_result is not None else None
        )
        bundle_ai_context = dump_bundle_ai_context(
            det_result.bundle_ai_context if det_result is not None else None
        )
        if bundle_context is not None:
            fields["bundle_context"] = bundle_context
        if bundle_ai_context is not None:
            fields["bundle_ai_context"] = bundle_ai_context
        return fields

    @staticmethod
    def _add_prompt_audit_fields(audit_entry: dict, prefix: str, artifact) -> None:
        """Attach prompt source/label and full prompt content when an AI call ran."""
        evidence = getattr(artifact, "prompt_evidence", None)
        if evidence is None:
            return

        prompt_label = evidence.prompt_label
        prompt_source = evidence.prompt_source
        system_prompt = evidence.system_prompt
        request_prompt = evidence.request_prompt

        if not any((prompt_label, prompt_source, system_prompt, request_prompt)):
            return

        audit_entry[f"{prefix}_prompt_source"] = prompt_source
        audit_entry[f"{prefix}_prompt_label"] = prompt_label
        audit_entry[f"{prefix}_system_prompt"] = system_prompt
        audit_entry[f"{prefix}_request_prompt"] = request_prompt

    @staticmethod
    def _add_output_audit_fields(audit_entry: dict, prefix: str, artifact) -> None:
        """Attach raw LLM output and converted pipeline artifact when set."""
        evidence = getattr(artifact, "prompt_evidence", None)
        if evidence is None:
            return

        llm_output = evidence.llm_output
        converted_output = evidence.converted_output

        if llm_output is not None:
            audit_entry[f"{prefix}_llm_output"] = llm_output
        if converted_output is not None:
            audit_entry[f"{prefix}_converted_output"] = converted_output

    @staticmethod
    def _build_deterministic_report(
        intent: IntentFrame,
        det_result,
    ) -> AnalysisReport:
        """Build the minimal AnalysisReport we attach when DG ALLOWs.

        The pipeline's downstream audit + verbose printing assume
        ``analysis`` is a populated :class:`AnalysisReport`.  This
        builds one with just enough shape: LOW risk, FULLY_REVERSIBLE,
        and a recommendation that names the matched gate so audit
        consumers can tell a passive-read ALLOW from a read-only
        RUN_COMMAND ALLOW.
        """
        from intentframe_core.enums import Reversibility, RiskLevel

        return AnalysisReport(
            stated_intent=f"{intent.action.value} on {intent.target}",
            actual_behaviors=[{
                "action": intent.action.value,
                "actual_behavior": det_result.reason,
                "matches_intent": True,
            }],
            requested_scope=[intent.target],
            actual_scope=[intent.target],
            scope_mismatch=False,
            predicted_outcomes={"risk_reason": "Deterministic pre-AE ALLOW"},
            hidden_behaviors=[],
            risk_factors={"overall": RiskLevel.LOW},
            reversibility=Reversibility.FULLY_REVERSIBLE,
            confidence=1.0,
            recommendation=(
                f"Deterministic Guardian ALLOW "
                f"(gate={det_result.matched_gate})"
            ),
        )

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

        if not self.onboarding_engine:
            if self.verbose:
                print(f"\n    [HANDSHAKE] No Onboarding Engine - using basic context")

            context = RuntimeContext(
                user_id=user_context.user_id,
                agent_id=user_context.agent_id,
                allowed_actions=user_context.allowed_actions,
                metadata=user_context.metadata,
                guardrails=[],
                available_actions=capabilities.action_types,
                onboarded_agent_type=capabilities.agent_type,
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
                capabilities,
                user_context,
                runtime_context_for_llm=onboarding_runtime_context_for_llm(
                    self._substrate_contexts
                ),
            )

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

        Intent planes inside this call:
          submitted_intent — frozen at entry; sole input to ``executor.execute()``.
          effective_intent — after bundle enrichment; fed to AE, Guardian, audit.
        Pipeline internals must not rewrite adapter params (see executor call below).
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
        # Agent-developer contract: executor params == actor payload.
        # Enrichment (``ctx.enriched_intent``), evidence, and AI context may
        # rewrite ``intent`` below for governance; they must not reach adapters.
        submitted_intent = intent.model_copy(deep=True)
        self._request_counter += 1
        req_num = self._request_counter

        if self.verbose:
            reason = intent.reason or ""

            subject = intent.display_subject or intent.target
            started_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            intent_header = f"INTENT #{req_num}  ·  {started_at}"

            print(f"\n    ╔══════════════════════════════════════════════════════════╗")
            print(f"    ║  {intent_header:<58} ║")
            print(f"    ╠══════════════════════════════════════════════════════════╣")
            print(f"    ║  Agent: {intent.agent_id:<50} ║")
            print(f"    ║  Action: {intent.action.value:<49} ║")
            print(f"    ║  Target: {subject[:49]:<49} ║")
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
        # LAYER 4a: DETERMINISTIC GUARDIAN (Bundle SDK lifecycle)
        # ═══════════════════════════════════════════════════════════════
        # Permission → action bundle (prepare / policy / gates) → domain
        # bundle → BLOCK / ALLOW / UNDECIDED.  UNDECIDED falls through
        # to AE + AIGuardian.
        safe_actions = self._extract_safe_actions(user_context)
        active_domains = self._extract_active_domains(user_context)

        det_result = await self.deterministic_guardian.decide_async(
            intent,
            user_context,
            verbose=self.verbose,
        )
        # Governance plane — enriched target/data for AE, Guardian, audit only.
        intent = (
            det_result.bundle_context.effective_intent
            if det_result.bundle_context is not None
            else intent
        )
        bundle_ai_context = det_result.bundle_ai_context
        if self.verbose:
            print(f"    ┌──────────────────────────────────────────────────────────┐")
            print(f"    │  DETERMINISTIC GUARDIAN: pre-AE pass                     │")
            print(f"    │  Decision: {det_result.decision.value:<46} │")
            if det_result.matched_gate:
                print(f"    │  Gate:     {det_result.matched_gate:<46} │")
            print(f"    └──────────────────────────────────────────────────────────┘")

        if det_result.decision is DeterministicDecision.BLOCK:
            decision_path = det_result.decision_path or "deterministic"
            audit_entry = {
                "action": intent.action.value,
                "target": intent.target,
                "data": intent.data,
                "reason": intent.reason,
                "decision": "BLOCK",
                "message": det_result.reason,
                "decision_path": decision_path,
                "matched_gate": det_result.matched_gate,
                "executed": False,
                **self._enrichment_audit_fields(det_result),
                **self._bundle_sdk_audit_fields(det_result),
            }
            if det_result.dg_exception:
                audit_entry["dg_exception"] = det_result.dg_exception
            self.audit_log.append(audit_entry)
            if self.verbose:
                print(f"")
                print(f"    ╔══════════════════════════════════════════════════════════╗")
                print(f"    ║  ⛔ ACTION BLOCKED (Deterministic)                        ║")
                print(f"    ╠══════════════════════════════════════════════════════════╣")
                print(f"    ║  {det_result.reason[:56]:<56} ║")
                print(f"    ╚══════════════════════════════════════════════════════════╝")
                print(f"")
            return ExecutionResult(
                success=False,
                error=f"Blocked: {det_result.reason}",
                data={
                    "decision": "BLOCK",
                    "reason": det_result.reason,
                    "layer": decision_path,
                    "matched_gate": det_result.matched_gate,
                },
            )

        # Captured here so the shared audit entry below can reference
        # it without keeping a reference to det_result at call sites.
        dg_matched_gate: str | None = None

        if det_result.decision is DeterministicDecision.ALLOW:
            # ───── Deterministic ALLOW — skip AE + AIGuardian ─────
            # Build a minimal AnalysisReport mirroring the shape AE's
            # own fast-path produces.  Audit + log formatting below
            # assume `analysis` is a real report, so we give them one.
            analysis = self._build_deterministic_report(intent, det_result)
            validation = ValidationResult(
                decision=Decision.ALLOW,
                intent=intent,
                analysis=analysis,
                message=det_result.reason,
                decision_path="deterministic",
            )
            dg_matched_gate = det_result.matched_gate
            if self.verbose:
                print(f"    │  ⚡ Deterministic ALLOW — AE + AIGuardian skipped        │")
        else:
            # ═══════════════════════════════════════════════════════════════
            # LAYER 4b: ANALYSIS ENGINE (UNDECIDED path only)
            # ═══════════════════════════════════════════════════════════════
            if self.verbose:
                print(f"    ┌──────────────────────────────────────────────────────────┐")
                print(f"    │  ANALYSIS ENGINE: Understanding intent                   │")

            analysis = await self.analysis_engine.analyze(
                intent,
                active_domains=active_domains,
                runtime_context_for_llm=analysis_runtime_context_for_llm(
                    self._substrate_contexts
                ),
                bundle_context=det_result.bundle_context,
                bundle_ai_context=bundle_ai_context,
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
            # LAYER 4c: AI GUARDIAN - Validate SECURITY (not business logic!)
            # ═══════════════════════════════════════════════════════════════
            if self.verbose:
                print(f"    ┌──────────────────────────────────────────────────────────┐")
                print(f"    │  GUARDIAN: Security validation                           │")
                print(f"    │  (Checks authority, NOT business logic)                  │")

            validation = await self.guardian.validate(
                intent,
                analysis,
                user_context,
                active_domains=active_domains,
                runtime_context_for_llm=guardian_runtime_context_for_llm(
                    self._substrate_contexts
                ),
                bundle_context=det_result.bundle_context,
                bundle_ai_context=bundle_ai_context,
            )
        
        # ═══════════════════════════════════════════════════════════════
        # DECISION: ALLOW / BLOCK
        # ═══════════════════════════════════════════════════════════════
        
        # decision_path is authoritative; fall back to message substring
        # only if a Guardian implementation predates the field (defensive
        # — all first-party Guardians set it explicitly).
        decision_path = getattr(validation, "decision_path", None)
        if not decision_path:
            decision_path = (
                "fast_path"
                if "fast-path" in (validation.message or "").lower()
                else "ai_path"
            )
        is_fast_path = decision_path == "fast_path"

        # Build audit entry
        audit_entry = {
            "action": intent.action.value,
            "target": intent.target,
            "data": intent.data,
            "reason": intent.reason,
            "decision": validation.decision.value,
            "message": validation.message,
            "decision_path": decision_path,
            "risk_level": str(analysis.risk_factors) if analysis.risk_factors else None,
            "confidence": analysis.confidence,
            **self._enrichment_audit_fields(det_result),
            **self._bundle_sdk_audit_fields(det_result),
        }
        if dg_matched_gate:
            audit_entry["matched_gate"] = dg_matched_gate

        # Prompt forensic audit — record what source/label was used plus
        # the exact system and request prompts sent to the model.  Fields
        # are absent when a component did not make an AI call.
        self._add_prompt_audit_fields(audit_entry, "ae", analysis)
        self._add_output_audit_fields(audit_entry, "ae", analysis)
        self._add_prompt_audit_fields(audit_entry, "guardian", validation)
        self._add_output_audit_fields(audit_entry, "guardian", validation)
        
        if validation.decision == Decision.ALLOW:
            # ───────────────────────────────────────────────────────────
            # ALLOW - Execute the action
            # ───────────────────────────────────────────────────────────
            if self.verbose:
                print(f"    │                                                          │")
                print(f"    │  ✅ DECISION: ALLOW                                       │")
                print(f"    │  {validation.message:<56} │")
                print(f"    └──────────────────────────────────────────────────────────┘")
            
            # Layer 5: Executor — always ``submitted_intent``, never ``intent``
            # (effective/enriched) and never ``validation.modified_intent``.
            # Adapters consume exactly what the actor submitted; policy context
            # belongs in evidence / external_context, not hidden param mutation.
            if self.verbose:
                print(f"    ┌──────────────────────────────────────────────────────────┐")
                print(f"    │  EXECUTOR: Performing action                             │")
            
            result = self.executor.execute(submitted_intent)
            if inspect.isawaitable(result):
                raise TypeError(
                    "Executor.execute() returned an awaitable; the runtime "
                    "requires a completed ExecutionResult inside the lock."
                )
            
            if self.verbose:
                status = 'Success' if result.success else 'Failed'
                print(f"    │  Result: {status:<49} │")
                # Adapter-owned lines; substrate only truncates and boxes.
                if result.display_summary:
                    for _line in result.display_summary.splitlines():
                        _line = _line[:52] + "…" if len(_line) > 52 else _line
                        print(f"    │  {_line:<56} │")
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

            self._log_executor_result(submitted_intent, result)

            # audit_entry reflects enriched intent for observability; executor used submitted_intent.
            audit_entry["executed"] = result.success
            audit_entry["result_data"] = result.data
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
