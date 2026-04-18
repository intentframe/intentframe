"""
Prompt construction and hardening for IntentFrame AI components.

Public API
──────────
``format_intent_data``    — format intent data dict for prompt inclusion
``normalize_text``        — encoding normalization for untrusted text
``PromptHardening``       — orchestrator that composes all hardening techniques
``PromptStrategy``        — protocol for AE/Guardian prompt-id routing
``DefaultPromptStrategy`` — deterministic capability-aware default strategy

Submodules
──────────
``data``            — intent data formatting (value-cap policy)
``normalization``   — Unicode / zero-width / base64 normalization
``boundaries``      — random boundary tokens and section framing
``roles``           — immutable role anchoring constants
``hardening``       — orchestrator class
``library``         — versioned prompt bodies (standard / critical lanes)
``strategy``        — prompt-id routing
"""

from intentframe_components.prompt.data import format_intent_data, MAX_VALUE_LENGTH
from intentframe_components.prompt.normalization import normalize_text
from intentframe_components.prompt.hardening import PromptHardening
from intentframe_components.prompt.strategy import (
    DefaultPromptStrategy,
    PromptStrategy,
)

__all__ = [
    "format_intent_data",
    "MAX_VALUE_LENGTH",
    "normalize_text",
    "PromptHardening",
    "PromptStrategy",
    "DefaultPromptStrategy",
]
