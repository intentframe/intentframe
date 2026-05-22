"""Merge bundle AE prompts and route prompt ids without ActionType in substrate."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType

from intentframe_action_bundle.critical.ae_routing import (
    select_ae_prompt_id as critical_select_ae_prompt_id,
)
from intentframe_action_bundle.files.ae_routing import (
    select_ae_prompt_id as files_select_ae_prompt_id,
)
from intentframe_action_bundle.files.prompts import AE_PROMPT_BODIES as FILES_PROMPTS
from intentframe_action_bundle.terminal.ae_routing import (
    select_ae_prompt_id as terminal_select_ae_prompt_id,
)
from intentframe_action_bundle.terminal.prompts import AE_PROMPT_BODIES as TERMINAL_PROMPTS
from intentframe_bundle_sdk.types import BundleContext

_AeSelector = Callable[[BundleContext], str | None]

_AE_SELECTORS: tuple[_AeSelector, ...] = (
    terminal_select_ae_prompt_id,
    files_select_ae_prompt_id,
    critical_select_ae_prompt_id,
)

_BUNDLE_PROMPT_BODIES: Mapping[str, str] = {
    **TERMINAL_PROMPTS,
    **FILES_PROMPTS,
}


def build_analysis_prompts(standard_body: str) -> Mapping[str, str]:
    """Assemble the full AE prompt catalog from substrate + bundle contributions."""
    merged: dict[str, str] = {
        "standard": standard_body,
        "critical_generic": standard_body,
        **_BUNDLE_PROMPT_BODIES,
    }
    return MappingProxyType(merged)


def select_ae_prompt_id(ctx: BundleContext) -> str:
    """Return the AE prompt id for this bundle context; ``standard`` when no match."""
    for selector in _AE_SELECTORS:
        prompt_id = selector(ctx)
        if prompt_id is not None:
            return prompt_id
    return "standard"


def analysis_prompt_ids(prompts: Mapping[str, str]) -> frozenset[str]:
    return frozenset(prompts.keys())
