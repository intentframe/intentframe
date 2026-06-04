# Policy seeding — layering and admin workflow

This document explains **who loads policy**, **what gets validated where**, and how to seed a running deployment without reimplementing demo-test or Jarvis plumbing.

For Jarvis-specific overrides and YAML shape, see [policy-guide.md](policy-guide.md).

## Strategy (why the split exists)

IntentFrame separates three concerns:

| Layer | Package | Responsibility |
|-------|---------|----------------|
| Contracts | `intentframe_core` | `ActionPermission`, `SemanticIntentLimit`, pipeline types |
| Data store | `policy_registry` | Persist and serve `UserPolicy` over HTTP/UDS; **structure only** on write |
| Semantics | `intentframe_bundle_sdk` | “Does this constraint dict match the bundle for this action?” |
| Orchestrator | Gateway, CLI, tests, **`scripts/admin/`** | Load YAML → validate bundles → `POST /policies` |
| Runtime | `intentframe_server` | **Read** policy via `PolicyRegistryClient`; enforce per intent |

`policy_registry` must not import `intentframe_bundle_sdk`. That keeps the registry a leaf and avoids packaging cycles.

```text
  YAML file
      │
      ▼
  load_policy_seed()              ← policy_registry (schema version + Pydantic)
      │
      ▼
  validate_policy_with_bundles()  ← bundle SDK (orchestrator calls this)
      │
      ▼
  PolicyRegistryClient.set_user_policy()  ← POST /policies
      │
      ▼
  intentframe-server GET /policies/{user}/{agent}  on each handshake/process
```

**Two validation kinds:**

1. **Structure** — `UserPolicy` fields, `intentframe_schema_version`, opaque `constraints` dicts. Done in `load_policy_seed`.
2. **Semantics** — registered action exists, constraint keys match bundle family schemas. Done by `validate_policy_with_bundles` **before** POST.

The registry HTTP API does not re-run bundle validation on `POST`/`PATCH`. Runtime enforcement still fail-closes if bad data slips through.

## Reference admin script

Copy or edit:

```text
scripts/admin/seed_policy.py
scripts/admin/README.md
```

It is the canonical “admin orchestrator” example: same pattern as `demo/tests/policy_loader.py`, but with a CLI and UDS/HTTP transport via `PolicyRegistryClient`.

### Prerequisites

Supervisor running with `policy-registry` (kit profile for demos that need workspaces):

```bash
# First-party kit profiles live in the installed intentframe-native-kit package
# (there is no intentframe_native_kit/ directory at the repo root).
KIT="$(uv run python -c 'import intentframe_native_kit as k, pathlib; print(pathlib.Path(k.__file__).parent)')"
INTENTFRAME_CORE_CONFIG="${KIT}/core.yaml" \
EXECUTOR_CONFIG=demo/config/executor_attacks.yaml \
uv run python -m supervisor.main start \
  --config "${KIT}/supervisor_profile.yaml"
```

From repo root: `uv sync`.

### Example — demo attack policy (local UDS)

Matches `demo/config/test_policy.yaml` and `attack_tester` / `stub_pipeline_agent`:

```bash
uv run python scripts/admin/seed_policy.py \
  --policy demo/config/test_policy.yaml \
  --user-id attack_tester \
  --agent-id stub_pipeline_agent \
  --bundle intentframe_native_kit.intentframe_native_bundles \
  --metadata '{"note":"seeded via scripts/admin"}'
```

Then run attack tests (they also upsert policy themselves):

```bash
python demo/tests/test_attacks.py 1
```

### Example — Jarvis user policy

Uses packaged YAML (or `~/.intentframe/policies/jarvis.yaml` if you copy an override there and point `--policy` at it):

```bash
uv run python scripts/admin/seed_policy.py \
  --policy jarvis_pa/jarvis/policies/jarvis.yaml \
  --user-id jarvis_default \
  --agent-id jarvis \
  --bundle intentframe_native_kit.intentframe_native_bundles \
  --skip-if-exists
```

Gateway bootstrap does the same load + validate + POST on startup; this script is for manual/dev seeding without the gateway.

**Note:** Jarvis also needs a **workspace** in resource-registry. Use `jarvis_pa/seed_policies.py` or gateway bootstrap for workspace mounts; `seed_policy.py` is policy-only.

### Example — deploy/dev over HTTP

With the dev container and edge on port 8443:

```bash
export INTENTFRAME_POLICY_URL=http://localhost:8443

uv run python scripts/admin/seed_policy.py \
  --policy demo/config/test_policy.yaml \
  --user-id attack_tester \
  --agent-id stub_pipeline_agent \
  --bundle intentframe_native_kit.intentframe_native_bundles
```

No script changes — `PolicyRegistryClient` reads `INTENTFRAME_POLICY_URL` when set.

### Useful flags

| Flag | When to use |
|------|----------------|
| `--skip-if-exists` | Idempotent seed (Jarvis-style; skip POST if slot exists) |
| `--no-validate-bundles` | Parse-only smoke test (not recommended for real seeds) |
| `--bundle` (repeatable) | Override default native bundle list |
| `--policy-url` / `--socket` | Explicit transport |

## Who seeds today (implementation map)

| Caller | Transport | Bundle validate | Workspace |
|--------|-----------|-----------------|-----------|
| [`scripts/admin/seed_policy.py`](../../scripts/admin/seed_policy.py) | `PolicyRegistryClient` (UDS or URL) | Yes (default) | No |
| [`intentframe_gateway/bootstrap.py`](../../intentframe_gateway/bootstrap.py) | Gateway proxy HTTP | Yes (`core.yaml` bundles) | Yes |
| [`jarvis_pa/seed_policies.py`](../../jarvis_pa/seed_policies.py) | Raw UDS `httpx` today | If `INTENTFRAME_CORE_CONFIG` set | Yes |
| [`demo/tests/policy_loader.py`](../../demo/tests/policy_loader.py) | Via test `PolicyRegistryClient` | Yes | Via test helpers |
| [`intentframe_server`](../../packages/intentframe-server/intentframe_server/) | GET only | N/A (reads store) | N/A |

## Validate without posting

Structure + bundles in-process (no registry required):

```bash
uv run python - <<'PY'
from pathlib import Path
from intentframe_bundle_sdk.loader import validate_policy_with_bundles
from policy_registry.seeds import load_policy_seed

policy = load_policy_seed(
    Path("demo/config/test_policy.yaml"),
    user_id="u",
    agent_id="stub_pipeline_agent",
)
validate_policy_with_bundles(
    policy, ["intentframe_native_kit.intentframe_native_bundles"]
)
print("OK:", len(policy.allowed_actions), "actions")
PY
```

## Related packaging work

Foundation types moved to `intentframe_core` (`policy.py`, `executor.py`) so `policy_registry` and `executor_client` do not pull higher layers. Future split: separate installable wheels with `policy_registry → intentframe_core` only; orchestrators depend on both registry and bundle SDK.

Write-time bundle validation in the policy-registry **process** is optional future work (`policy_registry/TODO/bundle_validator.md`); the current model validates at the orchestrator before POST.
