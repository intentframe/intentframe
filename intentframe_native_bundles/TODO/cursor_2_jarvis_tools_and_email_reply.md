# (2) Jarvis tools and email reply action updates
_Exported on 01/06/2026 at 9:23:50 GMT+5:30 from Cursor (3.5.38)_

---

**User**

lets work on this., we need to update jarvis tools as well as adapter..its llm responsibility to supply to..not enrich..and also lets remove enrich from bundle lifecycle.... -Agreed. If `to` is part of the policy-relevant contract for `REPLY_EMAIL`, the agent tool should submit it explicitly.

That gives the cleanest invariant:

- `IntentFrame.data` = what the actor/agent claims it wants to execute.
- Action bundle enrichment = evidence/context for AI and policy, not filling missing required fields.
- Executor adapter = either consumes submitted fields or derives internally from canonical fields, but not from bundle-enriched hidden mutations.

For `REPLY_EMAIL`, that means the Jarvis tool should likely require/submit something like:

```python
class _EmailReplyAction(BaseModel):
    action: str = "REPLY_EMAIL"
    rfc_message_id: str
    to: str
    body: str
    reply_all: bool = False
    reason: str
```

Then `enrich_intent()` should **not** add `data["to"]`. It can still add contextual fields like `email_from`, `email_subject`, `mailbox`, and display `target` for AI/audit. The email bundle’s policy check can compare submitted `to` against the resolved `email_from_address` when `reply_all=False`, if you want to prevent the agent from lying about the recipient.

---

**Cursor**

I'm currently in Ask mode, so I can't make the edits directly — but let me dig into the relevant files so I can give you a precise, actionable plan you can apply (or have me apply once you switch to Agent mode).

Let me check how the enriched context flows downstream (AI/policy) and what currently depends on the enrichment, so the plan accounts for impact.

Let me look at the SDK lifecycle to understand exactly what "remove enrich from bundle lifecycle" entails, and how enriched context reaches the AI/policy.

Let me verify the EDI email client's `reply()` signature, since whether the adapter can actually *send to* a submitted `to` matters for the security argument.

---

**User**

remove from bundle hooks..policy and ai layers see what actor submitted

its fine reaching executot "to"..it ll ignore

---

**Cursor**

Got it — the decision is now unambiguous: the email bundle stops mutating the intent during `enrich`, policy/AI see the raw actor submission, the LLM supplies `to`, and the executor can keep ignoring `to` (EDI derives the real recipient internally). Here's the precise, file-by-file plan to implement that. I'm in Ask mode so I'm not editing — switch to Agent mode and I'll apply it.

## What's actually happening today (for context)

For `REPLY_EMAIL`, `to` is a *synthetic* field:

1. `reply_email` tool submits no `to`.
2. `EmailActionBundle.enrich()` → `enrich_intent()` resolves the message from the local DB and **injects `data["to"] = email_from_address`** (plus `email_subject`, `email_from`, `mailbox`, and a display `target`).
3. `enforce_constraints._check()` validates that injected `to` against `allowed_recipients`.
4. The executor's `MailAdapter._reply()` **never reads `to`** — EDI's `actions.reply()` derives recipients internally from `rfc_message_id` (`to_addrs = [row["sender_email"]]`, plus to/cc if `reply_all`).

So `to` only ever fed the policy check, and it was bundle-injected (a "hidden mutation"). Your change makes it actor-supplied and removes the mutation.

## Edits required

### 1. `jarvis_pa/jarvis/tools.py` — LLM supplies `to`

`_EmailReplyAction` (lines 103-108) add `to`:

```python
class _EmailReplyAction(BaseModel):
    action: str = "REPLY_EMAIL"
    rfc_message_id: str
    to: str
    body: str
    reply_all: bool = False
    reason: str
```

`reply_email` tool (lines 457-464) add the param + pass-through, and update the docstring to tell the model to copy the original sender's exact address (mirror the `send_message` guidance about not reconstructing addresses):

```python
async def reply_email(ctx, rfc_message_id: str, to: str, body: str, reason: str, reply_all: bool = False) -> str:
    ...
    return await _submit(ctx, _EmailReplyAction(
        rfc_message_id=rfc_message_id, to=to, body=body, reply_all=reply_all, reason=reason,
    ))
```

### 2. `intentframe_native_bundles/actions/email/bundle.py` — drop the enrich hook

- Remove the `enrich()` method (lines 75-87).
- Remove the import `from ...email.enrich import EMAIL_MESSAGE_ACTIONS, enrich_intent` (line 14).
- The bundle no longer needs an `EmailClient`: `_get_client`, `_client`, `_client_lock`, `_closed` (lines 59-73) become dead. `aclose()` (lines 89-94) can drop the client teardown but must **keep** `self._contacts.invalidate()` since `enforce_constraints` still uses `PlatformContactsClient`.
- In `_check` (lines 145-165), the `_ENRICHER_RESOLVED` branch (lines 28, 156-160) now lies — `to` is no longer enricher-resolved. Remove `_ENRICHER_RESOLVED` and collapse the missing-recipient case to a single generic message:

```python
if not recipients:
    return False, "No recipient email address specified"
```

### 3. `intentframe_native_bundles/actions/email/enrich.py` — delete

After #2 it has no importers (`EMAIL_MESSAGE_ACTIONS` and `enrich_intent` are only used by the bundle). The file can be removed entirely. The default `ActionBundle.enrich()` is already a no-op `continue_`, so the runner's enrich phase still runs harmlessly and `record_enrichment` still fires.

### 4. `intentframe_executor_pack_macos/adapters/mail.py` — no behavior change

`_reply()` already ignores `to`; per your call we leave that as-is. Worth a one-line comment in `_reply` noting `to` is accepted-but-ignored (recipient is derived from `rfc_message_id`) so future readers don't "fix" it. The module docstring (lines 9-12) listing REPLY under message-actions stays correct.

## Tests / scripts that will break and need updating

- `tests/native_bundles/test_email_bundle_lifecycle.py` — the whole file exercises `bundle.enrich()` with a mocked `EmailClient` (client sharing, aclose-after-enrich, enrich-after-aclose-raises). With the hook gone these tests are obsolete; they should be deleted or rewritten to assert the bundle no longer mutates the intent and that `aclose()` still invalidates contacts.
- `tests/test_email_intent_flow.py` — the manual integration script patches `email_enrich_module.enrich_intent` and prints "to (enriched reply recipient)" (lines 182-211, 264-265). It needs to drop the enrichment patch and put `to` directly in `jarvis_payload`.
- Worth grepping `tests/test_enrichment_ledger.py` and the parity fixtures (`deterministic_gate_matrix_*`, etc.) — those track per-bundle hooks and may have a recorded expectation that the email bundle overrides `enrich`.

## One consequence to be aware of (not a blocker)

Because the adapter ignores `to` and EDI always replies to the original sender, the recipient constraint check for `REPLY_EMAIL` now validates an **agent-asserted** value rather than a resolved one. An agent could submit an allowed `to` while EDI still replies to the real original sender. That's low-risk here (a reply only ever goes back to someone who already emailed the user), and `SEND_EMAIL`/`FORWARD_EMAIL` still enforce a real, executor-consumed `to`. If you later want the reply recipient to be genuinely enforced, you'd have to thread `to` into EDI's `reply()` signature — but that's explicitly out of scope per your "it'll ignore" call.

Want me to switch to Agent mode and apply all of this (including pruning/rewriting the two affected tests)?

---

**User**

should we do this today? I mean a reply can  contain one or multiple receipeints and same for send email....is current tol calls are not supporting that? why we do have reply all..and what kind of enrichment email enrichment is doing ? how much that is relevant? 

---

**Cursor**

Good questions — let me trace how recipients and `reply_all` work end-to-end today, and what enrichment actually adds, before recommending whether to ship this today.


Short answer: **don’t do the full “remove enrichment from bundle hooks” today** unless you’re OK with AE/Guardian seeing only what the agent submits (mostly opaque `rfc_message_id`s). The **`to` invariant change is fine to do today** — it’s small and mostly fixes a lie in the policy layer. Multi-recipient support is a **separate, pre-existing gap**, not something this refactor solves or breaks.

---

## Current tool support for recipients

