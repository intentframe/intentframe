"""
IntentFrame Actor SDK — the agent-side gateway to IntentFrame.

Agent developers import Actor from this package and use it in their
tool implementations to route I/O through the IntentFrame security
pipeline.

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
