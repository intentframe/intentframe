# intentframe-actor

The agent-side SDK for [IntentFrame](https://github.com/intentframe/intentframe).
Agent developers create an `Actor`, handshake once, then call `submit()` from
every tool that needs to touch the real world — each request is routed through
the IntentFrame security pipeline.

```bash
pip install intentframe-actor
```

```python
from intentframe_actor import Actor

actor = Actor(agent_id="invoice_bot", user_id="finance_001")
await actor.handshake(capabilities)
result = await actor.submit({"action": "READ_FILE", "target": "/invoices/"})
```
