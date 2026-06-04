"""
Hash chain for audit trail integrity.

Maintains a SHA-256 hash chain where each audit entry's hash includes
the hash of the previous entry. This provides tamper evidence: modifying
any historical entry breaks the chain from that point forward.

This is a concrete, platform-agnostic service. It performs pure
computation with no I/O or platform dependencies.

Chain structure:
    entry_0: hash(entry_data_0 + GENESIS_HASH) = H0
    entry_1: hash(entry_data_1 + H0) = H1
    entry_2: hash(entry_data_2 + H1) = H2
    ...

Tampering with entry_1 would change H1, which would invalidate
H2 and every subsequent entry.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from executor_sdk.constants import GENESIS_HASH, HASH_ALGORITHM

__all__ = ["HashChain"]


class HashChain:
    """Maintains and verifies a SHA-256 hash chain.

    The chain tracks the hash of the most recent entry. Each new entry's
    hash is computed from its data concatenated with the previous hash.

    Usage:
        chain = HashChain()

        # Compute hash for a new entry
        entry_hash, prev_hash = chain.append({"action": "SEND_EMAIL", ...})
        # Store entry_hash and prev_hash in the audit entry

        # Verify chain integrity
        is_valid = HashChain.verify_chain(entries)
    """

    def __init__(self, last_hash: str | None = None) -> None:
        """Initialize the chain.

        Args:
            last_hash: The hash of the most recent entry in the existing
                       chain. If None, starts from the genesis hash
                       (new chain or first entry).
        """
        self._prev_hash = last_hash or GENESIS_HASH

    @property
    def prev_hash(self) -> str:
        """The hash of the most recent entry (chain head)."""
        return self._prev_hash

    def append(self, entry_data: dict[str, Any]) -> tuple[str, str]:
        """Compute the hash for a new entry and advance the chain.

        Args:
            entry_data: The audit entry data to hash. Must be
                        JSON-serializable.

        Returns:
            Tuple of (entry_hash, prev_hash) to store in the audit entry.
            entry_hash is the new chain head.
            prev_hash is what the entry_hash was computed from.
        """
        prev_hash = self._prev_hash
        entry_hash = self._compute_hash(entry_data, prev_hash)
        self._prev_hash = entry_hash
        return entry_hash, prev_hash

    @staticmethod
    def verify_entry(
        entry_data: dict[str, Any],
        expected_hash: str,
        prev_hash: str,
    ) -> bool:
        """Verify a single entry's hash against its claimed prev_hash.

        Args:
            entry_data: The entry data (same fields used during append).
            expected_hash: The stored entry_hash to verify.
            prev_hash: The stored prev_hash for this entry.

        Returns:
            True if the hash matches, False if tampered.
        """
        computed = HashChain._compute_hash(entry_data, prev_hash)
        return computed == expected_hash

    @staticmethod
    def verify_chain(entries: list[dict[str, Any]]) -> bool:
        """Verify the integrity of an entire hash chain.

        Entries must be in chronological order and each must contain
        'entry_hash' and 'prev_hash' fields.

        Args:
            entries: Ordered list of audit entries with hash fields.

        Returns:
            True if the entire chain is valid, False if any entry
            has been tampered with.
        """
        if not entries:
            return True

        # First entry's prev_hash should be the genesis hash
        if entries[0].get("prev_hash", "") != GENESIS_HASH:
            return False

        for i, entry in enumerate(entries):
            # Extract hash fields and compute verification data
            stored_hash = entry.get("entry_hash", "")
            stored_prev = entry.get("prev_hash", "")

            # Append-only: every field is hash-protected.
            # Only exclude the hash chain fields themselves.
            entry_data = {
                k: v for k, v in entry.items()
                if k not in ("entry_hash", "prev_hash")
            }

            computed = HashChain._compute_hash(entry_data, stored_prev)
            if computed != stored_hash:
                return False

            # Verify chain linkage: this entry's prev_hash should match
            # the previous entry's entry_hash
            if i > 0:
                if stored_prev != entries[i - 1].get("entry_hash", ""):
                    return False

        return True

    @staticmethod
    def _compute_hash(entry_data: dict[str, Any], prev_hash: str) -> str:
        """Compute SHA-256 hash of entry data concatenated with prev_hash.

        Uses canonical JSON serialization for deterministic output.
        """
        canonical = json.dumps(entry_data, sort_keys=True, separators=(",", ":"))
        payload = f"{canonical}|{prev_hash}"
        return hashlib.new(HASH_ALGORITHM, payload.encode("utf-8")).hexdigest()
