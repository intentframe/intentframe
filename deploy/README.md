# IntentFrame B2B deployment (Route B: edge + `base_url` clients)

Run one IntentFrame runtime in a container and reach it from anywhere —
including running your existing test/demo harnesses from your Mac against
the remote container.

## Components

```
┌─ intentframe-runtime container ───────────────────────────┐
│  entrypoint.sh                                             │
│    1. credential-vault  (HashiCorp backend)  ── first up   │
│    2. supervisor                                           │
│         policy-registry ─┐                                 │
│         resource-registry├─► intentframe-core (UDS)        │
│         executor ────────┘        │                        │
│  shared volume: ~/.intentframe/run/*.sock                  │
└───────────────┬────────────────────────────────────────────┘
                │ if-run volume (sockets)
┌───────────────▼─ intentframe-edge container ──────────────┐
│  HTTP(S) :8443                                             │
│    /policies*   → policy-registry.sock                     │
│    /workspaces* → resource-registry.sock                   │
│    /handshake /process /audit* → intentframe.sock          │
└───────────────┬────────────────────────────────────────────┘
                │ HTTP(S)
        your Mac: tests / agents (base_url = http(s)://HOST:8443)
```

The edge only exposes the three services a remote client legitimately
needs. The **executor** and **credential-vault** stay UDS-only inside the
environment.

## 1. Start the runtime + edge

```bash
export OPENAI_API_KEY=sk-...
export VAULT_ADDR=https://vault.acme.com:8200
export VAULT_ROLE_ID=...
export VAULT_SECRET_ID=...

docker compose -f deploy/docker-compose.yml up --build
```

Health checks:

```bash
# edge (and the backends behind it)
curl -fsS http://localhost:8443/health
# → {"status":"ok","backends":{"policy-registry":true,"resource-registry":true,"intentframe-core":true}}
```

> For a pipeline-only environment (no host I/O), set
> `INTENTFRAME_EXECUTOR_MODE=dry_run` — the executor service is skipped and
> core uses an in-process dry-run executor.

## 2. Run your tests from the Mac against the remote container

The three registry/runtime clients now accept a `base_url`, and also read
it from the environment. So your existing harnesses
(`demo/tests/test_attacks.py`, etc.) run unmodified — just point them at
the edge:

```bash
export INTENTFRAME_CORE_URL=http://CONTAINER_HOST:8443
export INTENTFRAME_POLICY_URL=http://CONTAINER_HOST:8443
export INTENTFRAME_RESOURCE_URL=http://CONTAINER_HOST:8443

python -m demo.tests.test_attacks 1 2 3
```

`PolicyRegistryClient()`, `ResourceRegistryClient()`, `IntentFrameClient()`
and `Actor(...)` all pick up these URLs automatically. The edge path-routes
each call to the right backend socket, so one base URL serves all three.

In code you can also pass it explicitly:

```python
from intentframe_actor import Actor
actor = Actor(agent_id="invoice-bot", user_id="acme",
              base_url="https://intentframe.acme.com:8443")
```

## 3. Enable TLS / mTLS (recommended for real networks)

Plain HTTP is fine for a trusted network or a quick demo. For real remote
access, terminate TLS at the edge and require client certs:

```yaml
# in docker-compose.yml, intentframe-edge.environment:
INTENTFRAME_EDGE_TLS_CERT: "/certs/server.pem"
INTENTFRAME_EDGE_TLS_KEY:  "/certs/server-key.pem"
INTENTFRAME_EDGE_TLS_CA:   "/certs/clients-ca.pem"   # omit for server-only TLS
# and mount:  - ./certs:/certs:ro
```

Then use `https://HOST:8443` for the `*_URL` env vars. A coarse bearer
token can be layered on with `INTENTFRAME_EDGE_TOKEN` (clients send
`Authorization: Bearer <token>`).

## Single-writer invariant

- One `intentframe-runtime` container = one supervisor = one writer.
  `replicas: 1`; never scale it.
- The edge is stateless ingress (no policy/audit/credential state), so it
  does not affect single-writer and can be scaled/restarted freely.
- Never point a second runtime container at the same `if-run` volume.
- The edge mounts `if-run` **read-write**: connecting to a Unix socket
  requires write permission on the socket inode, so a read-only mount
  would refuse the connection. It still holds no application state.
