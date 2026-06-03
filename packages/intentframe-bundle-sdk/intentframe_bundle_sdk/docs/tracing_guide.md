# Bundle SDK tracing guide

This guide explains how to read and query the Bundle SDK's internal lifecycle
audit log. For a short overview, see [Lifecycle trace](../README.md#lifecycle-trace-internal-audit)
in the SDK README.

---

## What gets traced (and what does not)

The trace log is **SDK-internal forensic data**. It is separate from:

- Substrate audit entries (`intentframe-core` pipeline audit)
- `BundleDeterministicResult` returned to callers

An auditor inspects the bundle-runtime process log directly. Trace data never
appears on the wire to `intentframe-core` consumers.

Each hook invocation (or deliberate skip) writes **one JSON line** to
`bundle-sdk.log`. Every record captures the **full function frame**:

- All positional and keyword arguments, bound to parameter names via
  `inspect.signature`
- Values serialised with `audit_dump` (Pydantic models, dataclasses, evidence
  objects, etc.)
- The audit-dumped return value, or `repr(exc)` on failure

There is no curated field list. New hook parameters show up automatically.

---

## Log location

| Setting | Path |
|---------|------|
| Default | `~/.intentframe/logs/bundle-sdk.log` |
| `$INTENTFRAME_LOG_DIR` | `$INTENTFRAME_LOG_DIR/bundle-sdk.log` |
| `configure_trace_logging(log_dir)` | `{log_dir}/bundle-sdk.log` |

Rotated backups (10 MB each, up to 3): `bundle-sdk.log.1`, `.2`, `.3`.

The logger name is `bundle_sdk.trace`. Records do **not** propagate to
`intentframe-core.log`.

**First write:** the file is created on the first traced hook in the process
(policy validation at boot, bundle `startup`, first intent through the runner,
etc.).

**Silent mode:** if the log directory is not writable (some sandboxes, CI),
tracing degrades to a no-op `NullHandler` — hooks still run, nothing is written.

---

## Record format

Each line is one JSON object (JSONL). Fields:

| Field | Type | Description |
|-------|------|-------------|
| `ts` | string | UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`) |
| `lane` | string | `boot`, `lifecycle`, `handshake`, or `runtime` |
| `trace_id` | string | Correlation id (format varies by lane — see below) |
| `phase` | string | Hook name or synthetic phase |
| `skipped` | bool | `true` when the runner chose not to call the hook |
| `skipped_reason` | string \| null | Why the hook was skipped |
| `elapsed_ms` | number \| null | Wall-clock milliseconds (null for skips) |
| `inputs` | object \| null | Full bound arguments (`null` when skipped) |
| `output` | any \| null | Audit-dumped return value (`null` on exception) |
| `raised` | string \| null | `repr(exc)` when the hook raised |
| `terminal` | bool | `true` when this hook produced the final BLOCK/ALLOW |

Example runtime record:

```json
{
  "ts": "2026-05-26T08:30:00Z",
  "lane": "runtime",
  "trace_id": "jarvis:abc123:7:email",
  "phase": "enrich",
  "skipped": false,
  "skipped_reason": null,
  "elapsed_ms": 1.234,
  "inputs": {
    "intent": { "action": "READ_MESSAGES", "target": "in:inbox", "...": "..." },
    "action_permission": { "safe": true, "constraints": null },
    "ctx": { "intent": { "...": "..." }, "evidence": {}, "...": "..." },
    "verbose": false
  },
  "output": {
    "decision": "CONTINUE",
    "context": { "...": "..." },
    "reason": "",
    "matched_gate": "",
    "terminal": false
  },
  "raised": null,
  "terminal": false
}
```

Skip example (no constraints on the action):

```json
{
  "ts": "2026-05-26T08:30:01Z",
  "lane": "runtime",
  "trace_id": "jarvis:abc123:7:email",
  "phase": "enforce_constraints",
  "skipped": true,
  "skipped_reason": "action_permission.constraints is None",
  "elapsed_ms": null,
  "inputs": null,
  "output": null,
  "raised": null,
  "terminal": false
}
```

---

## Lanes and trace_id formats

There is **no single trace_id** spanning an entire server session. Correlate
records by lane and `trace_id` pattern.

### `boot` — policy seed load

| Phase | Hook |
|-------|------|
| `validate_constraints` | `ActionBundle.validate_constraints` |
| `validate` | `DomainBundle.validate` |

| trace_id pattern | Example |
|------------------|---------|
| `boot:{bundle_id}:{action_id}` | `boot:email:READ_MESSAGES` |
| `boot:{bundle_id}:{domain_id}` | `boot:finance:finance` |

### `lifecycle` — server start / shutdown

| Phase | Hook |
|-------|------|
| `startup` | `ActionBundle.startup` / `DomainBundle.startup` |
| `aclose` | `ActionBundle.aclose` / `DomainBundle.aclose` |

| trace_id pattern | Example |
|------------------|---------|
| `lifecycle:{bundle_id}` | `lifecycle:email` |

### `handshake` — onboarding prompt assembly

| Phase | Hook |
|-------|------|
| `onboarding_guardrails` | `ActionBundle.onboarding_guardrails` |

| trace_id pattern | Example |
|------------------|---------|
| `handshake:{bundle_id}` | `handshake:email` |

### `runtime` — per intent in `DeterministicRunner`

Built by `make_trace_id(intent, bundle_id)`:

```
{agent_id}:{session_suffix}:{sequence_id}:{bundle_id}
```

- `session_suffix` — last segment of `intent.session_id` after splitting on `_`
- Example: `jarvis:abc123:7:email`

Runtime phases (in gate order):

```
prepare_evidence
  → enrich
  → enforce_constraints          (or skipped)
  → domain_enforce:{domain_id}   (or skipped per domain)
  → structural_gates
  → _try_passive_read_allow
  → allow_gates
  → describe_constraints         (UNDECIDED path only)
  → domain_describe:{domain_id}  (UNDECIDED path only, per routed domain)
  → build_ai_context             (UNDECIDED path only)
```

Gate order diagram:

```
permission (substrate — not traced here)
  → prepare_evidence
  → enrich
  → enforce_constraints
  → domain.enforce
  → structural_gates
  → passive_read ALLOW (_try_passive_read_allow)
  → allow_gates
  → UNDECIDED + build_ai_context
```

A record with `"terminal": true` marks the hook that returned the final
BLOCK or ALLOW. If no runtime record has `terminal: true`, the runner ended
UNDECIDED (check for `build_ai_context` without a prior terminal hook).

---

## Reading the log

### Tail live while processing intents

```bash
tail -f ~/.intentframe/logs/bundle-sdk.log
```

### Pretty-print one line

```bash
tail -1 ~/.intentframe/logs/bundle-sdk.log | python3 -m json.tool
```

### Convert entire log to a pretty JSON array

The file is JSONL (one object per line), not a single JSON value:

```bash
python3 <<'PY' > /tmp/bundle-sdk-trace.json
import json
from pathlib import Path

path = Path("~/.intentframe/logs/bundle-sdk.log").expanduser()
records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
print(json.dumps(records, indent=2))
PY
```

### List runtime trace_ids and hook counts

```bash
python3 <<'PY'
import json
from collections import defaultdict
from pathlib import Path

by_id = defaultdict(list)
for line in Path("~/.intentframe/logs/bundle-sdk.log").expanduser().read_text().splitlines():
    if line.strip():
        r = json.loads(line)
        if r["lane"] == "runtime":
            by_id[r["trace_id"]].append(r)

for tid, recs in sorted(by_id.items(), key=lambda x: -len(x[1])):
    terminal = [r["phase"] for r in recs if r.get("terminal")]
    print(f"{len(recs):3d} hooks  {tid!r}  terminal={terminal or 'UNDECIDED'}")
PY
```

### Full start-to-end trace for one intent

Pick a `trace_id` from the list above, then:

```bash
TRACE_ID='jarvis:abc123:7:email'

python3 <<PY | python3 -m json.tool > /tmp/trace-one-intent.json
import json
from pathlib import Path

trace_id = "$TRACE_ID"
records = []
for line in Path("~/.intentframe/logs/bundle-sdk.log").expanduser().read_text().splitlines():
    if not line.strip():
        continue
    r = json.loads(line)
    if r["trace_id"] == trace_id and r["lane"] == "runtime":
        records.append(r)

print(json.dumps({
    "trace_id": trace_id,
    "hook_count": len(records),
    "phases_in_order": [r["phase"] for r in records],
    "terminal_phase": next((r["phase"] for r in records if r.get("terminal")), None),
    "hooks": records,
}, indent=2))
PY
```

### Compact timeline (without full inputs/outputs)

```bash
python3 <<'PY'
import json
from pathlib import Path

trace_id = "jarvis:abc123:7:email"  # change me
for line in Path("~/.intentframe/logs/bundle-sdk.log").expanduser().read_text().splitlines():
    if not line.strip():
        continue
    r = json.loads(line)
    if r["trace_id"] != trace_id or r["lane"] != "runtime":
        continue
    out = r.get("output") or {}
    decision = out.get("decision") if isinstance(out, dict) else None
    gate = out.get("matched_gate") if isinstance(out, dict) else None
    print(
        f"{r['ts']}  {r['phase']:32s}  "
        f"skipped={r['skipped']}  terminal={r['terminal']}  "
        f"decision={decision}  gate={gate}  elapsed_ms={r['elapsed_ms']}"
    )
PY
```

### Find terminal decisions

```bash
grep '"terminal": true' ~/.intentframe/logs/bundle-sdk.log | tail -5
```

### Filter by action (from dumped intent in inputs)

```bash
grep '"action": "READ_MESSAGES"' ~/.intentframe/logs/bundle-sdk.log | head -3
```

---

## Worked example: auditing passive read

Passive read is decided in `_try_passive_read_allow` when:

1. `intent.action` is in `bundle.passive_read_action_ids`
2. `action_permission.safe` is `true`

Steps:

1. Find runtime records for the intent's `trace_id`.
2. Locate phase `_try_passive_read_allow`.
3. Confirm:
   - `inputs.action_permission.safe` is `true`
   - `inputs.intent.action` is a passive-read action
   - `output.decision` is `"ALLOW"`
   - `output.matched_gate` is `"passive_read"`
   - `terminal` is `true` (if passive read was the final decision)

```bash
grep '_try_passive_read_allow' ~/.intentframe/logs/bundle-sdk.log | tail -1 | python3 -m json.tool
```

If `output` is `null` and `terminal` is `false`, passive read did not apply
(action not in `passive_read_action_ids`, or `safe` was `false`).

---

## Tracing during tests

### Default pytest behaviour

Most tests write to `~/.intentframe/logs/bundle-sdk.log` when they load bundles
or run intents through `DeterministicRunner`. Running the full suite accumulates
records from boot, lifecycle, handshake, and runtime lanes.

`tests/test_bundle_sdk_trace.py` uses an isolated temp directory per test via
`configure_trace_logging(tmp_path)` — those records are **not** in the default
log file.

### Capture a fresh trace for one test run

```bash
export INTENTFRAME_LOG_DIR=/tmp/intentframe-test-trace
mkdir -p "$INTENTFRAME_LOG_DIR"

.venv/bin/python -m pytest tests/test_deterministic_gate_matrix.py -q

python3 <<'PY' > /tmp/test-trace-pretty.json
import json
from pathlib import Path
p = Path("/tmp/intentframe-test-trace/bundle-sdk.log")
records = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
print(json.dumps(records, indent=2))
PY
```

### Run trace unit tests

```bash
.venv/bin/python -m pytest tests/test_bundle_sdk_trace.py -v
```

---

## Configuration API

Only one public symbol is exported for integrators:

```python
from pathlib import Path
from intentframe_bundle_sdk import configure_trace_logging

configure_trace_logging(Path("/custom/log/dir"))
```

- Idempotent — first call wins for the process lifetime
- Auto-called on first hook if not configured explicitly
- Use `reset_trace_logging()` from `intentframe_bundle_sdk.trace` in tests only

Internal helpers (`traced_call`, `traced_acall`, `emit_skip`, `make_trace_id`)
are called by SDK modules (`runner`, `loader`, `lifecycle`, `onboarding`,
`registry`). Plugin authors should not call them.

---

## Implementation reference

| Module | Role |
|--------|------|
| `trace.py` | Logger setup, wrappers, emission |
| `audit_dump.py` | JSON-safe serialisation of hook args/returns |
| `runner.py` | Runtime lane — all gate hooks + skips |
| `loader.py` | Boot lane — `validate_constraints` |
| `registry.py` | Boot lane — `DomainBundle.validate` |
| `lifecycle.py` | Lifecycle lane — `startup`, `aclose` |
| `onboarding.py` | Handshake lane — `onboarding_guardrails` |

When bundle-runtime becomes a separate UDS process (see
`policy_registry/TODO/bundle_validator.md`), this log file moves with that
process. `BundleDeterministicResult` and substrate audit formats stay unchanged.

---

## Related

- [SDK README — Lifecycle trace](../README.md#lifecycle-trace-internal-audit)
- [bundle_validator.md](../../policy_registry/TODO/bundle_validator.md) — future process-isolated bundle runtime
- `tests/test_bundle_sdk_trace.py` — trace format regression tests
