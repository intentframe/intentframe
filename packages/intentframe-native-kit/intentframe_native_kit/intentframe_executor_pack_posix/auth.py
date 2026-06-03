"""
Guardian HMAC authorization verifier.

Verifies that execution requests carry a valid HMAC-SHA256 signature
from an authorized caller (typically IntentFrame's Cloud Guardian).

Token format:
    "{payload}:{hex_signature}"

Where:
    - payload: The signed content (typically request_id or intent_frame_id)
    - hex_signature: HMAC-SHA256(payload, shared_secret) as hex string

The shared secret is stored in the credential vault and is NEVER logged,
serialized, or transmitted.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_module
import logging

from executor_sdk.auth.base import AuthVerifier
from executor_sdk.models import AuthorizationProof, AuthResult

logger = logging.getLogger(__name__)


class GuardianHMACVerifier(AuthVerifier):
    """HMAC-SHA256 authorization verifier for IntentFrame Guardian.

    The shared secret can be provided directly (for testing) or
    referenced by a vault key (production). In production, the
    secret is fetched from the credential vault at startup.
    """

    def __init__(
        self,
        secret_key: str = "",
        secret_key_ref: str = "",
        **_kwargs,
    ) -> None:
        """Initialize with a direct key or vault reference.

        Args:
            secret_key: Direct HMAC secret (for testing/dev only).
            secret_key_ref: Vault key reference (e.g., "guardian/hmac-key").
                            Production deployments should use this.
        """
        self._secret_key = secret_key.encode() if secret_key else None
        self._secret_key_ref = secret_key_ref

    async def verify(self, proof: AuthorizationProof) -> AuthResult:
        """Verify a Guardian HMAC signature.

        Returns AuthResult(valid=True) if signature matches,
        AuthResult(valid=False, error=...) otherwise.
        """
        try:
            # Scheme check
            if proof.scheme != self.scheme():
                return AuthResult(
                    valid=False,
                    error=f"Unexpected auth scheme: '{proof.scheme}' (expected '{self.scheme()}')",
                )

            # Get the secret key
            key = self._get_key()
            if key is None:
                return AuthResult(
                    valid=False,
                    error="HMAC secret key not configured",
                )

            # Parse token: "payload:signature"
            separator_idx = proof.token.rfind(":")
            if separator_idx == -1:
                return AuthResult(
                    valid=False,
                    error="Invalid token format (expected 'payload:signature')",
                )

            payload = proof.token[:separator_idx]
            signature = proof.token[separator_idx + 1 :]

            # Compute expected HMAC
            expected = hmac_module.new(
                key, payload.encode("utf-8"), hashlib.sha256
            ).hexdigest()

            # Constant-time comparison to prevent timing attacks
            if not hmac_module.compare_digest(expected, signature):
                logger.warning("HMAC signature mismatch for payload: %s...", payload[:20])
                return AuthResult(
                    valid=False,
                    error="HMAC signature mismatch",
                )

            return AuthResult(valid=True, caller_id=payload)

        except Exception as exc:
            logger.error("HMAC verification error: %s", exc, exc_info=True)
            return AuthResult(valid=False, error=f"Verification error: {exc}")

    def scheme(self) -> str:
        return "guardian_hmac"

    def set_secret_key(self, key: str | bytes) -> None:
        """Set the secret key directly (for testing or vault-loaded keys)."""
        self._secret_key = key.encode() if isinstance(key, str) else key

    def _get_key(self) -> bytes | None:
        """Get the HMAC secret key."""
        return self._secret_key
