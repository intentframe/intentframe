"""Credential scrubber and sensitive-key constants.

Extracted from ``executor/services/credential_scrubber.py`` and
``executor/constants.py`` so every IntentFrame module can scrub
data consistently without depending on the executor package.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

__all__ = [
    "SENSITIVE_KEYS",
    "REDACTED_VALUE",
    "HASH_ALGORITHM",
    "CredentialScrubber",
]

# ── Constants ────────────────────────────────────────────────────────────────

SENSITIVE_KEYS: frozenset[str] = frozenset({
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "api_secret",
    "credential",
    "credentials",
    "private_key",
    "access_key",
    "secret_key",
    "auth",
    "authorization",
    "bearer",
    "ssn",
    "credit_card",
    "card_number",
    "refresh_token",
    "app_password",
})

REDACTED_VALUE: str = "[REDACTED]"

HASH_ALGORITHM: str = "sha256"


# ── Scrubber ─────────────────────────────────────────────────────────────────


class CredentialScrubber:
    """Scrubs sensitive values from dicts and produces param hashes.

    Thread-safe and stateless — safe to share across a gateway or service.

    Usage::

        scrubber = CredentialScrubber()
        clean = scrubber.scrub({"api_key": "secret123", "name": "test"})
        # -> {"api_key": "[REDACTED]", "name": "test"}

        digest = scrubber.hash_params({"to": "user@example.com"})
        # -> "a3f2b8c1..."
    """

    def __init__(
        self,
        sensitive_keys: frozenset[str] | None = None,
        redacted_value: str = REDACTED_VALUE,
    ) -> None:
        self._sensitive_keys = sensitive_keys or SENSITIVE_KEYS
        self._redacted_value = redacted_value

    def scrub(self, data: dict[str, Any]) -> dict[str, Any]:
        """Return a deep copy with sensitive values replaced."""
        return self._walk(copy.deepcopy(data))

    def hash_params(self, params: dict[str, Any]) -> str:
        """Deterministic SHA-256 hex digest for audit correlation."""
        canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
        return hashlib.new(HASH_ALGORITHM, canonical.encode()).hexdigest()

    # -- internals --

    def _walk(self, data: Any) -> Any:
        if isinstance(data, dict):
            for key in data:
                if key.lower() in self._sensitive_keys:
                    data[key] = self._redacted_value
                else:
                    data[key] = self._walk(data[key])
        elif isinstance(data, list):
            for i, item in enumerate(data):
                data[i] = self._walk(item)
        return data
