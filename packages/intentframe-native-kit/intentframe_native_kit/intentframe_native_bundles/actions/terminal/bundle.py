"""Terminal action bundle — RUN_COMMAND."""

from __future__ import annotations

import fnmatch

from intentframe_bundle_sdk import IntentFrame

from intentframe_native_kit.intentframe_native_bundles.actions.terminal import ACTION_IDS
from intentframe_native_kit.intentframe_native_bundles.actions.terminal._capability_match import (
    any_tag_matches,
    matches_any,
)
from intentframe_native_kit.intentframe_native_bundles.actions.terminal._read_only import is_read_only_fast_path
from intentframe_native_kit.intentframe_native_bundles.actions.terminal.ai_context import (
    build_terminal_intent_signals,
    render_terminal_external_context,
    select_terminal_ae_system_instructions,
)
from intentframe_native_kit.intentframe_native_bundles.actions.terminal.constraints import (
    SYSTEM_TERMINAL_BLOCKED_PATTERNS,
    TerminalConstraints,
)
from intentframe_native_kit.intentframe_native_bundles.actions.terminal.evidence import (
    COMMAND_INTEL_KEY,
    TERMINAL_COMMAND_SIGNALS_KEY,
    CommandIntel,
)
from intentframe_native_kit.intentframe_native_bundles.actions.terminal.onboarding_guardrails import (
    terminal_onboarding_guardrails,
)
from intentframe_native_kit.intentframe_native_bundles.actions.terminal.pre_pipeline import run_terminal_pre_pipeline
from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.types import (
    ActionPermission,
    BundleAIContext,
    BundleContext,
    BundlePhaseOutcome,
)


