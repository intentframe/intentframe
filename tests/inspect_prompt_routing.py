#!/usr/bin/env python3
"""
Inspect AE/Guardian prompt routing for every ActionType.

Prints a deterministic text snapshot of:
  - per-action AE and Guardian prompt ids (+ system-body sha256)
  - deduplicated AE system prompt bodies
  - deduplicated Guardian system prompt bodies

Run:
    .venv/bin/python tests/inspect_prompt_routing.py

Capture baseline (on pre-refactor @ 66e567c):
    .venv/bin/python tests/inspect_prompt_routing.py \\
        > tests/fixtures/prompt_routing_legacy_baseline.txt

On refactor branches this script resolves routing via action bundles
(the live pipeline path).  Legacy prompt ids in the routing table are
derived from resolved system bodies plus the pre-refactor routing rules
so output stays comparable to the frozen baseline.
"""

from __future__ import annotations

import asyncio
import hashlib

from action_registry.types import ActionType
from intentframe_bundle_sdk.loader import ensure_loaded
from intentframe_bundle_sdk.registry import action_bundle_for
from intentframe_bundle_sdk.types import ActionPermission, BundleAIContext, BundleContext
from intentframe_components.analysis.engine import AIAnalysisEngine
from intentframe_components.guardian.engine import AIGuardian
from intentframe_core.types import IntentFrame
from intentframe_prompt_library.library import DEFAULT_AE_SYSTEM_INSTRUCTIONS

LEGACY_COMMIT = "66e567c"
SEPARATOR = "═" * 72
THIN_SEP = "─" * 72

_NO_CONSTRAINTS = ActionPermission(safe=True, constraints=None)

# Pre-refactor DefaultPromptStrategy routing pins (commit 66e567c).
CRITICAL_GENERIC_ACTIONS = frozenset({
    "DELETE_CONTACT",
    "DELETE_EMAIL",
    "DELETE_EVENT",
    "DELETE_FILE",
    "DELETE_HOST_FILE",
    "DELETE_NOTE",
    "DELETE_REMINDER",
    "HTTP_POST",
    "PAY_INVOICE",
    "SEND_EMAIL",
})

GUARDIAN_CRITICAL_ACTIONS = CRITICAL_GENERIC_ACTIONS | frozenset({"RUN_COMMAND"})

STANDARD_AE_SHA256 = hashlib.sha256(
    DEFAULT_AE_SYSTEM_INSTRUCTIONS.encode("utf-8")
).hexdigest()

_AE = AIAnalysisEngine(verbose=False)
_GU = AIGuardian(verbose=False)


def _intent(action: ActionType) -> IntentFrame:
    return IntentFrame(
        action=action,
        target="/tmp/x",
        reason="test",
        agent_id="prompt_routing_inspect",
    )


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _bundle_ai_context(action: ActionType) -> BundleAIContext:
    intent = _intent(action)
    bundle = action_bundle_for(action.value)
    if bundle is None:
        return BundleAIContext()
    ctx = BundleContext(intent=intent)
    return asyncio.run(bundle.build_ai_context(intent, _NO_CONSTRAINTS, ctx))


def _resolve_ae_body(ai_ctx: BundleAIContext) -> str:
    return _AE._resolve_system_instructions(ai_ctx)


def _resolve_guardian_body(ai_ctx: BundleAIContext) -> str:
    return _GU._resolve_system_instructions(ai_ctx)


def _legacy_ae_prompt_id(
    action: ActionType,
    ae_body: str,
    ai_ctx: BundleAIContext,
) -> str:
    if sha256(ae_body) != STANDARD_AE_SHA256:
        label = (ai_ctx.ae_prompt_label or "").strip()
        if label:
            return label
        if action == ActionType.RUN_COMMAND:
            return "critical_run_command"
        if action in {ActionType.WRITE_FILE, ActionType.WRITE_HOST_FILE}:
            return "critical_write_file"
    if action.value in CRITICAL_GENERIC_ACTIONS:
        return "critical_generic"
    return "standard"


def _legacy_guardian_prompt_id(action: ActionType) -> str:
    if action.value in GUARDIAN_CRITICAL_ACTIONS:
        return "critical"
    return "standard"


def main() -> None:
    ensure_loaded(["intentframe_native_bundles"])

    print("PROMPT ROUTING MATRIX")
    print(SEPARATOR)
    print(f"Legacy commit: {LEGACY_COMMIT}")
    print()
    print("ROUTING ROWS")
    print(THIN_SEP)
    print(
        "action|ae_prompt_id|guardian_prompt_id|ae_system_sha256|guardian_system_sha256"
    )

    ae_bodies_by_id: dict[str, str] = {}
    gu_bodies_by_id: dict[str, str] = {}

    for action in sorted(ActionType, key=lambda item: item.value):
        ai_ctx = _bundle_ai_context(action)
        ae_body = _resolve_ae_body(ai_ctx)
        gu_body = _resolve_guardian_body(ai_ctx)
        ae_id = _legacy_ae_prompt_id(action, ae_body, ai_ctx)
        gu_id = _legacy_guardian_prompt_id(action)
        ae_bodies_by_id.setdefault(ae_id, ae_body)
        gu_bodies_by_id.setdefault(gu_id, gu_body)
        print(
            f"{action.value}|{ae_id}|{gu_id}|{sha256(ae_body)}|{sha256(gu_body)}"
        )

    print()
    print("AE SYSTEM PROMPT BODIES")
    print(THIN_SEP)
    for ae_id in sorted(ae_bodies_by_id):
        print(f"[prompt_id={ae_id}]")
        print(ae_bodies_by_id[ae_id])
        print()

    print("GUARDIAN SYSTEM PROMPT BODIES")
    print(THIN_SEP)
    for gu_id in sorted(gu_bodies_by_id):
        print(f"[prompt_id={gu_id}]")
        print(gu_bodies_by_id[gu_id])
        print()


if __name__ == "__main__":
    main()
