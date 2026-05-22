"""Bundle manifest model — action metadata for routing and policy bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from intentframe_action_bundle.critical.actions import CRITICAL_ONLY_ACTIONS
from intentframe_action_bundle.files.actions import WRITE_FILE_ACTIONS
from intentframe_action_bundle.host_files.deterministic import HOST_FILE_ACTIONS
from intentframe_action_bundle.passive_read.actions import PASSIVE_READ_ACTIONS
from intentframe_action_bundle.terminal import ACTION_IDS as TERMINAL_ACTIONS
from policy_registry.constraints import (
    ApiConstraints,
    BrowserConstraints,
    EmailConstraints,
    FileConstraints,
    HostFileConstraints,
    MessageConstraints,
    TerminalConstraints,
)


@dataclass(frozen=True)
class ActionBundleManifest:
    """Declarative bundle metadata — policy supplies limits; manifest supplies behavior."""

    bundle_id: str
    action_ids: frozenset[str] = frozenset()
    constraint_type: type | None = None
    ae_prompt_ids: frozenset[str] = frozenset()
    passive_read: bool = False
    critical: bool = False
    has_pre_pipeline: bool = False
    has_executor_floor: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


_MANIFESTS: tuple[ActionBundleManifest, ...] = (
    ActionBundleManifest(
        bundle_id="terminal",
        action_ids=TERMINAL_ACTIONS,
        constraint_type=TerminalConstraints,
        ae_prompt_ids=frozenset({
            "critical_run_command",
            "critical_network_probe",
            "critical_network_mutation",
        }),
        critical=True,
        has_pre_pipeline=True,
        has_executor_floor=True,
    ),
    ActionBundleManifest(
        bundle_id="files",
        action_ids=WRITE_FILE_ACTIONS,
        constraint_type=FileConstraints,
        ae_prompt_ids=frozenset({"critical_write_file"}),
        has_pre_pipeline=True,
        has_executor_floor=True,
    ),
    ActionBundleManifest(
        bundle_id="host_files",
        action_ids=HOST_FILE_ACTIONS,
        constraint_type=HostFileConstraints,
        critical=True,
        has_pre_pipeline=True,
        has_executor_floor=True,
    ),
    ActionBundleManifest(
        bundle_id="passive_read",
        action_ids=PASSIVE_READ_ACTIONS,
        passive_read=True,
    ),
    ActionBundleManifest(
        bundle_id="email",
        constraint_type=EmailConstraints,
    ),
    ActionBundleManifest(
        bundle_id="message",
        constraint_type=MessageConstraints,
    ),
    ActionBundleManifest(
        bundle_id="browser",
        constraint_type=BrowserConstraints,
    ),
    ActionBundleManifest(
        bundle_id="api",
        constraint_type=ApiConstraints,
        ae_prompt_ids=frozenset({"critical_generic"}),
        critical=True,
    ),
    ActionBundleManifest(
        bundle_id="critical",
        action_ids=CRITICAL_ONLY_ACTIONS,
        ae_prompt_ids=frozenset({"critical_generic"}),
        critical=True,
    ),
)

_ACTION_TO_BUNDLE: dict[str, ActionBundleManifest] = {}
for _manifest in _MANIFESTS:
    for _action_id in _manifest.action_ids:
        _ACTION_TO_BUNDLE[_action_id] = _manifest


def all_manifests() -> tuple[ActionBundleManifest, ...]:
    return _MANIFESTS


def manifest_for(action_id: str) -> ActionBundleManifest | None:
    return _ACTION_TO_BUNDLE.get(action_id)


def constraint_checkers() -> dict[type, Any]:
    """Build CONSTRAINT_CHECKERS from bundle-owned checker classes."""
    from intentframe_action_bundle.api.checker import ApiChecker
    from intentframe_action_bundle.browser.checker import BrowserChecker
    from intentframe_action_bundle.email.checker import EmailChecker
    from intentframe_action_bundle.files.checker import FileChecker
    from intentframe_action_bundle.host_files.checker import HostFileChecker
    from intentframe_action_bundle.message.checker import MessageChecker
    from intentframe_action_bundle.terminal.checker import TerminalChecker

    return {
        FileConstraints: FileChecker(),
        HostFileConstraints: HostFileChecker(),
        TerminalConstraints: TerminalChecker(),
        EmailConstraints: EmailChecker(),
        MessageConstraints: MessageChecker(),
        BrowserConstraints: BrowserChecker(),
        ApiConstraints: ApiChecker(),
    }
