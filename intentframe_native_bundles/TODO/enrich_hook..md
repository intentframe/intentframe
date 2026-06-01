>revisit email intel again, fix constraint check, reconsider enrich hook again
# `enrich` hook — notes

**Full thread / discussion plan:** [cursor_2_jarvis_tools_and_email_reply.md](./cursor_2_jarvis_tools_and_email_reply.md)

## What `enrich` is today

- Only **email** overrides `enrich()`; it mutates `ctx.enriched_intent` (fill-if-absent on `data`, display `target`).
- Runner passes **submitted** `intent` to gates; **effective** intent (`enriched_intent or intent`) goes to AE/Guardian and (today) pipeline executor path.
- Enriched fields land in the **untrusted** prompt section — safe for suspicion bias, but wrong provenance (system facts mixed with actor claims).

## Direction (not decided in code yet)

- Prefer **`prepare_evidence` + provenance-tagged AI context** over completing partial intents in `enrich`.
- For EDI reply: executor derives recipients; bundle may resolve recipients for constraints / Guardian intent-limits, tagged per bundle↔adapter contract.
- Do **not** inject policy-only fields into `intent.data` when the executor ignores them.
