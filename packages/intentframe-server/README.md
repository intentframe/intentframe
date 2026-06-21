# intentframe-server

The core runtime of [IntentFrame](https://github.com/intentframe/intentframe):
a FastAPI server (on a Unix domain socket) that receives pre-built IntentFrames
and runs them through the policy pipeline — analysis engine, guardian, and the
executor. Served as `intentframe_server.server:app`.

Depends on `intentframe-core`, `intentframe-components`,
`intentframe-policy-registry`, and `intentframe-executor-client`.

```bash
pip install intentframe-server
```

PyPI: [intentframe-server](https://pypi.org/project/intentframe-server/) · `pip install intentframe-server==0.1.1` · License: AGPL-3.0 · [Consumer guide](../../docs/package-consumers.md)

Core profile (`INTENTFRAME_CORE_CONFIG` → `core.yaml`): set `executor.hmac_key` (or `INTENTFRAME_EXECUTOR_HMAC_KEY`) to the same secret as the executor's `auth.options.secret_key`. See [`config/core.example.yaml`](intentframe_server/config/core.example.yaml) and [`docs/plugin-profiles.md`](../../docs/plugin-profiles.md).
