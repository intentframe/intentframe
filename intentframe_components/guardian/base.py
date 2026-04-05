"""
Layer 4: Guardian ("The Judge")

Policy Enforcer - HYBRID (Local + Cloud)
"""

from abc import ABC, abstractmethod

from intentframe_core.types import IntentFrame, AnalysisReport, ValidationResult, UserContext


class Guardian(ABC):
    """
    Layer 4: The Judge - HYBRID (Local + Cloud)
    
    Multi-layer system that receives Analysis Report from Analysis Engine
    and applies user policies to make ALLOW / BLOCK decisions.
    
    Local Layer (device):
    - UX, caching, format validation, queue management
    - CANNOT approve alone - always connects to cloud
    
    Cloud Layer (platform):
    - Real policy enforcement based on Analysis Report
    - Makes final ALLOW / BLOCK decisions
    - Hidden security components
    
    HAS: Policy authority, Analysis Report, judgment capability
    HAS NOT: Credentials, execution capability, ability to act
    
    Guardian does NOT do business logic. If an action is blocked,
    the agent (the domain expert) decides what to do next.
    
    Serves the USER's interests.
    """
    
    @abstractmethod
    async def validate(
        self, 
        intent: IntentFrame, 
        analysis: AnalysisReport,
        user_context: UserContext,
    ) -> ValidationResult:
        """
        Validate intent against user policies using Analysis Report.
        
        - Receives understanding from Analysis Engine
        - Applies user's policies and limits
        - Makes ALLOW / BLOCK decision
        
        ALLOW – Execute as-is (or with modified_intent).
        BLOCK – Policy violation, action rejected.
        
        Does NOT execute anything - that's Executor's job.
        Does NOT construct alternatives - that's the agent's job.
        """
        pass