| Action | Jarvis tool | Executor | Multiple recipients? |
|--------|-------------|----------|----------------------|
| `SEND_EMAIL` | `to: str` | accepts `str` or `list`, coerces str → `[str]` | **Partially** — adapter can take a list, but the tool schema is a single string. No `cc`. |
| `FORWARD_EMAIL` | `to: str` | same as send | Same |
| `REPLY_EMAIL` | no `to`; `reply_all: bool` | ignores `to`; derives recipients from DB | **No explicit list** — see below |

So yes: **current tool calls do not properly model “one or many recipients”** for send/forward. They’re typed as one string. The adapter happens to accept a list if something bypasses the tool layer, but Jarvis never exposes that.

Policy `_check()` does use regex to extract **all** emails from a string, so `"alice@x.com, bob@y.com"` would pass constraint checks — but that’s accidental, not a designed API.

---

## Why `reply_all` exists (and why it’s different from `to`)

For replies, recipients aren’t chosen by the agent — they’re **derived from the original message** in EDI:

```196:204:external_data_ingestion/external_data_ingestion/email/actions.py
    to_addrs = [row["sender_email"]]
    cc_addrs: list[str] = []
    if reply_all:
        for r in json.loads(row["to_recipients"] or "[]"):
            if r.get("email") and r["email"] != account.email:
                to_addrs.append(r["email"])
        for r in json.loads(row["cc_recipients"] or "[]"):
            if r.get("email") and r["email"] != account.email:
                cc_addrs.append(r["email"])
```

- `reply_all=False` → reply to original sender only  
- `reply_all=True` → sender + original To + original Cc (minus your own account)

That’s the right abstraction: the agent shouldn’t enumerate reply-all recipients; it toggles a flag and EDI resolves the set from headers. **`reply_all` is not a substitute for a multi-recipient `to` field** — it’s a different mechanism entirely.

The adapter never reads `params["to"]` for replies today:

```317:327:intentframe_executor_pack_macos/adapters/mail.py
    async def _reply(client, message_id: str, params: dict) -> ExecutionResult:
        ...
        result = await client.reply(
            message_id,
            body=body,
            html=params.get("html_body", ""),
            reply_all=params.get("reply_all", False),
        )
```

So requiring `to` on the tool is **for policy/audit honesty**, not for routing.

---

## What email enrichment actually does

For message-based actions (`GET`, `REPLY`, `FORWARD`, `MARK_READ`, `MOVE`, `DELETE`, `DOWNLOAD_ATTACHMENT`), `enrich_intent()`:

1. **Looks up the message** in the local EDI DB (headers only).
2. **Adds context into `intent.data`** if missing:
   - `email_subject`, `email_from`, `email_from_address`, `account_email`, `mailbox`, `email_date`, `has_attachments`
3. **Injects `data["to"]`** for `REPLY_EMAIL` only (from `email_from_address`) — the part you want to remove.
4. **Rewrites `target`** for display, e.g. `Reply to "Invoice Q3" from alice@co.com` instead of `<msg-id@...>`.

After enrichment, the pipeline swaps in `effective_intent` before AE/Guardian:

```528:531:intentframe_server/pipeline.py
        intent = (
            det_result.bundle_context.effective_intent
            if det_result.bundle_context is not None
            else intent
        )
```

So AE/Guardian today see enriched `target` + enriched `data` (subject, sender, injected `to`, etc.) in their untrusted prompt sections.

### How relevant is each piece?

| Enrichment output | Relevance | Notes |
|-------------------|-----------|-------|
| Injected `to` for reply | **Low / misleading** | Executor ignores it. Policy thinks it validated the real recipient, but EDI decides independently. Hidden mutation. |
| Display `target` | **Moderate** | Helps humans and AI read audit/prompts (“reply to Invoice Q3” vs raw ID). |
| `email_subject`, `email_from`, etc. in `data` | **Moderate** | Gives AE/Guardian context when the agent only submitted `rfc_message_id` + `body`. Without it, prompts are sparser. |
| DB lookup validating message exists | **Low for policy** | Constraint check already fails if enrichment can’t resolve `to`; with actor-supplied `to`, bad IDs fail at executor instead. |

---

## Should you do this today?

Split it into two decisions:

### A. Require actor-supplied `to` for `REPLY_EMAIL` — **yes, reasonable today**

- Small change: Jarvis tool + model, remove lines 94–97 in `enrich.py`, simplify `_ENRICHER_RESOLVED` error in `bundle.py`.
- Executor keeps ignoring `to` — you already said that’s fine.
- For `reply_all=True`, `to` is awkward: policy would check one address while EDI sends to many. Options:
  - Require `to` = original sender only (document that `reply_all` expands beyond that at execution), or
  - Skip recipient constraint check when `reply_all=True` and validate each resolved address in `enforce_constraints` via a DB lookup (more work).

Given executor ignores `to`, the pragmatic move for today is: **require `to` = sender address from `get_email`/`read_email`, use `reply_all` as today, accept that policy only loosely covers reply-all** until you wire real recipient validation.

### B. Remove enrichment from bundle hooks entirely — **probably not today**, unless you explicitly want sparser AI prompts

If you drop enrichment completely, AE/Guardian for a reply see roughly:

```
Target: (empty or message id)
Data: rfc_message_id, body, reply_all, reason
```

No subject, no sender name, no human-readable target — unless the agent fetched the email first and you start requiring those fields on the tool (which pushes burden to the LLM).

That matches your invariant (“policy and AI see what actor submitted”) but **costs observability** for message actions.

**Middle path (best of both):**
- Remove **`to` injection** and the enrich hook’s **policy mutations**.
- Keep optional **audit-only** enrichment elsewhere (ledger/display) if you still want pretty targets — but that contradicts strict “AI sees submitted only” unless you put enriched context in trusted external context, not `intent.data`.

---

## Multi-recipient as a follow-up (not blocked by today’s work)

If you want real multi-recipient support later:

- **Send / forward:** change tools to `to: list[str]` (or `str | list[str]`), add optional `cc`, update Jarvis docstrings.
- **Reply:** keep `reply_all`; don’t ask the LLM to list reply-all recipients.
- **Policy:** `_extract_emails` already handles multiple addresses in one string; a `list[str]` type would be cleaner.

That’s independent of the enrichment removal debate.

---

## Recommendation

| Change | Do today? |
|--------|-----------|
| Jarvis `reply_email` requires `to` | Yes |
| Remove `to` injection from `enrich_intent` | Yes |
| Remove entire email `enrich()` hook | Only if you accept thinner AE/Guardian context for message actions |
| Multi-recipient send/forward/cc | Separate task |
| Make policy validate reply-all recipients against DB | Later, if reply-all + constraints matter |

**Today:** do the **`to` honesty fix** (tool + stop injecting `to`). **Defer** full enrichment removal until you decide whether AE/Guardian should see resolved subject/sender or the agent must `get_email` first and submit that context explicitly.

If you want, I can implement just the narrow `to` fix (Jarvis + remove injection + simplify constraint error) and leave the enrich hook in place for metadata/target — or go all-in on removing the hook. Which scope do you prefer?

---

**User**

does enriched intent check by gates? its kind of author Decision to enrich..so maybe constraints should check all recepeient in reply to..because it currently onnly fetched to primary sender..but in future implementation we should populatef ull reply all list..which should cover to also...how does dg checks reply eail today if intent has no to?

---

**Cursor**

Let me trace exactly which intent the gates/constraints receive in the runner, so I can answer precisely about enriched-vs-submitted.

The gate-vs-enriched-intent question hinges on exactly what the runner passes to each hook. Let me read the full run method from the top.

This is the crux. Let me confirm whether any bundle reads the enriched intent inside `enforce_constraints`, and whether there's test coverage for a constrained reply.

Great question — this exposes a subtle and important detail. I traced the runner and pipeline; here's exactly how it works today.

## 1. Do the gates check the enriched intent? **No.**

The deterministic runner passes the **original submitted `intent`** to *every* hook. It never reassigns `intent` to the enriched copy:

```151:184:intentframe_bundle_sdk/runner.py
        # ── enrich ─────────────────────────────────────────────────────
        try:
            enriched = await _call_hook(
                bundle.enrich, intent, action_permission, ctx,
                ...
            )
        ...
        ctx = enriched.context
        record_enrichment(ctx, bundle_id=bundle.bundle_id)

        # ── enforce_constraints ────────────────────────────────────────
        if action_permission.constraints is not None:
            ...
                pol = await _call_hook(
                    bundle.enforce_constraints, intent, frozen, ctx,
```

