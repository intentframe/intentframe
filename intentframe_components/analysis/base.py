"""
Layer 3: Analysis Engine ("The Brain")

Semantic AI - SECRET, Cloud Only
"""

from abc import ABC, abstractmethod

from intentframe_core.types import (
    AnalysisReport,
    CommandIntel,
    ExecutionContext,
    FileIntel,
    IntentFrame,
)


class AnalysisEngine(ABC):
    """
    Layer 3: The Brain - SECRET, Cloud Only (FULLY TRUSTED)

    Proprietary AI core that provides deep semantic understanding
    of what actions will ACTUALLY do.

    Responsibilities:
    - Semantic understanding of actions
    - Code/script behavior analysis
    - Outcome prediction
    - Hidden behavior discovery
    - Intent vs action mismatch detection

    HAS: Deep AI understanding, behavior analysis, outcome models
    HAS NOT: Policy authority, credentials, ability to decide/act

    OUTPUT: Analysis Report (understanding, NOT decisions)

    This is the competitive moat - never open source, never documented.
    """

    @abstractmethod
    async def analyze(
        self,
        intent: IntentFrame,
        safe_actions: set[str] | None = None,
        terminal_command_signals: tuple = (),
        active_domains: set[str] | None = None,
        execution_context: ExecutionContext | None = None,
        command_intel: CommandIntel | None = None,
        file_intel: FileIntel | None = None,
    ) -> AnalysisReport:
        """
        Analyze what an intent will REALLY do.

        Returns an AnalysisReport with:
        - Actual behaviors (vs stated intent)
        - Predicted outcomes
        - Hidden behaviors discovered
        - Risk factors
        - Confidence score

        Does NOT make allow/block decisions - that's Guardian's job.

        Args:
            intent: The intent to analyse.
            safe_actions: Action types the user has marked ``safe``
                in their policy.  Used solely as a performance hint
                to skip AI analysis for passive system reads.
                Passed per-request by the pipeline from the resolved
                UserContext.
            terminal_command_signals: Structural findings from
                deterministic static analysis of RUN_COMMAND intents.
                Only relevant for RUN_COMMAND — injected into the AI
                prompt as additional context.  Does not affect fast-path
                decisions for other intent types.
            active_domains: Domain strings the user has active rules
                for, extracted deterministically from intent_limits
                and domain_constraints.  Injected into the AI prompt
                as trusted context so the AE knows which domains to
                check for.  Does not reveal policy details — only
                the domain vocabulary the system cares about.
            execution_context: Immutable server-side facts about the
                executor (privilege level, uid/euid).  Probed once at
                startup.  Allows risk assessment to account for
                whether commands will actually execute as root.
            command_intel: Bounded summary of command_shield facts
                (verdict, capability tags, code-intel findings).
                Populated only for RUN_COMMAND intents; ``None`` for
                every other action.  Additive context — Phase 1 wiring
                forwards it but existing implementations need not
                consume it yet.
            file_intel: Bounded summary of ``inspect_code`` facts for
                the WRITE_FILE payload (language, binary/oversized
                flags, code-intel findings).  Populated only for
                WRITE_FILE intents; ``None`` for every other action.
                Consumed by the prompt strategy to route WRITE_FILE to
                the ``critical_write_file`` AE lane when the payload is
                code-like and by the critical prompt body to ground
                reasoning in deterministic payload facts.
        """
        pass
