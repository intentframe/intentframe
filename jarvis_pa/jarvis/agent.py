"""Full agent loop: setup, chat, run_single.

JarvisAgent wires everything together – Actor handshake, workspace
bootstrap, memory indexing, skill discovery, prompt building,
heartbeat, and the OpenAI Agents SDK chat loop.

LiteLLM integration: set ``model`` in config.yaml to any provider
string (e.g. "anthropic/claude-sonnet-4", "gemini/gemini-2.5-pro")
and LiteLLM routes calls transparently through the OpenAI-compatible
interface that the Agents SDK expects.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from typing import Any

from agents import Agent, OpenAIResponsesModel, Runner
from loguru import logger
from openai import AsyncOpenAI

try:
    import litellm  # noqa: F401 — keep for future multi-provider support
    _LITELLM_AVAILABLE = True
except ImportError:
    _LITELLM_AVAILABLE = False

try:
    from intentframe_actor import Actor
    from intentframe_core.types import AgentCapabilities, RuntimeContext
    _INTENTFRAME_AVAILABLE = True
except ImportError:
    # Allow running without IntentFrame during development / unit tests.
    Actor = None  # type: ignore[assignment,misc]
    AgentCapabilities = None  # type: ignore[assignment,misc]
    RuntimeContext = None  # type: ignore[assignment,misc]
    _INTENTFRAME_AVAILABLE = False

from jarvis.config import JarvisConfig
from jarvis.heartbeat import HeartbeatRunner
from jarvis.memory import MemoryManager
from jarvis.memory_index import MemoryIndexer
from jarvis.memory_search import MemorySearcher
from jarvis.prompt import build_system_prompt
from jarvis.session import Session
from jarvis.skills import build_skills_xml, discover_skills, gate_skills
from jarvis.tools import ALL_TOOLS
from jarvis.types import AgentContext

# ---------------------------------------------------------------------------
# Declared capabilities sent during handshake
# ---------------------------------------------------------------------------

_CAPABILITY_LIST = [
    "file_ops", "commands", "email", "calendar", "reminders",
    "notes", "messages", "browser", "clipboard", "spotlight",
    "notifications", "system_control",
]

_ACTION_TYPES = [
    "READ_FILE", "WRITE_FILE", "LIST_DIRECTORY", "DELETE_FILE",
    "RUN_COMMAND",
    "SEND_EMAIL", "READ_EMAIL", "SEARCH_EMAIL",
    "GET_EMAIL", "REPLY_EMAIL", "FORWARD_EMAIL", "MARK_READ_EMAIL",
    "MOVE_EMAIL", "DELETE_EMAIL", "DOWNLOAD_ATTACHMENT",
    "CREATE_EVENT", "LIST_EVENTS", "LIST_CALENDARS", "UPDATE_EVENT",
    "DELETE_EVENT", "SEARCH_EVENTS",
    "CREATE_REMINDER", "LIST_REMINDERS", "LIST_REMINDER_LISTS",
    "COMPLETE_REMINDER", "UPDATE_REMINDER", "DELETE_REMINDER",
    "CREATE_NOTE", "LIST_NOTES", "READ_NOTE", "DELETE_NOTE",
    "SEND_MESSAGE", "READ_MESSAGES",
    "SEARCH_CONTACTS", "GET_CONTACT", "ADD_CONTACT",
    "UPDATE_CONTACT", "DELETE_CONTACT",
    "OPEN_URL", "SEARCH_WEB", "GET_PAGE_CONTENT",
    "GET_CLIPBOARD", "SET_CLIPBOARD",
    "SEARCH_SPOTLIGHT", "SHOW_NOTIFICATION", "ASK_USER",
    "GET_SYSTEM_INFO", "SET_VOLUME", "SET_BRIGHTNESS", "TOGGLE_DARK_MODE",
]


def _make_capabilities() -> Any:
    if _INTENTFRAME_AVAILABLE and AgentCapabilities is not None:
        return AgentCapabilities(
            agent_type="PersonalAssistant",
            description="Jarvis – macOS personal assistant",
            capabilities=_CAPABILITY_LIST,
            action_types=_ACTION_TYPES,
            version="0.1.0",
            author="jarvis",
        )
    return None


# ---------------------------------------------------------------------------
# LiteLLM-aware OpenAI client builder
# ---------------------------------------------------------------------------

def _build_openai_client(config: JarvisConfig) -> AsyncOpenAI:
    """Return an AsyncOpenAI client, routing through LiteLLM when the model
    is not a native OpenAI model (e.g. 'anthropic/claude-sonnet-4').

    LiteLLM runs a local proxy server on first use when configured, but here
    we use the simpler approach: set the base_url to LiteLLM's proxy if the
    model string contains a provider prefix.
    """
    model = config.model
    is_openai_native = not ("/" in model)

    if _LITELLM_AVAILABLE and not is_openai_native:
        # LiteLLM proxy: start inline or use environment-configured proxy.
        proxy_url = os.environ.get("LITELLM_PROXY_URL", "http://localhost:4000")
        logger.debug(f"Non-OpenAI model '{model}' — routing through LiteLLM proxy at {proxy_url}")
        return AsyncOpenAI(
            base_url=proxy_url,
            api_key=os.environ.get("LITELLM_API_KEY", "litellm"),
        )

    return AsyncOpenAI()


# ---------------------------------------------------------------------------
# JarvisAgent
# ---------------------------------------------------------------------------

class JarvisAgent:
    """Top-level orchestrator that owns all subsystems."""

    def __init__(self, config: JarvisConfig) -> None:
        self.config = config

        # IntentFrame actor (the only external dependency for IO).
        # Falls back to a no-op stub when IntentFrame is not installed.
        if _INTENTFRAME_AVAILABLE and Actor is not None:
            self.actor: Any = Actor(
                agent_id=config.agent_id,
                user_id=config.user_id,
                socket_path=config.socket_path,
            )
        else:
            self.actor = _StubActor()

        workspace = config.workspace_dir / "workspace"
        sessions = config.workspace_dir / "sessions"
        db_path = config.workspace_dir / "index" / "memory.db"

        # Subsystems – initialised but not yet started.
        self.session = Session(sessions, config)
        self.memory = MemoryManager(workspace, self.actor, config)
        self.indexer = MemoryIndexer(db_path, config)
        self.searcher = MemorySearcher(db_path, config)
        self.heartbeat = HeartbeatRunner(self, config)

        # Set after setup().
        self.runtime_ctx: Any | None = None
        self.agent: Agent | None = None
        self.ctx: AgentContext | None = None
        self._session_id: str | None = None

    # -- setup ---------------------------------------------------------------

    async def setup(self) -> None:
        """Perform handshake, bootstrap, index, build prompt, start heartbeat."""
        logger.info("Jarvis setup starting…")

        # 1. Handshake with IntentFrame (skip gracefully without it).
        if _INTENTFRAME_AVAILABLE:
            try:
                caps = _make_capabilities()
                self.runtime_ctx = await self.actor.handshake(caps)
                logger.debug("IntentFrame handshake complete")
            except Exception as exc:
                logger.warning(f"IntentFrame handshake failed ({exc}) — falling back to dev mode")
                self.actor = _StubActor()
        else:
            logger.warning("IntentFrame not available — running in dev mode (no real IO)")

        # 2. Bootstrap workspace on first run.
        await self.memory.bootstrap_if_needed()
        logger.debug("Workspace bootstrapped")

        # 3. Load workspace files.
        soul = await self.memory.read_file("SOUL.md")
        user = await self.memory.read_file("USER.md")
        memory = await self.memory.read_file("MEMORY.md")
        heartbeat_md = await self.memory.read_file("HEARTBEAT.md")

        guardrails: list[str] = []
        virtual_paths: list[str] = []
        path_permissions: dict[str, str] = {}
        if self.runtime_ctx is not None:
            if hasattr(self.runtime_ctx, "guardrails"):
                guardrails = self.runtime_ctx.guardrails or []
            if hasattr(self.runtime_ctx, "virtual_paths"):
                virtual_paths = self.runtime_ctx.virtual_paths or []
            if hasattr(self.runtime_ctx, "path_permissions"):
                path_permissions = self.runtime_ctx.path_permissions or {}

        # 4. Session ID.
        import uuid
        self._session_id = str(uuid.uuid4())[:8]

        # 5. Create Agent context.
        self.ctx = AgentContext(actor=self.actor, config=self.config, searcher=self.searcher)

        # 6. Resolve model — string for native OpenAI, Model object for LiteLLM.
        model_name = self.config.model
        is_openai_native = "/" not in model_name

        # M3: Open indexer + searcher and index workspace.
        try:
            self.indexer.open()
            self.searcher.open()
            workspace_dir = self.config.workspace_dir / "workspace"
            await self.indexer.index_workspace(workspace_dir, self.actor)
            logger.debug("Memory workspace indexed")
        except Exception as exc:
            logger.warning(f"Memory indexing failed (non-fatal): {exc}")

        # M4: Discover and gate skills.
        skills_xml = ""
        self._gated_skills: list = []
        try:
            raw_skills = discover_skills(self.config.skill_dirs)
            gated_skills = gate_skills(raw_skills)
            skills_xml = build_skills_xml(gated_skills)
            self._gated_skills = gated_skills
            logger.debug(f"Skills: {len(gated_skills)}/{len(raw_skills)} active")
        except Exception as exc:
            logger.warning(f"Skill discovery failed (non-fatal): {exc}")

        # 7. Build instructions callable.
        # The closure captures all static inputs (soul, user, skills, etc.)
        # so they stay one-shot from setup(). Only the cheap Jinja render +
        # datetime.now() runs per turn, giving the model a fresh timestamp
        # without compromising the prefix-based prompt cache.
        def _instructions(_ctx, _agent):
            return build_system_prompt(
                soul=soul,
                user=user,
                memory=memory,
                heartbeat=heartbeat_md,
                guardrails=guardrails,
                virtual_paths=virtual_paths,
                path_permissions=path_permissions,
                skills_xml=skills_xml,
                config=self.config,
                session_id=self._session_id,
            )

        logger.debug(f"System prompt assembled ({len(_instructions(None, None))} chars)")

        # 8. Create the OpenAI Agents SDK Agent.
        #    Only set verbosity; let the API decide reasoning effort (medium).
        from agents import ModelSettings
        settings = ModelSettings(verbosity="low")

        if is_openai_native:
            self.agent = Agent(
                name="jarvis",
                instructions=_instructions,
                tools=ALL_TOOLS,
                model=model_name,
                model_settings=settings,
            )
        else:
            openai_client = _build_openai_client(self.config)
            litellm_model = _build_model(openai_client, model_name)
            self.agent = Agent(
                name="jarvis",
                instructions=_instructions,
                tools=ALL_TOOLS,
                model=litellm_model,
                model_settings=settings,
            )
        logger.info(f"Agent created — model={model_name}")

        # M5: Start heartbeat background loop.
        self.heartbeat.start()

    # -- chat ----------------------------------------------------------------

    async def chat(self, message: str) -> str:
        """Process a user message through the full agent loop. Returns response text."""
        if self.agent is None or self.ctx is None:
            raise RuntimeError("call setup() before chat()")

        self.session.append_user(message)
        await self.session.maybe_compact(self.memory)

        messages = self.session.to_openai_messages()
        result = await Runner.run(self.agent, messages, context=self.ctx)
        response = result.final_output

        self.session.append_assistant(response)

        # Auto-capture triggers and re-index if memory changed.
        self.memory.auto_capture(message, response)
        if self.memory.files_changed:
            workspace = self.config.workspace_dir / "workspace"
            try:
                await self.indexer.index_workspace(workspace, self.actor)
                self.memory.files_changed = False
            except Exception as exc:
                logger.warning(f"Re-index after auto-capture failed: {exc}")

        logger.debug(f"Chat complete — tokens≈{self.session.estimate_tokens()}")
        return response

    # -- streaming chat ------------------------------------------------------

    async def chat_stream(self, message: str) -> AsyncGenerator[dict[str, Any], None]:
        """Process a user message, yielding streaming events as they arrive.

        Yields dicts with ``type`` key:
          - ``{"type": "text_delta", "delta": "..."}``
          - ``{"type": "tool_call", "name": "...", "arguments": "..."}``
          - ``{"type": "done", "response": "...", "tokens": N}``
          - ``{"type": "error", "error": "..."}``

        Handles session persistence, auto-capture, and re-indexing
        identically to ``chat()``.
        """
        from openai.types.responses import ResponseTextDeltaEvent

        if self.agent is None or self.ctx is None:
            yield {"type": "error", "error": "call setup() before chat_stream()"}
            return

        self.session.append_user(message)
        await self.session.maybe_compact(self.memory)

        messages = self.session.to_openai_messages()
        accumulated = ""
        final: str | None = None

        try:
            result = Runner.run_streamed(self.agent, messages, context=self.ctx)

            async for event in result.stream_events():
                if event.type == "raw_response_event":
                    if isinstance(event.data, ResponseTextDeltaEvent):
                        accumulated += event.data.delta
                        yield {"type": "text_delta", "delta": event.data.delta}

                elif event.type == "run_item_stream_event":
                    if (
                        event.name == "tool_called"
                        and event.item.type == "tool_call_item"
                    ):
                        raw = getattr(event.item, "raw_item", None)
                        name = getattr(raw, "name", "tool")
                        arguments = getattr(raw, "arguments", "{}")
                        yield {
                            "type": "tool_call",
                            "name": name,
                            "arguments": arguments,
                        }

            final = result.final_output if result.final_output is not None else accumulated

        except Exception as exc:
            logger.warning(f"Streaming failed ({exc}), falling back to sync run")
            try:
                sync_result = await Runner.run(self.agent, messages, context=self.ctx)
                final = sync_result.final_output if sync_result.final_output is not None else ""
            except Exception as fallback_exc:
                yield {"type": "error", "error": str(fallback_exc)}
                return

        if final is None:
            final = accumulated or ""

        self.session.append_assistant(final)

        self.memory.auto_capture(message, final)
        if self.memory.files_changed:
            workspace = self.config.workspace_dir / "workspace"
            try:
                await self.indexer.index_workspace(workspace, self.actor)
                self.memory.files_changed = False
            except Exception as exc:
                logger.warning(f"Re-index after auto-capture failed: {exc}")

        tokens = self.session.estimate_tokens()
        logger.debug(f"Chat stream complete — tokens≈{tokens}")
        yield {"type": "done", "response": final, "tokens": tokens}

    # -- single-shot ---------------------------------------------------------

    async def run_single(self, prompt: str) -> str:
        """One-shot LLM call (used by heartbeat, summarisation, etc.)."""
        if self.agent is None:
            raise RuntimeError("call setup() before run_single()")
        result = await Runner.run(
            self.agent,
            [{"role": "user", "content": prompt}],
            context=self.ctx,
        )
        return result.final_output

    # -- shutdown ------------------------------------------------------------

    async def shutdown(self) -> None:
        """Gracefully stop heartbeat and close actor connection."""
        logger.info("Shutting down Jarvis…")
        await self.heartbeat.stop()
        self.indexer.close()
        self.searcher.close()
        if _INTENTFRAME_AVAILABLE and hasattr(self.actor, "close"):
            await self.actor.close()
        logger.info("Goodbye.")


# ---------------------------------------------------------------------------
# LiteLLM-aware model provider for the Agents SDK
# ---------------------------------------------------------------------------

def _build_model(client: AsyncOpenAI, model_name: str) -> OpenAIResponsesModel:
    """Return an Agents SDK Model backed by the given OpenAI client.

    Uses the Responses API (``/v1/responses``) which supports hosted tools
    like ``WebSearchTool``, ``FileSearchTool``, etc.
    """
    return OpenAIResponsesModel(model=model_name, openai_client=client)


# ---------------------------------------------------------------------------
# Stub actor for development without IntentFrame
# ---------------------------------------------------------------------------

class _StubActor:
    """No-op actor used when IntentFrame is not installed."""

    async def handshake(self, capabilities: Any) -> None:
        return None

    async def submit(self, action: dict[str, Any]) -> "_StubResult":
        logger.warning(f"[stub] actor.submit called: {action.get('action')} — IntentFrame not available")
        return _StubResult()

    async def close(self) -> None:
        pass


class _StubResult:
    success = False
    data: dict[str, Any] = {}
    error = "IntentFrame not available (dev mode)"
