# IntentFrame B2B deployment (Route B: edge + `base_url` clients)

Run one IntentFrame runtime in a container and reach it from anywhere —
including running your existing test/demo harnesses from your Mac against
the remote container.

## Components

```
┌─ intentframe-runtime container ───────────────────────────┐
│  entrypoint.sh                                             │
│    1. credential-vault  (HashiCorp backend)  ── first up   │
│    2. supervisor  (minimal graph by default)               │
│         policy-registry ─┐                                 │
│         executor ────────┴─► intentframe-server (UDS)        │
│         (resource-registry only with the kit profile)      │
│  shared volume: ~/.intentframe/run/*.sock                  │
└───────────────┬────────────────────────────────────────────┘
                │ if-run volume (sockets)
┌───────────────▼─ intentframe-edge container ──────────────┐
│  HTTP(S) :8443  (minimal routes by default)                │
│    /policies*   → policy-registry.sock                     │
│    /handshake /process /audit* → intentframe.sock          │
│    /workspaces* → resource-registry.sock  (kit profile)    │
└───────────────┬────────────────────────────────────────────┘
                │ HTTP(S)
        your Mac: tests / agents (base_url = http(s)://HOST:8443)
```

Supervisor and edge are generic, config-driven substrate. By **default** they
run the minimal graph — `policy-registry`, `executor`, `intentframe-server`, and
the edge routes `/policies` + `/handshake|/process|/audit`. The
**resource-registry** service and its `/workspaces` route are **opt-in** via the
first-party kit profiles (see [§4](#4-enable-workspaces-resource-registry)). The
**executor** and **credential-vault** are never exposed by the edge — they stay
UDS-only inside the environment.

`intentframe-server` is also config-driven: `INTENTFRAME_CORE_CONFIG` points at a
`core.yaml` profile declaring the action bundles to load. The compose default is
the first-party kit profile (`/app/packages/intentframe-native-kit/intentframe_native_kit/core.yaml`); third
parties ship their own profile just like they ship their own executor config.
Entry-point short names vs module paths: [docs/plugin-profiles.md](../../docs/plugin-profiles.md).

## 1. Start the runtime + edge

```bash
export OPENAI_API_KEY=sk-...
export VAULT_ADDR=https://vault.acme.com:8200
export VAULT_ROLE_ID=...
export VAULT_SECRET_ID=...
# optional override; defaults to /app/packages/intentframe-native-kit/intentframe_native_kit/core.yaml
# export INTENTFRAME_CORE_CONFIG=/app/acme/core.yaml

docker compose -f deploy/prod/docker-compose.yml up --build
```

Health checks:

```bash
# edge (and the backends behind it) — minimal default graph
curl -fsS http://localhost:8443/health
# → {"status":"ok","backends":{"policy-registry":true,"intentframe-server":true}}
```

With the kit profiles enabled (see [§4](#4-enable-workspaces-resource-registry))
the summary also includes `"resource-registry":true`.

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

> **`ResourceRegistryClient` / `INTENTFRAME_RESOURCE_URL` need the kit
> profiles.** The default deploy has no `resource-registry` service and the edge
> has no `/workspaces` route, so workspace calls 404/502. If your tests create or
> resolve workspaces, enable the kit profiles first — see
> [§4](#4-enable-workspaces-resource-registry).

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

## 4. Enable workspaces (resource-registry)

The default deploy is the minimal substrate — no `resource-registry` service and
no `/workspaces` edge route. Workspaces (virtual→real mount tables, the agent's
`ClientView`, the executor's `ExecutorView`) are an **opt-in** for deployments
that want dynamic mount resolution or run workspace-dependent tests.

Enable them by setting **both** kit profiles before `up` (the runtime gets the
service, the edge gets the route — they must match):

```bash
export INTENTFRAME_SUPERVISOR_CONFIG="/app/packages/intentframe-native-kit/intentframe_native_kit/supervisor_profile.yaml"
export INTENTFRAME_EDGE_CONFIG="/app/packages/intentframe-native-kit/intentframe_native_kit/edge_profile.yaml"
docker compose -f deploy/prod/docker-compose.yml up --build
```

Verify the registry is now live:

```bash
curl -fsS http://localhost:8443/health
# → {"status":"ok","backends":{"policy-registry":true,"resource-registry":true,"intentframe-server":true}}
```

This is exactly how a third party runs IntentFrame for their own requirements:
the substrate ships generic, and you point it at the service graph, core bundle
profile, executor pack profile, and route set you need. The executor still works
without a registry by using the static `pack_options.files.mounts` table in its
`EXECUTOR_CONFIG`.

## Single-writer invariant

- One `intentframe-runtime` container = one supervisor = one writer.
  `replicas: 1`; never scale it.
- The edge is stateless ingress (no policy/audit/credential state), so it
  does not affect single-writer and can be scaled/restarted freely.
- Never point a second runtime container at the same `if-run` volume.
- The edge mounts `if-run` **read-write**: connecting to a Unix socket
  requires write permission on the socket inode, so a read-only mount
  would refuse the connection. It still holds no application state.
