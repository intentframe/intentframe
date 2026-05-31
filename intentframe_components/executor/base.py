"""
Layer 5: Executor ("The Hands")

Action Performer - TRUSTED, User's Device
"""

from abc import ABC, abstractmethod

from intentframe_core.types import IntentFrame, ExecutionResult


class Executor(ABC):
    """
    Layer 5: The Hands - Local on User's Device (TRUSTED)
    
    The ONLY entity with API keys, credentials, and permissions.
    Performs standard actions after cloud Guardian approval.
    
    Responsibilities:
    - Execute validated intents
    - Hold credentials securely
    - Intelligent error handling, retry, rollback
    - Immutable logging of all actions
    
    HAS: Credentials, execution capability
    HAS NOT: Judgment capability - does NOT question wisdom
    
    Only executes what Guardian has validated.
    """
    
    @abstractmethod
    def execute(self, validated_intent: IntentFrame) -> ExecutionResult:
        """
        Execute the validated intent and return results.
        
        - Performs the actual I/O operation
        - Logs everything immutably
        - Returns the completed result for audit trail
        
        Does NOT make decisions about SHOULD this happen.
        This method must not return a coroutine, future, or job handle;
        callers rely on the returned ExecutionResult being final.
        """
        pass