`enrich()` writes only to `ctx.enriched_intent`. Then `enforce_constraints`, domain enforce, `structural_gates`, `allow_gates`, and `build_ai_context` are all called with that same submitted `intent` param. So **the deterministic gates evaluate what the actor submitted**, not the enriched frame.

The enriched intent is consumed in exactly two places, both *after* the deterministic layer:

- The pipeline swaps it in before AE/Guardian:

```528:532:intentframe_server/pipeline.py
        intent = (
            det_result.bundle_context.effective_intent
            if det_result.bundle_context is not None
            else intent
        )
```

- The audit ledger (`record_enrichment` → `enrichment_changed`) records the diff for observability.

So to your framing: yes, **enrichment is purely the bundle author's decision**, and its product is visible to the *AI layer and audit*, not to the *gates*.

## 2. How does the DG check `REPLY_EMAIL` today when there's no `to`?

Two paths, depending on whether constraints are configured:

**No constraints (the common case, e.g. `ActionPermission(safe=False)`):** `enforce_constraints` is skipped entirely (the `if action_permission.constraints is not None` guard). `_check` never runs, so the missing `to` is irrelevant. The reply falls through to UNDECIDED → AE/Guardian. That's exactly what the integration test exercises:

```42:46:tests/test_runtime_email_lifecycle_integration.py
def _reply_user_context() -> UserContext:
    return UserContext(
        user_id="test",
        allowed_actions={"REPLY_EMAIL": ActionPermission(safe=False)},
    )
```

**Constraints configured:** `enforce_constraints` runs `_check(intent, ...)` against the **submitted** intent:

```151:165:intentframe_native_bundles/actions/email/bundle.py
        data = intent.data or {}
        action = intent.action.value
        raw_to = str(data.get("to", "")).strip()
        recipients = self._extract_emails(raw_to) if raw_to else []
        if not recipients:
            if action in _ENRICHER_RESOLVED:
                return False, (
                    "Could not determine reply recipient — email enrichment "
                    "likely failed (bad or hallucinated rfc_message_id?)"
                )
            return False, "No recipient email address specified"
```

Here's the catch you're sensing: **the `to` that `enrich_intent` injects lives in `ctx.enriched_intent`, but `_check` reads the `intent` param (submitted), which has no `to`.** So a *constrained* `REPLY_EMAIL` hits the `_ENRICHER_RESOLVED` branch and **BLOCKs** — even when enrichment succeeded. The error message ("enrichment likely failed") is misleading; the real reason is that the gate reads the submitted frame, not the enriched one. The injected `to` only ever reached AE/Guardian, never the constraint check.

That's why your earlier "the executor ignores `to` anyway" observation is even more true than it looked: today `to` injection affects *nothing* deterministic — not the executor (derives recipients in EDI) and not the constraint gate (reads submitted intent).

## 3. Your reply-all recipient point — correct, and it needs an architectural decision

You're right that constraints *should* check all reply-all recipients, and that today it only ever conceptually targets the primary sender. The full recipient set (sender + original To + Cc, minus self) is resolved **deep inside EDI**, not surfaced to the bundle:

```196:204:external_data_ingestion/external_data_ingestion/email/actions.py
    to_addrs = [row["sender_email"]]
    cc_addrs: list[str] = []
    if reply_all:
        for r in json.loads(row["to_recipients"] or "[]"):
            if r.get("email") and r["email"] != account.email:
                to_addrs.append(r["email"])
        for r in json.loads(row["cc_recipients"] or "[]"):
            if r.get("email") and r["email"] != account.email:
                cc_addrs.append(r["email"])
```

For the constraint gate to validate the real reply-all set, two things must change:

1. **Someone must resolve the full recipient set before/at constraint time** — either `enrich` resolves sender+To+Cc (not just the single sender it does now), or `enforce_constraints` does its own DB lookup.
2. **The gate must actually read that resolved set.** Today it can't, because the runner hands `enforce_constraints` the submitted intent. You'd need either:
   - the runner to pass `ctx.effective_intent` to `enforce_constraints` (a runner-wide semantic change affecting all bundles), or
   - the email bundle's `enforce_constraints` to read `ctx.effective_intent` instead of the `intent` param (a local fix, no SDK change).

The local fix (option b) is the smaller, safer move and is the missing link that would make your future "populate full reply-all list, which covers `to`" plan actually enforce.

## Summary

| Question | Answer |
|----------|--------|
| Do gates see enriched intent? | No — runner passes submitted intent to all hooks; enriched intent only reaches AE/Guardian + audit. |
| How is reply checked with no `to`? | No constraints → check skipped, flows to AI. Constraints → `_check` reads submitted intent (no `to`) → blocks via `_ENRICHER_RESOLVED`. The injected `to` is never seen by the gate. |
| Reply-all recipient validation | Not possible today: full set is resolved inside EDI; gate reads submitted intent. Needs (a) resolving the full set at enrich/constraint time, and (b) `enforce_constraints` reading `effective_intent`. |

So, two design choices fall out of this for your future direction:
- **Where to resolve the full reply-all recipient set** (enrich vs. enforce_constraints DB lookup).
- **Whether the gate reads submitted or effective intent** — and if you keep your "policy sees what the actor submitted" invariant, then the recipients must be *actor-submitted* (LLM supplies them), not enrichment-derived, for the constraint check to mean anything.

Want me to map out the concrete change for option (b) — having the email `enforce_constraints` resolve and validate the full reply-all recipient set against `allowed_recipients` — so you can decide between "LLM submits recipients" vs "bundle resolves them"?

---

**User**

this whole machinry around a single action family seems off....is it needed in real life?

---

**Cursor**

Let me check one thing that reframes the question: how much of this is *email-specific* vs a shared substrate every action family rides on.

Confirmed something useful: **email is the only action family that overrides `enrich()`.** Every other bundle (files, terminal, host_files, calendar, message, api, browser) inherits the no-op. So let me separate what's shared substrate from what's genuinely email-specific, then give you a real-world verdict.

## Reframe: most of the "machinery" isn't per-family

The lifecycle (`prepare_evidence → enrich → enforce_constraints → domain → structural_gates → allow_gates → build_ai_context`) is a **shared substrate** that ~8 families ride on. `enforce_constraints`/`prepare_evidence`/`build_ai_context` show up across terminal (3 hooks), files (3), host_files (3), calendar, message, api, browser. The cost is amortized — email isn't carrying a bespoke framework, it's opting into a few hooks.

So the question isn't "is this whole pipeline needed for email" — it's "are email's *specific* opt-ins (the `enrich` hook + recipient constraints) worth it?"

## The genuinely email-specific pieces, judged against real life

| Piece | Real-world value | Verdict |
|-------|------------------|---------|
| **`enforce_constraints` / `allowed_recipients`** | "Don't let the agent email outside my company / approved list." This is a real, frequently-requested guardrail for an autonomous agent with send capability. | **Earns its keep.** This is the one piece with clear real-world demand. |
| **`enrich()` → display `target`** ("Reply to 'Invoice Q3' from alice@…") | Makes audit logs and approval prompts human-readable instead of `<CALyg3Ru…@mail.gmail.com>`. Genuinely helps a human approving/reviewing. | **Marginal but cheap.** Nice for UX/audit; not security-critical. |
| **`enrich()` → inject `data["to"]`** | We established it reaches neither the executor (EDI derives recipients) nor the gate (reads submitted intent). | **Dead weight.** Pure liability — looks like a control, controls nothing. |
| **`enrich()` → subject/sender/mailbox into `data`** | Gives AE/Guardian context when the agent only submitted an opaque message-id. | **Questionable.** Only matters if you trust the AI layer to reason over it — and it muddies your "AI sees what the actor submitted" invariant. |
| **`_ENRICHER_RESOLVED` block branch** | Designed to catch "enrichment failed," but actually fires whenever a constrained reply has no submitted `to` — i.e., it blames enrichment for a gate/submitted-intent mismatch. | **Actively misleading.** Should be removed regardless of direction. |
| **`recipient_sources` (dynamic contact-group ACLs)** | Resolve "allowed = my contacts group" at runtime via `PlatformContactsClient`. Powerful, but: do you actually have users configuring contact-group-scoped send policies today? | **Speculative.** Classic YAGNI candidate unless a real user wants it. |

