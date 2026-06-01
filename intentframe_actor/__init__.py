"""
IntentFrame Actor SDK — thin transport to the IntentFrame runtime.

Wraps tool calls: parse request dicts into :class:`~intentframe_core.types.IntentFrame`
(no action-registry validation) and POST to the pipeline. Agent authors who
want fail-fast taxonomy/domain checks import ``action_registry`` in their own
tool layer (see ``jarvis.tools``).

Usage::

    from intentframe_actor import Actor

    actor = Actor(
        agent_id="invoice_bot",
        user_id="finance_001",
        socket_path="~/.intentframe/run/intentframe.sock",
    )

    # Handshake once at startup
    runtime_ctx = await actor.handshake(capabilities)

    # Then in every tool call:
    result = await actor.submit({"action": "READ_FILE", "target": "/invoices/"})
"""

from intentframe_actor.actor import Actor

__all__ = ["Actor"]