class TerminalActionBundle(ActionBundle):
    bundle_id = "terminal"
    action_ids = ACTION_IDS

    async def prepare_evidence(
        self,
        intent: IntentFrame,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        (
            command_intel,
            terminal_command_signals,
            early_block,
            audit_entry,
        ) = run_terminal_pre_pipeline(intent, verbose=verbose)

        if early_block is not None:
            del audit_entry
            block_data = early_block.data or {}
            reason = block_data.get("reason") or early_block.error or "catastrophic command detected"
            if str(reason).startswith("Blocked by command_shield: "):
                reason = str(reason)[len("Blocked by command_shield: ") :]
            return BundlePhaseOutcome.block(
                ctx,
                reason=str(reason),
                matched_gate="command_shield",
            )

        ctx.evidence[COMMAND_INTEL_KEY] = command_intel
        ctx.evidence[TERMINAL_COMMAND_SIGNALS_KEY] = terminal_command_signals
        return BundlePhaseOutcome.continue_(ctx)

    def validate_constraints(self, action_permission: ActionPermission) -> None:
        if action_permission.constraints is not None:
            TerminalConstraints.model_validate(action_permission.constraints)

    async def enforce_constraints(
        self,
        intent: IntentFrame,
        action_permission: ActionPermission,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        del verbose
        if action_permission.constraints is None:
            return BundlePhaseOutcome.continue_(ctx)
        constraints = TerminalConstraints.model_validate(action_permission.constraints)
        passed, reason = self._check_constraints(intent, constraints, ctx)
        if not passed:
            return BundlePhaseOutcome.block(
                ctx,
                reason=f"Constraint violation: {reason}",
                matched_gate="constraint",
            )
        return BundlePhaseOutcome.continue_(ctx)

    async def describe_constraints(self, action_permission: ActionPermission) -> str | None:
        if action_permission.constraints is None:
            return None
        constraints = TerminalConstraints.model_validate(action_permission.constraints)
        parts: list[str] = []
        if constraints.blocked_patterns:
            parts.append(f"Blocked patterns: {', '.join(constraints.blocked_patterns)}")
        if constraints.allowed_commands:
            parts.append(f"Allowed commands: {', '.join(constraints.allowed_commands)}")
        if constraints.deny_capabilities:
            parts.append(
                f"Deny capabilities: {', '.join(sorted(constraints.deny_capabilities))}"
            )
        if constraints.allow_capabilities:
            parts.append(
                f"Allow capabilities: {', '.join(sorted(constraints.allow_capabilities))}"
            )
        return "; ".join(parts) if parts else "No terminal constraints"

    def onboarding_guardrails(self) -> str:
        return terminal_onboarding_guardrails()

    async def allow_gates(
        self,
        intent: IntentFrame,
        action_permission: ActionPermission,
        ctx: BundleContext,
    ) -> BundlePhaseOutcome:
        if intent.action not in self.action_ids:
            return BundlePhaseOutcome.continue_(ctx)
        command_intel = ctx.evidence.get(COMMAND_INTEL_KEY)
        if command_intel is None:
            return BundlePhaseOutcome.continue_(ctx)

        deny_caps = self._deny_capabilities(action_permission)
        if is_read_only_fast_path(command_intel, deny_caps):
            return BundlePhaseOutcome.allow(
                ctx,
                reason="Permitted (deterministic: read-only command)",
                matched_gate="run_command_read_only",
            )
        return BundlePhaseOutcome.continue_(ctx)

    async def build_ai_context(
        self,
        intent: IntentFrame,
        action_permission: ActionPermission,
        ctx: BundleContext,
    ) -> BundleAIContext:
        del intent, action_permission
        command_intel = ctx.evidence.get(COMMAND_INTEL_KEY)
        if command_intel is not None and not isinstance(command_intel, CommandIntel):
            command_intel = None
        signals = ctx.evidence.get(TERMINAL_COMMAND_SIGNALS_KEY, ())
        if not isinstance(signals, tuple):
            signals = ()
        system, label = select_terminal_ae_system_instructions(command_intel)
        intent_signals, truncated = build_terminal_intent_signals(signals)
        return BundleAIContext(
            ae_system_instructions=system,
            ae_external_context=render_terminal_external_context(signals),
            ae_prompt_label=label,
            ae_log_hints=(
                f"Terminal command signals ({len(signals)}) — enriching AI prompt",
            ) if signals else (),
            ae_intent_signals=tuple(intent_signals),
            ae_signal_truncated=truncated,
        )

    @staticmethod
    def _deny_capabilities(action_permission: ActionPermission) -> frozenset[str]:
        if action_permission.constraints is None:
            return frozenset()
        constraints = TerminalConstraints.model_validate(action_permission.constraints)
        return constraints.deny_capabilities

    @staticmethod
    def _terminal_policy_needs_command(constraints: TerminalConstraints) -> bool:
        return bool(
            constraints.allowed_commands
            or constraints.blocked_patterns
            or constraints.deny_capabilities
            or constraints.allow_capabilities
        )

    @staticmethod
    def _check_constraints(
        intent: IntentFrame,
        constraints: TerminalConstraints,
        ctx: BundleContext,
    ) -> tuple[bool, str]:
        # ``data["command"]`` is the executed resource; ``intent.target`` is display.
        command = (intent.data or {}).get("command", "")
        if TerminalActionBundle._terminal_policy_needs_command(constraints):
            if not command or (
                isinstance(command, str) and not command.strip()
            ):
                return (
                    False,
                    "Command is required to evaluate terminal policy",
                )

        # System floor is always enforced, independent of user policy.
        effective_blocked = list(
            dict.fromkeys(list(SYSTEM_TERMINAL_BLOCKED_PATTERNS) + constraints.blocked_patterns)
        )
        for pattern in effective_blocked:
            if pattern in command:
                return False, f"Command blocked — matched pattern: {pattern}"

        command_intel = ctx.evidence.get(COMMAND_INTEL_KEY)
        if command_intel is not None and not isinstance(command_intel, CommandIntel):
            command_intel = None
        capabilities: tuple[str, ...] = (
            command_intel.capabilities if command_intel is not None else ()
        )

        if constraints.deny_capabilities and capabilities:
            hit = any_tag_matches(capabilities, constraints.deny_capabilities)
            if hit is not None:
                return False, f"Command blocked — capability '{hit}' denied by policy"

        if constraints.allowed_commands:
            matched_allowlist = any(
                fnmatch.fnmatch(command, pattern)
                for pattern in constraints.allowed_commands
            )
            if not matched_allowlist:
                return False, f"Command '{command}' not in allowed commands"

        if constraints.allow_capabilities and capabilities:
            for tag in capabilities:
                if not matches_any(tag, constraints.allow_capabilities):
                    return (
                        False,
                        f"Command blocked — capability '{tag}' not in allowed capabilities",
                    )

        return True, ""