## So — is it needed in real life?

**The honest split:**

- **Yes, real:** recipient allow-listing for send/reply/forward. An agent that can send email to anyone is a phishing/exfil vector; constraining recipients is a legitimate, commonly-wanted control. That alone justifies the email bundle having an `enforce_constraints`.

- **No, over-built for now:** the `enrich()` hook. Its only defensible output is the display `target`. The `to` injection is inert, the metadata injection conflicts with the invariant you said you want, and the `_ENRICHER_RESOLVED` branch is a misfire. Email being the *sole* user of `enrich()` is a strong smell that this hook was built speculatively.

- **Speculative:** `recipient_sources`. Keep the schema if you've promised it, but don't let it justify the rest.

## What a leaner, real-world design looks like

1. **Drop `enrich()` entirely** (your original instinct). LLM submits `to` (and recipients explicitly). Policy + AI + executor all see the same submitted frame — clean invariant, no hidden mutations.
2. **Keep `enforce_constraints` with `allowed_recipients`** — this is the part that maps to a real threat.
3. **Make the recipient set actor-submitted**, so the gate validates something real. For reply-all, that means the LLM lists the recipients it intends (it already has them from `get_email`/`read_email`), rather than enrichment guessing them.
4. **Move display-target prettification** out of the security path — compute it for audit/UI rendering from the result, not by mutating the intent pre-gate.
5. **Delete `_ENRICHER_RESOLVED`** and its branch.

That collapses the email-specific surface to: one constraint check + a Pydantic constraints model. Everything else is the shared substrate you're already paying for across every family.

