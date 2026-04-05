"""
Actor — the agent-side SDK for IntentFrame.

Actor is a client library that agent developers use in their tool
calls.  It parses raw request dicts into signed IntentFrames and
sends them to the IntentFrame Runtime over HTTP.

Actor is platform-controlled and trusted.  IntentFrame Runtime only
accepts IntentFrames from certified Actors (verified signatures).

    Agent tool call
        │
        ▼
    Actor.submit({"action": "READ_FILE", ...})
        │  1. Parse & validate
        │  2. Build IntentFrame (add metadata, signature)
        │  3. HTTP POST to Runtime
        │
        ▼
    ExecutionResult back to agent
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from intentframe_server.client import AsyncIntentFrameClient
from action_registry import ActionType
from action_registry.types import ACTION_DOMAINS
from intentframe_core.domains import DOMAIN_SCHEMAS
from intentframe_core.types import (
    AgentCapabilities,
    ExecutionResult,
    IntentFrame,
    RuntimeContext,
)

logger = logging.getLogger(__name__)


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
        agent_id: str,
        user_id: str,
        socket_path: str = "~/.intentframe/run/intentframe.sock",
    ) -> None:
        self.agent_id = agent_id
        self.user_id = user_id
        self.runtime_context: Optional[RuntimeContext] = None
        self.agent_capabilities: Optional[AgentCapabilities] = None

        self._socket_path = socket_path
        self._sequence_id = 0
        self._client: Optional[AsyncIntentFrameClient] = None

    def _get_client(self) -> AsyncIntentFrameClient:
        if self._client is None:
            self._client = AsyncIntentFrameClient(socket_path=self._socket_path)
        return self._client

    # ── Handshake ─────────────────────────────────────────────────────

    async def handshake(self, capabilities: AgentCapabilities) -> RuntimeContext:
        """
        Perform handshake with IntentFrame Runtime.

        Sends agent_id, user_id, and capabilities. The server looks up
        the user's real policies from the policy registry — Actor never
        knows or sends policy data.

        Returns:
            RuntimeContext that the agent can use in its system prompt.
        """
        client = self._get_client()
        ctx = await client.handshake(capabilities, self.user_id)
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
        return await client.process_intent(intent, self.user_id)

    # ── Close ─────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Release HTTP connections."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    # ── Internal ──────────────────────────────────────────────────────

    _RESERVED_KEYS = frozenset({"action", "target", "reason"})

    def _build_intent(self, agent_request: Dict[str, Any]) -> IntentFrame:
        """Parse a raw agent request dict into a signed IntentFrame.

        Fields ``action``, ``target``, and ``reason`` are extracted into
        their dedicated IntentFrame fields.  All remaining keys are
        captured into ``IntentFrame.data`` so they arrive as adapter
        params without any per-action translation layer.

        Backward compatibility: if the caller passes an explicit ``data``
        dict (legacy style) with no other extra keys, it is used as-is.
        """
        action_str = agent_request.get("action", "")
        try:
            action = ActionType[action_str]
        except KeyError:
            raise ValueError(
                f"Unknown action '{action_str}'. "
                f"Valid: {[a.name for a in ActionType]}"
            )

        # Capture every non-reserved key into data.  If the caller used
        # the legacy {"data": {...}} style, merge it with any flat keys.
        extra = {k: v for k, v in agent_request.items()
                 if k not in self._RESERVED_KEYS}
        explicit_data = extra.pop("data", None)
        if isinstance(explicit_data, dict):
            data = {**explicit_data, **extra} or None
        else:
            data = extra or None

        # Validate data against the domain schema for critical domains.
        domain = ACTION_DOMAINS.get(action)
        if domain is not None:
            schema_cls = DOMAIN_SCHEMAS.get(domain)
            if schema_cls is not None:
                raw = data or {}
                try:
                    schema_cls(**raw)
                except Exception as exc:
                    raise ValueError(
                        f"{action.name} is in the {domain.value} domain and "
                        f"requires valid {schema_cls.__name__} data: {exc}"
                    ) from exc

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
            agent_id=self.agent_id,
            session_id=session_id,
            sequence_id=self._sequence_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            authorized_by=self.user_id,
            agent_type=agent_type,
            actor_verified=True,
            signature=f"sig_{self.agent_id}_{self._sequence_id}",
        )
