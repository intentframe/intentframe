# intentframe-executor

The executor service for [IntentFrame](https://github.com/intentframe/intentframe).
It receives approved actions from the runtime, dispatches them to capability
adapters via a worker pool, and enforces the credential/audit boundary. It runs
as a FastAPI app on a Unix domain socket (`executor.server:app`).

Capability adapters are loaded as executor packs through the
`intentframe.executor_packs` entry-point group, so deployments select packs
without modifying this service. Built on `intentframe-executor-sdk`.

```bash
pip install intentframe-executor
```