**Bottom line:** the *pipeline* is justified (it's shared and the recipient guardrail is real). The *email enrichment hook* specifically is the part that feels off because it largely is — it's the only per-family enrichment in the codebase, and most of what it produces is either inert or fights the invariant you actually want. Cutting it is the simplification your gut is pointing at.

Want me to sketch the concrete "no-enrich, actor-submits-recipients, constraint-validates-real-recipients" version of the email bundle + Jarvis tool so you can see the full reduced surface before deciding?

---

**User**

but there is also one another concern....something u only need for policy layer is not meant not meant to be burdened on actors or executors in general...if i can write an adapter which completes its task with just few params...its the job of policy action bundle author ? can we generalise it?

---

**Cursor**

This is a sharp architectural point, and the codebase actually already answers it in two other families. Let me confirm the existing pattern before I generalize.

Yes — and the strong version of your point is already implemented in this codebase. Two families (`files`, `terminal`) do exactly what you're describing; email is the one that breaks the pattern. So this isn't something to invent — it's something to *apply consistently*.

## The principle, named: three data planes

| Plane | Owner | Consumed by | Example |
|-------|-------|-------------|---------|
| **Intent data** (`IntentFrame.data`) | Actor | Executor (+ gate validates it) | `path`, `command`, `body`, `rfc_message_id` |
| **Evidence** (`ctx.evidence`) | Bundle author | Gates + AI + audit. **Never** the executor; **never** required from the actor | `file_intel`, `command_intel`, resolved recipients |
| **Constraints** (`ActionPermission.constraints`) | Operator/policy | Gate | `allowed_paths`, `allowed_recipients` |

Your concern — "policy-only data shouldn't burden actors or executors" — *is* the reason the evidence plane exists.

## The codebase already generalizes it

`files` derives policy/AI facts into a **private channel** in `prepare_evidence`, not into `intent.data`:

```46:54:intentframe_native_bundles/actions/files/bundle.py
    async def prepare_evidence(
        self,
        intent: IntentFrame,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        ctx.evidence[FILE_INTEL_KEY] = run_files_pre_pipeline(intent, verbose=verbose)
        return BundlePhaseOutcome.continue_(ctx)
```

…and reads it back only where governance/AI needs it:

```111:117:intentframe_native_bundles/actions/files/bundle.py
        file_intel = ctx.evidence.get(FILE_INTEL_KEY)
        if file_intel is not None and not isinstance(file_intel, FileIntel):
            file_intel = None
        system, label = select_write_file_ae_system_instructions()
        return BundleAIContext(
            ae_system_instructions=system,
            ae_external_context=render_file_external_context(file_intel),
            ae_prompt_label=label,
        )
```

`terminal` does the same with `command_intel`/signals — written in `prepare_evidence` (`ctx.evidence[COMMAND_INTEL_KEY] = …`), read by `allow_gates` and `build_ai_context`. The actor never supplies `command_intel`; the executor never receives it. It's purely policy/AI fuel.

Crucially, note what `files.enforce_constraints` validates:

```72:80:intentframe_native_bundles/actions/files/bundle.py
        # ``data["path"]`` is the executed resource (same field the adapter acts
        # on). ``intent.target`` is display/audit only.
        path = (intent.data or {}).get("path", "")
        if not self._path_matches(path, constraints.allowed_paths):
```

It checks **`data["path"]` — the field the executor actually acts on.** Policy validates the *real functional field*, and pulls *derived* context from evidence. That's the whole discipline in one bundle.

## The decision rule (the generalization)

For any field, ask: **does the executor need it to perform the action?**

- **Yes → `IntentFrame.data`**, actor supplies it, executor consumes it, and the gate validates *that same field*. (`SEND_EMAIL.to`, `FILE.path`, `RUN_COMMAND.command`.) Here the field is *both* functional and policy-relevant, so there's no burden — the actor was always going to supply it.
- **No, but policy/AI needs it and it's derivable → `ctx.evidence`**, the bundle author resolves it, gate/AI read it, executor and actor are untouched. (`file_intel`, `command_intel`, **reply recipients**.)

This dissolves the false dilemma we were stuck in earlier. We were choosing between:
- "make the actor submit `to`" → burdens the actor with a policy-only field, and
- "enrich `to` into `intent.data`" → burdens the executor (carries a field it ignores) and pollutes the actor's contract.

The correct third option, per the existing pattern, is: **resolve recipients into `ctx.evidence` in `prepare_evidence`, and have `enforce_constraints` read evidence.** Neither actor nor executor is touched.

## Why email is the odd one out

`REPLY_EMAIL` is the textbook case for the evidence plane: the executor genuinely does *not* need `to` (EDI derives sender + To + Cc from the stored message), so `to` is **policy-only**. Yet email today:

1. Injects `to` into `intent.data` via `enrich()` (wrong plane — that's the executor's channel), and
2. The gate then reads the *submitted* `intent`, so it doesn't even see the injected value (the bug we found).

If email followed the `files`/`terminal` pattern instead:

- `prepare_evidence` resolves the real recipient set (sender for reply, sender+To+Cc for reply-all) into `ctx.evidence["resolved_recipients"]`.
- `enforce_constraints` reads `ctx.evidence["resolved_recipients"]` and checks each against `allowed_recipients`.
- The Jarvis tool stays minimal (`rfc_message_id`, `body`, `reply_all`) — no policy-only `to` foisted on the LLM.
- The executor stays minimal — no ignored field.
- `intent.data` remains a faithful statement of what the actor asked for.

That simultaneously honors your invariant ("policy and executor are decoupled"), fixes the reply-all recipient gap, and deletes the misleading `to` injection — *without* the actor lying about recipients it can't actually control.

## One caveat on "generalize it"

The evidence plane is the generalization, but there's a deliberate boundary worth keeping: **a gate must validate the field the executor will actually act on, not a parallel derived value, whenever the executor consumes that field.** Otherwise you get TOCTOU-style divergence (policy validates X, executor does Y). Email reply is safe to validate from evidence *only because* the executor independently re-derives the same recipients from the same message — evidence and execution share one source of truth (the message in the DB). For `SEND_EMAIL`, where the executor sends to whatever `to` it's given, the gate must validate the *submitted* `to`, not an evidence copy. So the rule is:

> Validate from evidence only when the executor derives the same fact from the same source; otherwise validate the actor-submitted field the executor will use.

Want me to write up the concrete reshaped email bundle (recipients resolved in `prepare_evidence` → `enforce_constraints` reads evidence, `enrich` deleted, Jarvis tool unchanged) as a plan you can hand to Agent mode?

---

**User**

what evidemce ai layers use in their llm prompt?

---

**Cursor**

I'll trace how `ctx.evidence` flows into AE and Guardian prompt construction.


Short answer: **`ctx.evidence` never goes straight into an LLM prompt.** Bundles read evidence in `build_ai_context`, render it into `BundleAIContext`, and only those rendered fields reach the AI layer. Email today mostly bypasses that path and uses `enrich()` → `enriched_intent` instead.

## The pipeline (evidence → prompt)

```
prepare_evidence  →  ctx.evidence          (raw, structured — gates + build_ai_context only)
enrich            →  ctx.enriched_intent     (mutated IntentFrame — separate path)
        ↓ UNDECIDED only
build_ai_context  →  BundleAIContext       (rendered strings for AE)
runner            →  constraint_context    (describe_constraints — Guardian only)
        ↓
Analysis Engine   →  system prompt + request prompt
Guardian          →  system prompt + request prompt (different material)
```

`ctx.evidence` is an internal bundle workspace. AE and Guardian never read `ctx.evidence` directly.

---

## What actually lands in LLM prompts

### Analysis Engine

From `BundleAIContext`:

| Field | In prompt? | Where |
|-------|------------|--------|
| `ae_system_instructions` | Yes | System prompt (replaces default AE instructions for write/run-command) |
| `ae_external_context` | Yes | Appended to trusted **Context** section |
| `ae_intent_signals` | **No** (not in prompt text) | Copied onto `AnalysisReport.intent_signals` for audit/metadata |
| `constraint_context` | No | Guardian only |

```298:325:intentframe_components/analysis/engine.py
        context_lines = [
            f"Action: {intent.action.value}",
            ...
        ]
        if bundle_ai_context.ae_external_context:
            context_lines.append(bundle_ai_context.ae_external_context)
        ...
        untrusted = {"Target": intent.target, "Reason": intent.reason}
        data_section = format_intent_data(intent.data)
```

**Trusted:** action, agent, task, plus bundle external context.  
**Untrusted:** `target`, `reason`, `intent.data` — from **`effective_intent`** (submitted + enrichment if any).

### Guardian

| Field | In prompt? |
|-------|------------|
| `guardian_system_instructions` | System prompt (no bundle sets this today) |
| `guardian_external_context` | **Defined but unused** — nothing reads it in `guardian/engine.py` |
| `constraint_context` | Yes — in **Policy Context → Constraints** |
| `ae_external_context` | **Not used** by Guardian |

Guardian gets the full **Analysis Report** (trusted), policy context, intent limits, and the same untrusted intent fields as AE. It does **not** get terminal/file evidence text unless AE’s analysis somehow reflects it.

---

## Which bundles use evidence in AI prompts today

Only **three** families override `build_ai_context` and read `ctx.evidence`:

### 1. Terminal (`RUN_COMMAND`)

**Evidence:** `command_intel`, `terminal_command_signals` (from `prepare_evidence`)

**In AE prompt:**
- Custom system prompt (`critical_run_command`)
- External context: `TERMINAL COMMAND — STRUCTURAL SIGNALS:` with each shield finding

**Not in AE prompt:** `command_intel` capabilities directly — those are used by **gates** (`enforce_constraints`, `allow_gates`), not rendered to the LLM.

**Side channel:** `ae_intent_signals` → stored on `AnalysisReport`, not in prompt body.

### 2. Files (`WRITE_FILE`)

**Evidence:** `file_intel` (language, binary, size, code-intel findings, destination probes, path category)

**In AE prompt:**
- Custom system prompt (`critical_write_file`)
- External context: `WRITE_FILE — PAYLOAD SIGNALS`, `DESTINATION SIGNALS`, `PATH SEMANTICS`

### 3. Host files (`WRITE_HOST_FILE`)

Same pattern as files — reuses `file_intel` + `render_file_external_context`.

### Everything else (including email)

Default `build_ai_context()` → empty `BundleAIContext`. **No evidence → no bundle-specific AE context.**

---

## Email: enrichment is *not* the evidence pattern

Email is the outlier. It does **not** use `prepare_evidence` or `build_ai_context`. It uses **`enrich()`**, which writes **`ctx.enriched_intent`** (mutated `IntentFrame`), not `ctx.evidence`.

That enriched intent is what AE/Guardian see in the **untrusted** section:

- Pretty `target` (`Reply to "Subject" from sender@…`)
- Extra `data` keys: `email_subject`, `email_from`, `email_from_address`, injected `to`, etc.

So for email, “extra context for AI” today comes from **intent mutation**, not from the evidence → `BundleAIContext` path files/terminal use.

---

## Summary table

| Source | Used by gates? | Used in AE prompt? | Used in Guardian prompt? |
|--------|----------------|--------------------|---------------------------|
| `ctx.evidence` (raw) | Yes (terminal constraints, etc.) | No — only via `build_ai_context` | No |
| `BundleAIContext.ae_external_context` | — | Yes (terminal, files, host_files) | No |
| `BundleAIContext.constraint_context` | — | No | Yes |
| `BundleAIContext.ae_intent_signals` | — | No (on report only) | No |
| `enriched_intent` (email) | No (gates read submitted intent) | Yes — untrusted `target`/`data` | Yes — same |
| Submitted `intent.data` | Yes (when gate checks it) | Yes — untrusted | Yes — untrusted |

---

## Takeaway for your architecture question

The generalized pattern you want already exists for terminal/files:

> **Evidence fuels policy gates and/or trusted AE context strings — without touching actor params or executor params.**

Email should follow that (`prepare_evidence` → resolved recipients in evidence; `enforce_constraints` reads evidence; optional `build_ai_context` for display metadata in **trusted** external context), instead of mutating `intent.data` via `enrich()`.

Right now, **the only evidence-derived text in LLM prompts is terminal structural signals and file write intel** — nothing from email, calendar, message, etc.

---

**User**

so we shohuld follow intel pattern and create email intel?

---

**Cursor**

Mostly yes — but with an important refinement, because email isn't quite the same *kind* of thing as `file_intel`/`command_intel`. Don't cargo-cult the full machinery; copy the *plane*, right-size the *mechanism*.

## What "intel" actually is vs. what email needs

The existing intel objects share a defining trait:

- **`file_intel`** = deterministic static analysis of the **payload the actor already submitted** (the file content/path). No external I/O.
- **`command_intel`** = deterministic static analysis of the **command string** the actor submitted. No external I/O.

They're *pure computations over actor-supplied data* that produce facts for gates + AI.

**Email "intel" is a different animal:** resolving an opaque `rfc_message_id` into sender/subject/recipients is an **external DB lookup**, not analysis of a submitted payload. That's fine for the evidence plane (`prepare_evidence` is explicitly allowed to do I/O under a deadline) — but it changes the cost/benefit, so the mechanism should differ.

## The real question: what consumes it?

Intel earns a full `*Intel` object + `build_ai_context` renderer only when **both** gates and the AI layer need it. Map email:

| Consumer | Needs resolved email facts? | Notes |
|----------|------------------------------|-------|
| **`enforce_constraints`** (recipient allow-list) | **Yes** — needs resolved recipients (sender for reply, sender+To+Cc for reply-all) | Only runs **when constraints are configured** |
| **AE/Guardian prompt** | **Optional** — subject/sender as *trusted* context is marginal nice-to-have | Today it's smuggled via untrusted `intent.data`, which is worse |
| **Executor** | **No** — EDI re-derives recipients from the message | Confirmed earlier |
| **Actor** | **No** | |

So the **only hard requirement** is recipient resolution for the constraint gate. Everything else is optional polish.

## Why a full `EmailIntel` + `prepare_evidence` is probably over-built

`files` resolves intel in `prepare_evidence`, which runs on **every** file action, because file_intel feeds both the always-on `build_ai_context` and `enforce_constraints`. That's justified there.

For email, if the only mandatory consumer is the recipient gate, then resolving in `prepare_evidence` means **a DB lookup on every reply/forward even when no recipient constraints are configured** — pure waste in the common unconstrained case.

And there's already a precedent in the email bundle for the leaner approach: dynamic recipient sources (contacts) are resolved **inside `enforce_constraints`, only when constraints exist**:

```113:118:intentframe_native_bundles/actions/email/bundle.py
        # Resolve dynamic recipient sources here — the natural place since
        # "is this recipient allowed?" is a constraint check, not enrichment.
        allowed = list(constraints.allowed_recipients)
        if intent.action.value in _SEND_LIKE_ACTIONS and constraints.recipient_sources:
            resolved = await self._contacts.resolve_sources(constraints.recipient_sources)
            allowed = list(set(allowed) | set(resolved))
```

The message-recipient resolution belongs in exactly the same place, for the same reason.

## My recommendation: tiered

**Tier 1 (do this — the actual fix):** resolve the real recipient set *inside `enforce_constraints`*, only when constraints are present, and validate it. No `intent.data` mutation, no executor/actor burden, no DB hit when unconstrained.

```python
# inside enforce_constraints, after building `allowed`
if intent.action.value == REPLY_EMAIL and reply_all:
    recipients = await self._resolve_reply_recipients(message_id, reply_all=True)  # sender + To + Cc
elif intent.action.value == REPLY_EMAIL:
    recipients = await self._resolve_reply_recipients(message_id, reply_all=False) # [sender]
else:
    recipients = self._extract_emails(data.get("to", ""))  # send/forward: actor-supplied
# then check each against `allowed`
```

This fixes the reply-all gap *and* the "gate never saw the injected `to`" bug, and kills the misleading `_ENRICHER_RESOLVED` branch.

**Tier 2 (only if you want richer AI prompts):** add a proper `prepare_evidence` + `EmailIntel` + `build_ai_context` that puts subject/sender into AE's **trusted external context** (like terminal/files do) — *not* into untrusted `intent.data`. Do this only if you've decided AE/Guardian genuinely benefit from email metadata. Given email actions are mostly low-risk and the AI already gets `body`, this is lower priority.

**Tier 3 (delete regardless):** the `enrich()` hook, the `to` injection, `EMAIL_MESSAGE_ACTIONS` import in the bundle, and `_ENRICHER_RESOLVED`. The pretty `target` can be computed for audit/UI from the result rather than by pre-gate mutation.

## So: "create email intel?"

- **Follow the evidence *plane*: yes, unequivocally.** Stop mutating `intent.data`.
- **Build a full `EmailIntel` object like `FileIntel`: only if you go Tier 2.** For Tier 1, you don't need a typed intel object or `prepare_evidence` at all — a private helper that resolves recipients on demand inside `enforce_constraints` is the right-sized, lazier fit.

The key correction to "just copy the intel pattern": `file_intel`/`command_intel` are *always-computed, pure, feed-the-AI* facts; email recipient resolution is *conditional, I/O-bound, feed-the-gate* resolution. Same architectural plane (evidence, not intent), different mechanism (lazy in `enforce_constraints`, not eager in `prepare_evidence`).

Want me to write up the concrete Tier 1 reshape (new `enforce_constraints` recipient resolution + the deletions) as a plan for Agent mode, and separately spec Tier 2 so you can decide on it independently?

---

**User**

there is a bigger concern here...guardian needs full email list or enriiched intent currently for its semantic judgement...thats why it was added in the first place...so both AE and Guardian can see he whole email structure before sending...the thing is i can just write dont send sany emails to xyz@gmail.com in intent limits and intentframe should enforce that...even without connstraints or domain constraints

---

**Cursor**

This is the crux of the whole discussion, and it changes my earlier recommendation. Let me verify exactly how intent limits are enforced before I respond, because the answer hinges on whether "don't email xyz@gmail.com" is judged by the Guardian LLM (needs recipients in the prompt) or by a deterministic checker.

That reframes everything — and you've identified the load-bearing reason enrichment exists. Let me confirm the enforcement mechanism, because it determines whether "email intel" alone is even sufficient.

**Confirmed: intent limits are enforced by the Guardian LLM, not deterministically.** The Guardian reads them as a trusted prompt section and maps plain-English rules to behavior:

```415:435:intentframe_components/guardian/engine.py
        if user_context.intent_limits:
            limit_lines: list[str] = []
            for i, limit in enumerate(user_context.intent_limits, 1):
                ...
            trusted_sections["Intent Limits"] = "\n".join(limit_lines)

        # ── Untrusted section (agent-controlled) ──────────────────
        untrusted = {"Target": intent.target, "Reason": intent.reason}
        data_section = format_intent_data(intent.data)
        if data_section:
            untrusted["Data"] = data_section
```

Your demo proves it — ~49/100 root blocks came purely from the Guardian LLM reading grandma rules. So "don't email xyz@gmail.com" is a Guardian-semantic feature, and **it only works if the recipient list is in the Guardian's prompt.**

## The critical finding that changes my prior advice

Here's the catch that breaks the naive "just use the intel pattern" plan:

**The intel pattern (terminal/files) feeds AE via `ae_external_context` — but the Guardian never reads that channel.** I traced the Guardian prompt builder: the *only* bundle-supplied input it consumes is `constraint_context`. And `guardian_external_context` is **defined but completely unused** (one definition site, zero readers):

```151:151:intentframe_bundle_sdk/types.py
    guardian_external_context: str = ""
```

So today, terminal/file intel reaches the Guardian only *indirectly* — via whatever the AE chose to echo into its analysis report. The **only channel that reliably puts a fact in front of the Guardian as structured input is the intent itself** (untrusted `target`/`data`).

That's *why* email used `enrich()` → `enriched_intent` instead of the intel pattern: mutating `intent.data` is the one mechanism that guarantees both AE *and* Guardian see the recipients. The intel pattern would **not** have gotten recipients to the Guardian.

**Consequence:** if you naively port email to the terminal/files intel pattern (evidence + `ae_external_context`) and delete the intent mutation, you would *regress* your "don't email xyz" capability — the Guardian would stop seeing recipients, and the intent limit would silently stop firing for replies.

## The real architectural issue (and the right fix)

Your earlier invariant ("policy/AI see what the actor submitted") is in genuine tension with "Guardian needs the resolved email structure." The resolution is to recognize these are **two different facts that must both be visible, with distinct provenance**:

| Fact | Source | Trust | Channel today |
|------|--------|-------|---------------|
| What the actor *claims* (rfc_message_id, body, reply_all) | Agent | **Untrusted** | `intent.data` |
| What the system *resolved* (sender, subject, full recipient list) | DB/EDI | **Trusted** | ❌ none — currently smuggled into untrusted `intent.data` via enrich |

The actual defect in today's design isn't "enrichment exists" — it's that **enrichment writes system-resolved facts into the untrusted `intent.data`, blurring "the agent said this" with "the system resolved this."** The Guardian sees the recipient list rendered identically to agent-controlled input.

So the correct design is not "delete enrichment" (that loses the visibility you need) and not "lazy-resolve in enforce_constraints" (that never reaches the Guardian). It's:

1. **Resolve the full email structure into evidence** (your "email intel") — sender, subject, and the *expanded* recipient set (sender for reply; sender+To+Cc for reply-all). This is the intel object, and it's where reply-all finally gets covered.
2. **Surface it to BOTH AE and Guardian as a *trusted*, clearly-labeled context section** — e.g. "RESOLVED EMAIL RECIPIENTS (system-derived, not agent-claimed): …". For AE that's `ae_external_context` (already wired). For the Guardian, **you must activate the dormant `guardian_external_context` channel** — wire it into `_build_validation_prompt` the way `ae_external_context` is wired into the AE prompt. That's the missing substrate piece.
3. **The constraint gate reads the same resolved evidence** (deterministic enforcement when `allowed_recipients` is configured).
4. **Leave the submitted `intent.data` pure** (untrusted, exactly what the actor sent).

That simultaneously: keeps your intent-limit enforcement working, *strengthens* it (recipients become trusted fact instead of untrusted claim), fixes the reply-all coverage gap, honors your provenance invariant, and still removes the `to`-injection hack.

## So, to answer directly

**Yes, create "email intel" — but it's a bigger change than terminal/files intel, because email is the first family that needs resolved facts in front of the *Guardian*, and that channel doesn't exist yet.**

Minimum viable version of this design:

- `EmailIntel` (sender, subject, mailbox, `resolved_recipients`, `reply_all_recipients`) resolved in `prepare_evidence` (or lazily — but since you now need it for the *always-on* AI path, not just the conditional constraint path, `prepare_evidence` is the right home after all, for send-like actions).
- AE: render it into `ae_external_context` (trusted) — already works.
- **Guardian: wire `guardian_external_context` into the prompt and render the same intel there.** This is the keystone enabling "don't email xyz" without constraints.
- Constraints: read `EmailIntel.resolved_recipients`.
- Delete: `to` injection, `_ENRICHER_RESOLVED`, the `intent.data` mutation.

One thing worth flagging before you commit: activating `guardian_external_context` is a **substrate change affecting every bundle**, and it touches the Guardian prompt — your most security-sensitive prompt. It deserves its own careful step (and prompt-hardening review), separate from the email-specific work.

Want me to spec this as two ordered work items — (1) substrate: wire `guardian_external_context` into the Guardian prompt with hardening, (2) email: `EmailIntel` in evidence feeding AE + Guardian + constraints, deletions of the enrich hook — with the exact files and test impacts for each? I can lay that out while we're still in Ask mode so you can review before switching to Agent mode.

---

**User**

on a high level , what is meaningfylly different purpose of prepare evidence and enrich intent? and this is not core invariant...actor-executor is fixed...basically there is no point of saying ai only sees intent..it sees so many things along with intent..so that does not makes sense..the only concern is system generated fields are now in untrusted intent? any reason u mark system generated fields in intent as untrusted in any case?

---

**Cursor**

You're right on both counts, and the third question is the one that actually matters. Let me take them in order.

## 1. `prepare_evidence` vs `enrich` — the real difference

It's not the soft docstring distinction ("analyze payload" vs "fetch external data"). Both are async, both can do I/O. The **hard, enforced** difference is in two powers, and they're almost mirror images:

| | `prepare_evidence` | `enrich` |
|---|---|---|
| Can it **stop** the pipeline? | **Yes** — may return terminal (BLOCK) | **No** — runner raises if it returns terminal |
| Can it **mutate the intent**? | **No** — writes only `ctx.evidence` (side annotations) | **Yes** — writes `ctx.enriched_intent`, which becomes `effective_intent` downstream |

```163:169:intentframe_bundle_sdk/runner.py
        if enriched.terminal:
            raise RuntimeError(
                f"bundle {bundle.bundle_id!r} enrich() returned terminal "
                f"{enriched.decision.value} — enrichment must not BLOCK or ALLOW"
            )
        ctx = enriched.context
        record_enrichment(ctx, bundle_id=bundle.bundle_id)
```

So: **`prepare_evidence` can halt but can't rewrite; `enrich` can rewrite but can't halt.** `enrich` is the *only* hook that makes `effective_intent != intent`. Everything else treats the intent as immutable and works off it + side evidence.

And here's the consequence you're circling: given the actor↔executor contract is fixed, **rewriting the canonical frame is the architecturally suspect power.** Anything `enrich` produces that the executor consumes silently breaks "executor does what the actor submitted." Anything it produces that the executor *ignores* (display `target`, the inert `to`) could have been evidence instead. So `enrich` is largely redundant with `prepare_evidence` + a context channel — the reason email reached for it was to get fields in front of the Guardian, which is a missing-channel problem, not a need-to-mutate problem.

## 2. The invariant — you're correct, I overstated it

"AI sees only what the actor submitted" is **not** an invariant, and I was wrong to lean on it. The architecture deliberately feeds the AI a large trusted context: action, agent, task, the full analysis report, policy context, constraint summaries, intent limits, runtime context, and bundle external context (terminal signals, file intel). The whole design *philosophy* is evidence-augmented judgment — the more trusted context the AI gets, the better. The fixed invariant is the **actor↔executor** contract. The AI is an observer/judge, not a party to that contract. So "AI sees many things alongside the intent" is exactly right and by design.

## 3. The only real concern — and is there ever a reason to mark system fields untrusted?

This is the sharp one. The defect today is purely **provenance mislabeling**: `enrich` writes system-resolved facts into `intent.data`, and the prompt builder dumps all of `intent.data` wholesale into the *untrusted* section:

```437:442:intentframe_components/guardian/engine.py
        # ── Untrusted section (agent-controlled) ──────────────────
        untrusted = {"Target": intent.target, "Reason": intent.reason}
        data_section = format_intent_data(intent.data)
        if data_section:
            untrusted["Data"] = data_section
```

There's no per-field provenance — the `intent.data` bucket is a single coarse trust class. So the question "any reason to mark system-generated fields untrusted?" splits into two answers, and the distinction is the whole point:

**For genuinely system-computed routing facts → No, never. It's strictly harmful.** The resolved recipient *address*, `account_email`, `mailbox` are computed by your code from your DB. Marking them untrusted:
- tells the Guardian "be suspicious, this may be adversarial," which is wrong for ground-truth data, and
- co-mingles them with agent-controlled fields so the LLM **cannot distinguish "agent claimed recipient X" from "system resolved recipient X."** That directly undermines the "don't email xyz@gmail.com" enforcement you want: for that limit to be reliable, the recipient must be presented as a *trusted system fact*, not a possibly-spoofed claim sitting in the untrusted bucket.

**But — and this is the real subtlety — not everything `enrich` pulls is a system fact.** Some "enriched" email fields are *third-party content*:
- `email_subject`, `email_from` (sender display name), and any body/quoted text are **controlled by whoever sent the email.** A malicious sender can put a prompt-injection payload in the subject line. Those fields are correctly **untrusted** — they're attacker-influenced content, not system-trusted facts.

So the honest model isn't "intent = untrusted, evidence = trusted." It's **provenance-per-field**, three classes:

| Class | Example | Correct trust |
|-------|---------|---------------|
| Actor-claimed | `rfc_message_id`, `body`, `reply_all` | Untrusted |
| System-computed routing fact | resolved recipient address, `account_email`, `mailbox` | **Trusted** |
| Third-party content the system fetched | `email_subject`, sender display name, quoted body | **Untrusted** (it's external content) |

Today's design accidentally gets class 3 "right" (subject/sender land in untrusted, which is correct) but gets class 2 **wrong** (resolved recipients also land in untrusted, weakening exactly the enforcement you care about). That's the actual bug — not "enrichment exists," but "enrichment has no provenance, so it dumps both trustworthy routing facts and untrustworthy remote content into the same untrusted bucket."

## Synthesis

- `enrich` = the mutate-the-frame hook; given the fixed actor↔executor contract, that power is mostly unnecessary and is what created the provenance mess. `prepare_evidence` = attach-facts (+ optional early block) without touching the frame.
- "AI sees only the intent" isn't real; trusted context augmentation is the design.
- There's **no** reason to mark genuinely system-computed fields untrusted — doing so only weakens the Guardian's semantic enforcement. There **is** a reason some "enriched" email fields are untrusted, but only because they're third-party content (subject/sender/body), not because they're system-generated.

The design implication: what you want isn't "evidence vs enrich" plumbing — it's **a provenance-aware context channel** that lets a bundle hand the AI layer facts tagged trusted (resolved recipients, mailbox) vs untrusted (subject, sender display, body), feeding *both* AE and Guardian. That subsumes the "email intel" idea and fixes the real defect.

Want me to sketch what a provenance-tagged bundle→AI context would look like (the minimal type change + how AE/Guardian would render trusted vs untrusted sections from it), so you can see whether it's worth generalizing beyond email?

---

**User**

why i should use this as trusted - System-computed routing fact
resolved recipient address, account_email, mailbox...assume if the reply all had different executor structure where it would need all fields...for edi, it does not...but maybe in a third party code...it can have all computed fields...which might also  be filled by llm..in our case edi does it internally or maybe in others code too 

---

**Cursor**

You've found the flaw in my classification, and it's the important one. I attached trust to the **field's role** ("routing fact"). That's wrong. Trust is a property of **where this value came from in this specific flow** — and that origin is adapter-dependent, exactly as you say.

## Trust is provenance, not semantics

`to` / `account_email` / `mailbox` have no intrinsic trust level. The same logical field can be:

- **System-resolved** (EDI derives recipients from the stored message headers) → trustworthy ground truth.
- **LLM-supplied** (a third-party adapter that needs `to` explicitly because it doesn't derive anything) → agent claim, untrusted.

So "resolved recipient = trusted" is only true *in the EDI pairing*. Port the same action to an adapter that consumes the submitted `to`, and that field is now agent-authored — marking it trusted would be a lie. The substrate cannot know which case it's in; only the bundle↔adapter contract knows.

This means: **you can't bake trust into the field. Only the component that actually produced the value can vouch for it.** A bundle may tag as trusted *only the values it itself resolved* in this run, and must leave actor-submitted values untrusted — even when they're the "same" concept.

## The tighter principle: trust must bind to what the executor actually acts on

There are really two questions that the coarse `intent.data`-bucket conflates:

1. **What will actually execute?** = whatever the executor acts on. Adapter-dependent. EDI: internally-derived recipients. Generic adapter: the submitted `to`.
2. **Who authored that value?** = the provenance. System-resolved → trusted. LLM-filled → untrusted.

The value the AI should treat as ground truth is the answer to (1), and its trust label is the answer to (2). The danger is when they diverge: if a bundle presents "trusted: recipients = bob (system-resolved)" but a mismatched executor actually sends to the LLM's `to = alice`, you've manufactured *false assurance* — the Guardian validated a fact that isn't what executes. That's the same divergence as the earlier "validate the field the executor acts on" rule, now generalized: **provenance tagging and enforcement must both bind to the executor contract, or they're fiction.**

## The consequence you're driving at

Because the binding is adapter-specific, the safe default is **untrusted**, and trusted-tagging is a *conservative optimization*, not the norm:

- **Untrusted is not invisible.** A recipient in the untrusted section is still fully visible to the Guardian, and "don't email xyz@gmail.com" still fires. Untrusted just biases the model toward suspicion — and for a security layer, suspicion bias causes over-blocking (false positives), never under-blocking. That's the safe direction.
- **Trusted buys two things, and only when provenance is guaranteed:** (a) fewer false positives (the Guardian won't discount a real fact as "maybe the agent is lying"), and (b) **anti-spoofing** — if recipients are system-resolved-and-trusted, the agent can't lie about them. But (b) only matters when the executor derives internally; if the executor uses the agent's value, the agent "can't lie" anyway because whatever it submits is literally what executes (and being untrusted, it gets scrutinized).

So for your EDI reply-all case, presenting the system-resolved recipient set as trusted is *legitimately better* (anti-spoofing + ground truth). But it's better **because EDI derives internally**, not because recipients are "routing facts." For a third-party adapter where the LLM fills those fields and the executor consumes them, the correct presentation is: no system-resolved fact exists, the submitted values execute, and they stay untrusted.

## What this says about the design

Don't build "trusted routing fields." Build a channel where **each bundle attaches provenance to the values it surfaces, scoped to its executor contract**:

- "system-resolved (will execute)" → render trusted
- "actor-claimed (will execute)" → render untrusted, and it's the enforcement target
- "third-party content the system fetched" (subject/sender/body) → untrusted regardless

And critically — a bundle may only tag "system-resolved (will execute)" when its paired executor actually derives that value. The substrate provides the provenance vocabulary; the bundle, which knows its adapter, assigns the labels. That keeps the actor↔executor contract authoritative and prevents the trusted-tag from drifting away from what executes.

Net correction to my earlier answer: scrap "routing fact = trusted." The rule is **trust = who produced the executing value, decided per bundle↔adapter, defaulting to untrusted.** Your EDI case earns "trusted" by virtue of EDI's internal derivation — not by virtue of the field being a recipient.

---

**User**



is enrich intent is a function to complete a partial intent?

---

**Cursor**

Mechanically, yes — that's exactly what it is today. The tell is the fill-if-absent guard:

```90:97:intentframe_native_bundles/actions/email/enrich.py
    for key, value in meta.items():
        if not data.get(key):
            data[key] = value

    if intent.action.value == ActionType.REPLY_EMAIL.value and not data.get("to"):
        reply_to = meta.get("email_from_address") or ""
        if reply_to:
            data["to"] = reply_to
```

"If the field isn't there, put it there." So as written, `enrich_intent` is a **partial-intent completer**: it back-fills `to`, `subject`, `sender`, `mailbox`, etc. that the actor didn't submit, and replaces the placeholder `target`.

But "complete a partial intent" is precisely the framing that hides the bug, because it fuses two operations that don't belong together:

**1. Completing fields the *executor* needs.** This is "completion" in the literal sense — finishing an under-specified request. But it's the problematic kind, for two reasons we already established:
- It makes the *system* a co-author of the request. The actor↔executor contract says the executor acts on what the actor submitted; if the system silently fills required fields, the executed action contains data the actor never asked for. If a required field is genuinely missing, the honest responses are **reject** or **ask**, not **fabricate**.
- In your actual case it's moot — EDI derives recipients internally, so there's nothing to complete. The "completion" is inert.

**2. Adding context for the judge/display.** Subject, sender, the pretty `target` — these aren't *completing the intent*, they're *annotating* it. The intent was already complete (`rfc_message_id` + `body` + `reply_all` fully specifies the request). It just lacked surrounding facts for the AI to reason about. That's evidence, not a missing field — and it has no business in `intent.data`.

So the precise answer: **`enrich_intent` is implemented as a partial-intent completer, but that's its design smell, not its rationale.** Of the "completion" it performs, part is unnecessary/inert (executor-needed fields EDI already derives), and part is miscategorized context (judgment/display facts that should be annotations, not intent fields).

There *is* one legitimate cousin worth naming so you don't over-correct: **canonicalization** — a faithful, deterministic transform of values the actor *did* submit (e.g. normalizing a path to absolute, parsing a date to ISO). That genuinely "completes" an intent without new authorship, because it only re-expresses what the actor already said. But that's distinct from what `enrich_intent` does — it fetches *external* data to fill *absent* fields, which is authorship, not normalization.

Net: if you define enrich as "complete a partial intent," you've licensed the system to author requests and to smuggle context into the intent. The cleaner mental model is three separate verbs:
- **canonicalize** — faithfully rewrite submitted values (legitimate intent transform)
- **annotate** — attach external facts as provenance-tagged evidence (never intent fields)
- **reject/ask** — when a required field is truly missing

`enrich_intent` today is doing "annotate" and "fabricate-missing" while disguised as "complete," which is why it ended up putting system facts into the untrusted frame.

---

**User**

okay so today if anything mutates intent...and all the mutation fields if not safe like reply email,  is not trusted data..one can do that in enrich

---

**Cursor**

Empty file (just a placeholder TODO). On your statement — yes, that's correct today, with three caveats worth nailing down so you don't over-trust the "it's just untrusted" part.

**Confirmed:** anything `enrich` mutates into the frame — both `target` and every key in `data` — renders in the **untrusted** section of both the AE and Guardian prompts. There's no per-field provenance, so nothing `enrich` injects can become *trusted*. In the suspicion-bias direction that's safe: injected fields inherit "treat with suspicion," which over-blocks rather than under-blocks. And not-safe actions like `REPLY_EMAIL` (`safe=False`) do traverse the AE/Guardian path, so they actually hit that untrusted rendering.

But "it's just untrusted data" is only the whole truth for the *prompt*. Three caveats:

**1. Untrusted ≠ inert for execution.** The enriched frame is also `effective_intent`, which is what flows to the executor:

```528:532:intentframe_server/pipeline.py
        intent = (
            det_result.bundle_context.effective_intent
            if det_result.bundle_context is not None
            else intent
        )
```

So if the paired adapter *consumes* a field `enrich` injected, that's a real execution effect, not just untrusted prompt text. EDI ignores `to` on reply, so it's inert *there* — but that's an EDI fact, not a general one. A different adapter that reads the injected field would execute on a system-authored value.

**2. The fill-if-absent guard means the agent wins.** `enrich` only sets a field when it's missing (`if not data.get(key)`). So an agent that pre-supplies the field suppresses the system value entirely — the "system fact" appears only when the agent stayed silent. So you can't assume the untrusted field reflects the system's resolution; it may be the agent's own value that enrich declined to overwrite.

**3. Safe/passive actions may never reach the prompt.** Passive reads can be deterministically ALLOWed and skip AE/Guardian, so the untrusted-rendering statement holds specifically for actions that reach the AI layer (the not-safe / UNDECIDED ones, which is the case you named).

So your summary is right: **today, enrich mutations are untrusted in the prompt, so doing the mutation in enrich is "safe" in the sense that it can't forge trust.** Just remember it can still (a) drive execution via `effective_intent` in adapters that read the field, and (b) be silently overridden by an agent-supplied value because of the fill-if-absent guard.

