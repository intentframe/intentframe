"""
Boundary token generation and section framing.

Provides two framing mechanisms:

1. **Trusted sections** use static XML-style ``<trusted_context>`` tags.
   These are pipeline-controlled content (action, agent metadata, analysis
   reports, policy) that the agent LLM does not control.

2. **Untrusted sections** use per-request random boundary tokens — 32-char
   hex strings that an attacker cannot predict or close.  Analogous to
   CSRF tokens in web security.

The system prompt explains the boundary protocol once at Agent init.
Each per-request prompt carries the actual token.
"""

from __future__ import annotations

import secrets


def generate_boundary() -> str:
    """Generate a cryptographically random 32-char hex boundary token."""
    return secrets.token_hex(16)


def frame_trusted(content: str, label: str = "pipeline") -> str:
    """Wrap pipeline-controlled content in static XML tags.

    Args:
        content: The trusted text to frame.
        label: Source attribution shown in the tag (default: "pipeline").
    """
    return (
        f'<trusted_context source="{label}">\n'
        f'{content}\n'
        f'</trusted_context>'
    )


def frame_untrusted(content: str, boundary: str) -> str:
    """Wrap agent-controlled content between random boundary markers.

    Args:
        content: The untrusted text to frame.
        boundary: The per-request boundary token from ``generate_boundary()``.
    """
    return (
        f'{boundary}_UNTRUSTED_START\n'
        f'{content}\n'
        f'{boundary}_UNTRUSTED_END'
    )
