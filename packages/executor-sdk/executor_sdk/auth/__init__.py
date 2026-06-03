"""
Authorization verification layer -- how the executor validates auth proof.

Every execution request carries an AuthorizationProof. The auth verifier
checks whether that proof is valid. It does NOT know or care who the
caller is -- only whether the proof satisfies the configured scheme.

Platform-specific implementations register themselves via
register_auth_verifier() and are instantiated at startup from config.

Implementations to create later:
    - guardian_hmac.py  (IntentFrame default -- HMAC signature from Guardian)
    - mtls.py           (cloud -- mutual TLS certificate verification)
    - token.py          (admin/CI -- JWT or opaque bearer token)
"""

from __future__ import annotations

from typing import Any

from executor_sdk.auth.base import AuthVerifier
from executor_sdk.exceptions import ConfigurationError

__all__ = ["AuthVerifier", "register_auth_verifier", "create_auth_verifier"]

# ─── Plugin Registry ─────────────────────────────────────────────────────────

_AUTH_REGISTRY: dict[str, type[AuthVerifier]] = {}


def register_auth_verifier(
    auth_type: str, verifier_class: type[AuthVerifier]
) -> None:
    """Register an auth verifier implementation for config-driven instantiation.

    Platform-specific auth modules call this at import time:
        register_auth_verifier("guardian_hmac", GuardianHMACVerifier)
    """
    _AUTH_REGISTRY[auth_type] = verifier_class


def create_auth_verifier(config: Any) -> AuthVerifier:
    """Instantiate the configured auth verifier from the registry.

    Args:
        config: Auth section of executor.yaml.

    Returns:
        Configured AuthVerifier instance ready to verify().

    Raises:
        ConfigurationError: If the auth type is not registered.
    """
    verifier_class = _AUTH_REGISTRY.get(config.type)
    if verifier_class is None:
        registered = ", ".join(sorted(_AUTH_REGISTRY)) or "(none)"
        raise ConfigurationError(
            f"Unknown auth type: '{config.type}'. "
            f"Registered verifiers: {registered}",
        )
    return verifier_class(**config.options)
