"""
Cross-cutting services for the IntentFrame Executor.

These services provide shared infrastructure used by the gateway,
adapters, and each other. They are injected into components that
need them -- never accessed as globals or singletons.

Services are either:
    - Abstract (ABC): Platform-specific implementations plug in later
        - CredentialVault (Keychain on macOS, Vault on cloud, etc.)
        - AuditLogger (SQLite impl, cloud logging impl, etc.)
        - StateStore (SQLite impl, Redis impl, etc.)
        - VirtualFileSystem (local FS impl, cloud storage impl, etc.)

    - Concrete (platform-agnostic): Included in the skeleton
        - CredentialScrubber (regex-based sensitive data removal)
        - HashChain (SHA-256 chain for audit trail integrity)
"""

from executor_sdk.services.audit_logger import AuditLogger
from executor.services.credential_scrubber import CredentialScrubber
from executor_sdk.services.credential_vault import CredentialVault
from executor_sdk.services.hash_chain import HashChain
from executor_sdk.services.state_store import StateStore
from executor_sdk.services.virtual_filesystem import MountPointResolver, VirtualFileSystem

__all__ = [
    "AuditLogger",
    "CredentialScrubber",
    "CredentialVault",
    "HashChain",
    "MountPointResolver",
    "StateStore",
    "VirtualFileSystem",
]
