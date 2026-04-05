"""
Credential scrubber — re-exported from the shared ``intentframe_credentials`` package.

All executor code continues to import from this module unchanged::

    from executor.services.credential_scrubber import CredentialScrubber
"""

from intentframe_credentials.redaction import CredentialScrubber

__all__ = ["CredentialScrubber"]
