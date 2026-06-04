# intentframe-edge

Network-facing HTTP/TLS ingress for an IntentFrame runtime.

The edge is a thin, stateless reverse proxy. It terminates TCP/TLS/auth at the
deployment boundary and forwards approved routes to supervisor-managed services
over Unix domain sockets. Its default backend set exposes the substrate routes
only; the first-party native kit supplies an optional profile that also exposes
`/workspaces` through the resource registry.

```bash
python -m intentframe_edge --host 0.0.0.0 --port 8443
intentframe-edge --config "${KIT}/edge_profile.yaml"
```
