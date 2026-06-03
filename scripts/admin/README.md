# scripts/admin/

Reference admin utilities for seeding IntentFrame registries. Copy or edit these scripts for installers, demos, and one-off dev workflows.

**Strategy and longer examples:** [docs/dev/policy-seeding.md](../../docs/dev/policy-seeding.md) (layering, who validates what, deploy/dev HTTP).

## `seed_policy.py`

Loads a policy YAML, optionally validates constraint shapes against registered bundles, and upserts into **policy-registry** via `PolicyRegistryClient`.

### Prerequisites

- Supervisor running with `policy-registry` (and bundles loaded in core if you rely on runtime enforcement).
- From repo root with deps installed: `uv sync`.

### Local UDS (default)

```bash
python -m supervisor.main start \
  --config intentframe_native_kit/supervisor_profile.yaml

uv run python scripts/admin/seed_policy.py \
  --policy demo/config/test_policy.yaml \
  --user-id attack_tester \
  --agent-id stub_pipeline_agent \
  --bundle intentframe_native_kit.intentframe_native_bundles
```

Uses `~/.intentframe/run/policy-registry.sock` when `INTENTFRAME_POLICY_URL` is unset.

### Deploy/dev over HTTP (edge)

```bash
export INTENTFRAME_POLICY_URL=http://localhost:8443

uv run python scripts/admin/seed_policy.py \
  --policy demo/config/test_policy.yaml \
  --user-id attack_tester \
  --agent-id stub_pipeline_agent \
  --bundle intentframe_native_kit.intentframe_native_bundles
```

Same script; `PolicyRegistryClient` reads the env var automatically.

### Common flags

| Flag | Purpose |
|------|---------|
| `--skip-if-exists` | Jarvis-style idempotent seed (GET first, skip POST) |
| `--no-validate-bundles` | Structure-only; skips `validate_policy_with_bundles` |
| `--metadata '{"note":"..."}'` | Shallow merge into policy `metadata` |
| `--policy-url` / `--socket` | Explicit transport override |

### Layering

| Step | Owner |
|------|--------|
| YAML → `UserPolicy` | `policy_registry.seeds.load_policy_seed` |
| Bundle constraint check | `intentframe_bundle_sdk.loader.validate_policy_with_bundles` |
| Store | `policy_registry` HTTP API (`POST /policies`) |

`policy_registry` does not import bundle SDK; this script is the orchestrator.

### Related callers

- `demo/tests/policy_loader.py` — same load + validate pattern for tests
- `jarvis_pa/seed_policies.py` — Jarvis-specific policy + workspace seed (still UDS-only today)
- `intentframe_gateway/bootstrap.py` — auto-seeds Jarvis on gateway startup
