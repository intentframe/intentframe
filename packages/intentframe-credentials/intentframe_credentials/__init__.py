"""IntentFrame Credential Vault — internal secret management.

Public API re-exports for consumers::

    from intentframe_credentials import VaultClient, VaultClientSync
    from intentframe_credentials import CredentialVault, create_vault, register_backend
    from intentframe_credentials import CredentialScrubber, redact_credentials
    from intentframe_credentials import (
        DeliveryMode, CredentialRecord, CredentialRef,
        MaskedSummary, StoreRequest, mask_value,
    )
"""

from intentframe_credentials.backends.service_backend import ServiceVault
from intentframe_credentials.client import VaultClient, VaultClientSync
from intentframe_credentials.exceptions import (
    BackendUnavailableError,
    CredentialDeleteError,
    CredentialNotFoundError,
    CredentialStoreError,
    MetadataStoreError,
    ValidationFailedError,
    VaultError,
)
from intentframe_credentials.models import (
    CredentialRecord,
    CredentialRef,
    DeliveryMode,
    MaskedSummary,
    Namespace,
    StoreRequest,
    mask_value,
)
from intentframe_credentials.protocol import (
    CredentialVault,
    create_vault,
    register_backend,
    registered_backends,
)
from intentframe_credentials.redaction import (
    REDACTED_VALUE,
    SENSITIVE_KEYS,
    CredentialScrubber,
)
from intentframe_credentials.structlog_redactor import redact_credentials

__all__ = [
    # Protocol
    "CredentialVault",
    "create_vault",
    "register_backend",
    "registered_backends",
    # Backends
    "ServiceVault",
    # Client
    "VaultClient",
    "VaultClientSync",
    # Models
    "DeliveryMode",
    "Namespace",
    "CredentialRecord",
    "CredentialRef",
    "MaskedSummary",
    "StoreRequest",
    "mask_value",
    # Redaction
    "CredentialScrubber",
    "redact_credentials",
    "SENSITIVE_KEYS",
    "REDACTED_VALUE",
    # Exceptions
    "VaultError",
    "CredentialNotFoundError",
    "CredentialStoreError",
    "CredentialDeleteError",
    "ValidationFailedError",
    "BackendUnavailableError",
    "MetadataStoreError",
]
