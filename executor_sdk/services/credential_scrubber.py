"""
Credential scrubber — re-exported from the shared ``intentframe_credentials`` package.

All executor code imports from this module::

    from executor_sdk.services.credential_scrubber import CredentialScrubber
"""

from intentframe_credentials.redaction import CredentialScrubber

__all__ = ["CredentialScrubber"]
