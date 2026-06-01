"""
Actor — the agent-side SDK for IntentFrame.

A thin transport client: agent developers call ``Actor.submit()`` from tool
implementations to route I/O through the IntentFrame security pipeline.

The Actor parses request dicts into signed :class:`~intentframe_core.types.IntentFrame`
objects and POSTs them to the runtime. It does **not** validate action
taxonomy or critical-domain payload shape — that is optional author-side
work (e.g. Jarvis imports ``action_registry`` before submit). Unknown actions
and malformed domain payloads fail closed server-side in the bundle runner
and executor.

    Agent tool call
        │
        ▼
    Actor.submit({"action": "READ_FILE", ...})
        │  1. Parse request → IntentFrame (action as plain string)
        │  2. Add metadata, signature
        │  3. HTTP POST to Runtime
        │
        ▼
    ExecutionResult back to agent
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from intentframe_server.client import AsyncIntentFrameClient
from intentframe_core.types import (
    AgentCapabilities,
    ExecutionResult,
    IntentFrame,
    RuntimeContext,
)

logger = logging.getLogger(__name__)


def _resolve_user_id(explicit: str | None) -> str:
    """Pick the operator/owner id, preferring explicit > env > error.

    Env precedence: ``INTENTFRAME_USER_ID`` first; ``JARVIS_USER_ID`` is
    honoured as a one-release fallback so existing setup scripts keep
    working.  Raises if nothing is supplied — agents must not run with
    an implicit / empty owner.
    """
    if explicit:
        return explicit
    env = os.environ.get("INTENTFRAME_USER_ID") or os.environ.get("JARVIS_USER_ID")
    if env:
        return env
    raise ValueError(
        "Actor: no user_id provided. Pass user_id=... or set "
        "INTENTFRAME_USER_ID in the agent's environment."
    )


def _resolve_agent_id(explicit: str | None) -> str:
    """Pick the agent id, preferring explicit > env > error.

    External agents must declare their identity — implicit / empty
    agent ids would silently miss the wrong policy slot in the
    registry, so we fail loudly instead.
    """
    if explicit:
        return explicit
    env = os.environ.get("INTENTFRAME_AGENT_ID")
    if env:
        return env
    raise ValueError(
        "Actor: no agent_id provided. Pass agent_id=... or set "
        "INTENTFRAME_AGENT_ID in the agent's environment."
    )


class Actor:
    """
    IntentFrame Actor SDK.

    Agent developers create an Actor, handshake once, then call
    ``submit()`` from every tool that needs I/O.

    Actor handles:
    - Parsing raw request dicts into IntentFrames
    - Adding agent_id, session_id, timestamps, signatures
    - Sending IntentFrames to IntentFrame Runtime over HTTP
    - Returning ExecutionResults

    Actor does NOT:
    - Analyze intents (that's Analysis Engine)
    - Make policy decisions (that's Guardian)
    - Execute anything (that's Executor)
    - Hold credentials
    """

    def __init__(
        self,
        agent_id: str | None = None,
        user_id: str | None = None,
        socket_path: str = "~/.intentframe/run/intentframe.sock",
        *,
        base_url: str | None = None,
    ) -> None:
        """
        Args:
            agent_id: Identifier of this agent (e.g. ``"jarvis"``,
                ``"invoice_bot"``).  Falls back to ``INTENTFRAME_AGENT_ID``
                env var when omitted.  Required — raises if neither is set.
            user_id: Operator/owner id this agent runs on behalf of.
                Falls back to ``INTENTFRAME_USER_ID`` (and, for one
                release, ``JARVIS_USER_ID``).  Required — raises if
                neither is set.
            socket_path: UDS path to a local IntentFrame Runtime.
            base_url: Network URL of a remote runtime reached through the
                IntentFrame edge (e.g. ``https://intentframe.acme.com``).
                Falls back to the ``INTENTFRAME_CORE_URL`` env var.  When
                set, it takes precedence over ``socket_path``.

        The ``(user_id, agent_id)`` pair is used by the runtime to look
        up the correct policy slot, so empty/None values are rejected
        loudly rather than silently routing to the wrong policy.
        """
        self.user_id = _resolve_user_id(user_id)
        self.agent_id = _resolve_agent_id(agent_id)
        self.runtime_context: Optional[RuntimeContext] = None
        self.agent_capabilities: Optional[AgentCapabilities] = None

        self._socket_path = socket_path
        self._base_url = base_url
        self._sequence_id = 0
        self._client: Optional[AsyncIntentFrameClient] = None

    def _get_client(self) -> AsyncIntentFrameClient:
        if self._client is None:
            self._client = AsyncIntentFrameClient(
                socket_path=self._socket_path,
                base_url=self._base_url,
            )
        return self._client

    # ── Handshake ─────────────────────────────────────────────────────

    async def handshake(self, capabilities: AgentCapabilities) -> RuntimeContext:
        """
        Perform handshake with IntentFrame Runtime.

        Sends agent_id, user_id, and capabilities. The server looks up
        the policy registered against the ``(user_id, agent_id)`` pair
        — Actor never knows or sends policy data.

        Returns:
            RuntimeContext that the agent can use in its system prompt.
        """
        client = self._get_client()
        ctx = await client.handshake(capabilities, self.user_id, self.agent_id)
        self.runtime_context = ctx
        self.agent_capabilities = capabilities
        return ctx

    # ── Submit ────────────────────────────────────────────────────────

    async def submit(self, agent_request: Dict[str, Any]) -> ExecutionResult:
        """
        Full round-trip: parse → build IntentFrame → send to Runtime → return result.

        This is the ONLY way agents should perform I/O through IntentFrame.

        Args:
            agent_request: Raw dict with "action", "target", "data", "reason".

        Returns:
            ExecutionResult from the IntentFrame Runtime.
        """
        if self.runtime_context is None:
            raise RuntimeError(
                "Actor.handshake() must be called before submit(). "
            )

        self._sequence_id += 1
        intent = self._build_intent(agent_request)
        client = self._get_client()
        return await client.process_intent(intent, self.user_id, self.agent_id)

    # ── Close ─────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Release HTTP connections."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    # ── Internal ──────────────────────────────────────────────────────

    _RESERVED_KEYS = frozenset({"action", "target", "reason", "display_subject"})

    def _build_intent(self, agent_request: Dict[str, Any]) -> IntentFrame:
        """Parse a raw agent request dict into a signed IntentFrame.

        Fields ``action``, ``target``, ``reason``, and ``display_subject``
        are extracted into dedicated IntentFrame fields. ``action`` is passed
        through as an opaque string with no taxonomy check. All remaining keys
        are captured into ``IntentFrame.data`` so they arrive as adapter params
        without any per-action translation layer.

        Backward compatibility: if the caller passes an explicit ``data``
        dict (legacy style) with no other extra keys, it is merged with any
        flat keys.
        """
        action = agent_request.get("action", "")

        # Capture every non-reserved key into data.  If the caller used
        # the legacy {"data": {...}} style, merge it with any flat keys.
        extra = {k: v for k, v in agent_request.items()
                 if k not in self._RESERVED_KEYS}
        explicit_data = extra.pop("data", None)
        if isinstance(explicit_data, dict):
            data = {**explicit_data, **extra} or None
        else:
            data = extra or None

        agent_type = ""
        if self.agent_capabilities:
            agent_type = self.agent_capabilities.agent_type

        session_id = ""
        if self.runtime_context:
            session_id = self.runtime_context.session_id

        return IntentFrame(
            action=action,
            target=agent_request.get("target", ""),
            data=data,
            reason=agent_request.get("reason", ""),
            display_subject=agent_request.get("display_subject", ""),
            agent_id=self.agent_id,
            session_id=session_id,
            sequence_id=self._sequence_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            authorized_by=self.user_id,
            agent_type=agent_type,
            actor_verified=True,
            signature=f"sig_{self.agent_id}_{self._sequence_id}",
        )
