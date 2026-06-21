# intentframe-client

Low-level HTTP/UDS transport client for the
[IntentFrame](https://github.com/intentframe/intentframe) Core service
(`IntentFrameClient`, `AsyncIntentFrameClient`). Supports local Unix-domain
sockets and remote HTTPS via `INTENTFRAME_CORE_URL`.

Agent developers usually want the higher-level `intentframe-actor` wrapper.

```bash
pip install intentframe-client
```

PyPI: [intentframe-client](https://pypi.org/project/intentframe-client/) · `pip install intentframe-client==0.1.1` · License: Apache-2.0 · [Consumer guide](../../docs/package-consumers.md)
