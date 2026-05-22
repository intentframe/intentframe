"""Register all first-party action and domain bundles with the SDK."""

from __future__ import annotations

from intentframe_action_bundle.bundles.domain import DeletionDomainBundle, FinanceDomainBundle
from intentframe_action_bundle.bundles.email import EmailActionBundle
from intentframe_action_bundle.bundles.files import FilesActionBundle
from intentframe_action_bundle.bundles.host_files import HostFilesActionBundle
from intentframe_action_bundle.bundles.passive_read import PassiveReadActionBundle
from intentframe_action_bundle.bundles.terminal import TerminalActionBundle
from intentframe_bundle_sdk.action import CheckerOnlyActionBundle
from intentframe_bundle_sdk.registry import register_action_bundle, register_domain_bundle
from policy_registry.constraints import (
    ApiConstraints,
    BrowserConstraints,
    MessageConstraints,
)

_BUNDLES_LOADED = False


def ensure_bundles_registered() -> None:
    global _BUNDLES_LOADED
    if _BUNDLES_LOADED:
        return

    register_action_bundle(TerminalActionBundle())
    register_action_bundle(FilesActionBundle())
    register_action_bundle(HostFilesActionBundle())
    register_action_bundle(PassiveReadActionBundle())
    register_action_bundle(EmailActionBundle())
    register_action_bundle(CheckerOnlyActionBundle("message", MessageConstraints))
    register_action_bundle(CheckerOnlyActionBundle("browser", BrowserConstraints))
    register_action_bundle(CheckerOnlyActionBundle("api", ApiConstraints))

    register_domain_bundle(FinanceDomainBundle())
    register_domain_bundle(DeletionDomainBundle())

    _BUNDLES_LOADED = True
