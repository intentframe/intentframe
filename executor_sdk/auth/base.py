"""
Abstract base class for authorization verification.

An AuthVerifier checks whether the AuthorizationProof attached to an
ExecutionRequest is valid. It answers one question: "Is this proof
legitimate according to my scheme?"

It does NOT answer:
    - "Who sent this?" (caller identity is irrelevant to the executor)
    - "Should this action be allowed?" (that's the caller's problem)
    - "Is this a good idea?" (executor acts, it doesn't judge)

The gateway calls verify() for every inbound request. If the result
is AuthResult(valid=False), the request is rejected immediately
(fail-closed) and a SecurityEvent is logged.

Implementations:
    Each auth scheme provides one concrete verifier.
    Only ONE verifier is active per executor instance.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from executor.models import AuthorizationProof, AuthResult


class AuthVerifier(ABC):
    """Abstract base for all authorization verifier implementations.

    Contract:
        - verify() MUST return AuthResult, never raise.
        - On any internal error, return AuthResult(valid=False, error=...).
        - verify() MUST be safe to call concurrently from multiple tasks.
        - verify() MUST NOT perform I/O that could block the event loop
          for longer than auth_timeout (use async I/O if needed).
    """

    @abstractmethod
    async def verify(self, proof: AuthorizationProof) -> AuthResult:
        """Verify an authorization proof.

        Args:
            proof: The AuthorizationProof extracted from the ExecutionRequest.

        Returns:
            AuthResult with valid=True if the proof is legitimate,
            valid=False with error description otherwise.
        """
        ...

    @abstractmethod
    def scheme(self) -> str:
        """Return the auth scheme this verifier handles (e.g., 'guardian_hmac').

        Used for logging and diagnostics. Must match the scheme field
        in AuthorizationProof for requests routed to this verifier.
        """
        ...
