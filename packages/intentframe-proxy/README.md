# intentframe-proxy

Shared HTTP and WebSocket proxy primitives for IntentFrame services that expose
HTTP APIs over Unix domain sockets.

The package provides `UDSProxy` and `proxy_websocket`, used by the product
gateway and the network edge so both paths share the same forwarding behavior.

```python
from intentframe_proxy import UDSProxy, proxy_websocket
```
PyPI: [intentframe-proxy](https://pypi.org/project/intentframe-proxy/) · `pip install intentframe-proxy==0.1.0` · License: Apache-2.0 · [Consumer guide](../../docs/package-consumers.md)
