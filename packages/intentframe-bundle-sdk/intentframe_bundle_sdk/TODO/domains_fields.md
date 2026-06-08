agent devs should not be forced to use actual fields in domain module schema ..but the gent dev should pass maping for an actual executor field to domain module required field in action bundles for domain constraints determinstic check..this should make dev work easy when they already have tool calls already build and they might be using third party policy schemas or different team working on domain schema in bundles

# Domain field mapping (TODO)

## Problem

Today `check_domain_intent_shape` validates `IntentFrame.data` **directly** against
each routed domain's canonical `intent_schema` (e.g. `DeletionIntentData.path`,
`FinancialIntentData.amount`). Domain `enforce()` reads the same canonical keys.

Agent/tool authors should **not** be forced to rename their executor payload fields
to match domain-module schema names — especially when:

- tool calls and adapters already exist with fixed param names (`event_id`, `payment_amount`, …),
- a third-party or org policy schema uses different naming, or
- the domain schema is owned by a different team than the action/tool author.

Concrete gap today: `DELETE_EVENT` / `DELETE_REMINDER` use `event_id` / `reminder_id`,
not `path`, so they cannot route to the deletion domain without reshaping payloads.
See `deletion.py` and `domain_routes.py` (those actions are commented out).

## Proposed behavior

Introduce a **human-authored field map** from executor/tool payload keys → domain
schema keys, used only for deterministic domain checks (shape validation + `enforce`).

Example — calendar delete routed to deletion domain:

```python
# executor/tool payload uses event_id; deletion domain expects path
domains_mapping = {
    "deletion": {"path": "event_id"},
}
```

Before `intent_schema.validate_slice` and before `DomainBundle.enforce`, project:

```python
projected = {domain_key: data[executor_key] for domain_key, executor_key in mapping.items()}
```

Executor adapters still receive the original `IntentFrame.data` unchanged.

## Who authors the mapping (not the LLM)

The LLM does **not** emit `IntentFrame` and does **not** define field names.

Actual flow (see `jarvis_pa/jarvis/tools.py`):

1. Human writes tool functions + typed Pydantic action models with fixed fields.
2. LLM calls those tools and only **fills values** for those predefined params.
3. Tool layer builds `payload = action.model_dump()` and calls `actor.submit(payload)`.
4. **Actor** constructs and signs the `IntentFrame`; server bundles re-validate
   authoritatively regardless of any client-side pre-flight.

The mapping is therefore **human-authored at the tool/action layer** — same trust
tier as the tool schema itself, not model-generated metadata.

## Where the mapping should live (open design choice)

Two viable placements; same authorship, different wire/boot contract:

### Option A — Action bundle (original note)

Declare per-action, per-domain maps on `ActionBundle` (registered at boot):

```python
class CalendarActionBundle(ActionBundle):
    domain_field_map = {
        "DELETE_EVENT": {"deletion": {"path": "event_id"}},
    }
```

- Validated once at startup with other bundle config.
- Enforcement side reads from registry, not from request payload.
- Mapping is not repeated on every `IntentFrame`.

### Option B — Tool / actor submission path

Tool author attaches `domains_mapping` when building the payload passed to
`actor.submit`, for all domains expected in org policy for that action:

```python
class _CalendarAction(BaseModel):
    action: str
    event_id: str
    ...
    domains_mapping: dict[str, dict[str, str]] = {
        "deletion": {"path": "event_id"},
    }
```

- Lives next to the Pydantic model the tool author already maintains.
- Natural fit for integrations that do not ship an `ActionBundle`.
- Server must still treat the map as **input to validate** (project, then check) —
  same fail-closed contract as existing `_validate_against_registry` pre-flight;
  client convenience must not weaken authoritative server enforcement.

Both options solve the same ergonomics problem. Pick based on whether the
integration author owns an `ActionBundle` or only a tool/actor client.

## What does not change

- Domain schemas (`FinancialIntentData`, `DeletionIntentData`, …) stay canonical.
- `DomainBundle` stays action-agnostic; routing remains `register_domain_routes`.
- `intent_schema` on `DomainBundle` remains required.
- Unrelated keys in `IntentFrame.data` continue to be ignored (`extra="ignore"`).

## References

- `intentframe_bundle_sdk/domain.py` — `check_domain_intent_shape`, `intent_schema`
- `intentframe_native_kit/.../domains/deletion.py` — path-oriented limitation
- `intentframe_native_kit/.../domain_routes.py` — DELETE_EVENT/REMINDER not routed yet
- `jarvis_pa/jarvis/tools.py` — tool → Pydantic model → `actor.submit` pattern
