"""Onboarding middle-section assembly — bundle SDK only."""

from __future__ import annotations

from intentframe_bundle_sdk.registry import all_action_bundles, onboarding_manifest


def render_onboarding_bundle_context(allowed_action_ids: frozenset[str]) -> str:
    """Join per-bundle guardrail blocks and unconditional manifest sections.

    Bundles supply paste-ready markdown via :meth:`ActionBundle.onboarding_guardrails`.
    Manifest sections are appended unconditionally after bundle blocks.
    This function only filters bundles by granted actions and joins with ``\\n\\n``.
    """
    blocks: list[str] = []

    for bundle in all_action_bundles():
        if not (bundle.action_ids & allowed_action_ids):
            continue
        text = bundle.onboarding_guardrails().strip()
        if text:
            blocks.append(text)

    for section in onboarding_manifest().sections:
        text = section.strip()
        if text:
            blocks.append(text)

    return "\n\n".join(blocks)
