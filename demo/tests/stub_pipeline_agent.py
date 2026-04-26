"""
Stub agent — full Actor → IntentFrame Core → Executor stack.

Loads fixed attack intent payloads from JSON fixtures
(``demo/demo_data/attack_intents/``) and submits them through the Actor SDK.
Each fixture carries the realistic intent data a compromised agent would
actually produce — attack-specific reasons, injected metadata, fake
overrides — so the Analysis Engine and Guardian see real attack content.

Agent-agnostic: the stub is just a loop calling ``actor.submit()``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from intentframe_actor import Actor
from intentframe_core.types import AgentCapabilities, ExecutionResult, RuntimeContext

_INTENTS_DIR = Path(__file__).resolve().parents[2] / "demo" / "demo_data" / "attack_intents"


def load_attack_submissions(attack_num: int) -> list[dict[str, Any]]:
    """Load the intent fixture for *attack_num* from the JSON data directory.

    Searches both the top-level ``attack_intents/`` directory and all
    subdirectories (e.g. ``redteam/``).
    """
    pattern = f"attack_{attack_num:02d}_*.json"
    matches = list(_INTENTS_DIR.glob(pattern)) + list(_INTENTS_DIR.rglob(pattern))
    seen: dict[str, Path] = {}
    for m in matches:
        seen.setdefault(str(m), m)
    matches = list(seen.values())
    if not matches:
        raise FileNotFoundError(
            f"No intent fixture matching {pattern} in {_INTENTS_DIR}"
        )
    with open(matches[0]) as f:
        data = json.load(f)
    return data["submissions"]


class StubPipelineAgent:
    """
    Handshake once, then run a scripted list of submit dicts through Actor.

    Same transport and framing as production agents; no OpenAI Agents SDK.

    All async work (handshake → submits → close) runs on a single event
    loop so the underlying ``httpx.AsyncClient`` is never orphaned.
    """

    CAPABILITIES = AgentCapabilities(
        agent_type="StubPipelineTest",
        description=(
            "Test harness that submits pre-built intents through IntentFrame. "
            "Simulates post-compromise agent behavior."
        ),
        capabilities=["scripted_submits"],
        resource_needs=["invoices_directory", "expense_tracker_file"],
        action_types=[
            "LIST_DIRECTORY",
            "READ_FILE",
            "APPEND_ROW",
            "PAY_INVOICE",
        ],
        version="1.0.0",
        author="IntentFrame Tests",
    )

    def __init__(self, verbose: bool = True) -> None:
        self.verbose = verbose
        self._user_id: str = ""
        self._socket_path: str = "~/.intentframe/run/intentframe.sock"
        self._actor: Actor | None = None

    def setup(self, user_id: str, socket_path: str = "~/.intentframe/run/intentframe.sock") -> None:
        self._user_id = user_id
        self._socket_path = socket_path

    def run_submissions(self, submissions: list[dict[str, Any]]) -> list[ExecutionResult]:
        if not self._user_id:
            raise RuntimeError("StubPipelineAgent.setup() required before run_submissions()")
        return asyncio.run(self._run_all(submissions))

    async def _run_all(self, submissions: list[dict[str, Any]]) -> list[ExecutionResult]:
        """Handshake, submit everything, close — all on one event loop."""
        actor = Actor(
            agent_id="stub_pipeline_agent",
            user_id=self._user_id,
            socket_path=self._socket_path,
        )
        try:
            ctx = await actor.handshake(self.CAPABILITIES)
            if self.verbose:
                print(
                    f"    [STUB] Handshake OK — user={self._user_id!r}, "
                    f"allowed_actions={len(ctx.allowed_actions)}"
                )

            out: list[ExecutionResult] = []
            for req in submissions:
                action = req.get("action", "?")
                r = await actor.submit(req)
                out.append(r)
                if self.verbose:
                    dec = ""
                    if isinstance(r.data, dict):
                        dec = str(r.data.get("decision", ""))
                    snip = repr((r.error or "")[:100])
                    print(
                        f"    [STUB] {action} → success={r.success} decision={dec} err={snip}"
                    )
            return out
        finally:
            await actor.close()

    # ── Async primitives for multi-intent test sessions ────────────────
    #
    # Callers that want one handshake across many intents drive the loop
    # themselves with these three methods.  ``run_submissions`` above
    # stays for single-shot use cases (existing invoice/redteam tests).

    async def open(self, user_id: str, socket_path: str) -> RuntimeContext:
        """Open the Actor and perform the one-time handshake."""
        if self._actor is not None:
            raise RuntimeError("StubPipelineAgent.open() called on an already-open agent")
        self._user_id = user_id
        self._socket_path = socket_path
        self._actor = Actor(
            agent_id="stub_pipeline_agent",
            user_id=user_id,
            socket_path=socket_path,
        )
        ctx = await self._actor.handshake(self.CAPABILITIES)
        if self.verbose:
            print(
                f"    [STUB] Handshake OK — user={user_id!r}, "
                f"allowed_actions={len(ctx.allowed_actions)}"
            )
        return ctx

    async def submit(self, req: dict[str, Any]) -> ExecutionResult:
        """Submit one intent on the open Actor session."""
        if self._actor is None:
            raise RuntimeError("StubPipelineAgent.open() required before submit()")
        action = req.get("action", "?")
        r = await self._actor.submit(req)
        if self.verbose:
            dec = ""
            if isinstance(r.data, dict):
                dec = str(r.data.get("decision", ""))
            snip = repr((r.error or "")[:100])
            print(
                f"    [STUB] {action} → success={r.success} decision={dec} err={snip}"
            )
        return r

    async def close(self) -> None:
        """Close the Actor session."""
        if self._actor is None:
            return
        try:
            await self._actor.close()
        finally:
            self._actor = None
