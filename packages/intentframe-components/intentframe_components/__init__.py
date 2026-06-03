"""
IntentFrame Components — pipeline building blocks.

Each sub-package exposes a base class (interface) and an AI-powered
implementation.  The server assembles them into a pipeline.
"""

from intentframe_components.analysis import AnalysisEngine, AIAnalysisEngine
from intentframe_components.guardian import Guardian, AIGuardian
from intentframe_components.executor import Executor
from intentframe_components.onboarding import OnboardingEngine, AIOnboardingEngine
