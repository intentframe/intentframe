# Substrate vocabulary hygiene — remaining action literals in `intentframe_components`

> **Context:** [docs/_internal_/substrate-plugin-refactor.md](../../docs/_internal_/substrate-plugin-refactor.md) — completed bundle SDK refactor (May 2026).  
> Follow-up to path heuristics → files bundle and onboarding → `intentframe_native_kit.intentframe_native_bundles.onboarding`.  
> Pre-refactor baseline: `66e567c` (`pre-refactor` tag).

---

## Goal

**Substrate** (`intentframe_components` + thin `DeterministicGuardian`) should orchestrate only:

- opaque `intent.action` strings for permission / registry lookup,
- bundle-supplied evidence (`BundleContext`, `AnalysisContext`),
- generic prompt hardening and engine wiring.

**Product vocabulary** (action names, path fragments, capability families, per-family guardrail hints) should live in **`intentframe_action_bundle`** (and SDK phase contracts), not in substrate control flow or prompt bodies—except where explicitly accepted as shared content assets (see optional item 3).

---

## Already done

| Item | Status |
|------|--------|
| Path heuristics (`is_sensitive_write_path`, `classify_path_category`) | Moved to `intentframe_action_bundle/files/path_heuristics.py` |
| Dead `DefaultPromptStrategy` on `AIAnalysisEngine` | Removed; AE uses `analysis_context.ae_prompt_id` from bundles |
| Onboarding action literals + constraint summaries | Moved to `intentframe_action_bundle/onboarding/` |
| Deterministic gates (pre-`66e567c` matrix) | Preserved in bundles + `DeterministicRunner`; not regressed |

---

## Remaining leaks (audit summary)

| Category | Location | Kind |
|----------|----------|------|
| Guardian routing | `prompt/strategy.py` — `is_critical(intent.action.value)` | **Behavior** (data from bundle `taxonomy`, branch in substrate) |
| User-IO prompt text | `prompt/library/guardian.py`, `guardian/engine.py` closing | **Prompt content** (`ASK_USER`, `SHOW_MESSAGE`, `GET_CONFIRMATION`) |
| AE standard examples | `prompt/library/analysis.py` `_STANDARD` | **Prompt content** (`HTTP_POST`, `DELETE_FILE`, `READ_FILE` as examples) |
| Doc / example drift | `routing/__init__.py`, `prompt/hardening.py` docstring | **Docs only** |
| Domain replay | `guardian/engine.py` AI path — `ACTION_DOMAINS` + `DOMAIN_MODULES` | **Behavior** (domain-keyed, not action-id tables; lower priority) |

---

## TODO 1 — Guardian routing: bundle-owned `guardian_prompt_id` (mirror AE)

### Problem

AE prompt selection already lives in bundles (`select_ae_prompt_id` → `AnalysisContext.ae_prompt_id`). Guardian still uses substrate `DefaultPromptStrategy` + `is_critical(intent.action.value)` in `intentframe_components/prompt/strategy.py`.

### Target shape

- Bundle (or registry) exposes `select_guardian_prompt_id(intent, analysis?) -> str` — same pattern as AE.
- `AIGuardian` resolves prompt id from bundle/context only; **no** `is_critical` import in components.
- `routing/criticality.py` re-export can remain for tests/telemetry or move callers to `intentframe_action_bundle.taxonomy` directly.

### Suggested steps

1. Add `guardian_prompt_id` to a bundle-owned module (e.g. extend `intentframe_action_bundle/prompts/registry.py` or `taxonomy.py`).
2. Wire `AIGuardian._resolve_prompt_id` to bundle selection (pass `IntentFrame` + `AnalysisReport` if needed).
3. Deprecate / thin `DefaultPromptStrategy` to a test double or remove if unused.
4. Update `tests/test_prompt_strategy.py` Guardian matrix to assert bundle registry, not substrate `is_critical`.

### Acceptance

- `rg 'is_critical' intentframe_components/prompt/strategy.py` → no matches (or strategy deleted).
- Guardian `last_prompt_id` behavior unchanged for critical vs non-critical actions (parity tests green).

---

## TODO 2 — User-IO guardrail text → action bundle

### Problem

Guardian system prompt and closing instruction hardcode user-IO action names:

- `prompt/library/guardian.py` — `ASK_USER` / `SHOW_MESSAGE` / `GET_CONFIRMATION` section in `_STANDARD`.
- `guardian/engine.py` — closing bullet: `For ASK_USER: check prompt safety only…`

### Target shape

- New bundle module (e.g. `intentframe_action_bundle/user_io/guardian_hints.py` or under `prompts/`) exporting trusted prompt fragment(s).
- Substrate `GUARDIAN_PROMPTS` / `_build_validation_prompt` **inject** bundle text; no action literals in components.

### Suggested steps

1. Define `USER_IO_ACTIONS` frozenset in bundle (from `intentframe_native_kit.action_registry.types.ActionType`).
2. Export `guardian_user_io_section() -> str` (and optional closing line fragment).
3. Concatenate into Guardian `_STANDARD` via `build_guardian_prompts()` (mirror `build_analysis_prompts`).
4. Remove literal `ASK_USER` strings from `guardian/engine.py` closing; use bundle fragment or generic “user-IO actions” wording.

### Acceptance

- `rg 'ASK_USER|SHOW_MESSAGE|GET_CONFIRMATION' intentframe_components/prompt intentframe_components/guardian` → no matches in `.py` (tests may still mention ids).
- `tests/test_prompt_hardening.py` Guardian keyword invariants still pass.

---

## TODO 3 — Standard AE examples: generic wording (optional)

### Problem

`prompt/library/analysis.py` `_STANDARD` uses concrete action ids as pedagogical examples:

- `HTTP_POST to stripe.com/...`
- `DELETE_FILE → ["deletion"]`
- `READ_FILE → ["data_access"]`

Not a gate; does not change routing. Violates strict “zero action keywords in components” if taken literally.

### Target shape

Replace with action-agnostic examples, e.g.:

- “POST to a payments API → `["spending"]`”
- “delete a file → `["deletion"]`”
- “read a file → `["data_access"]`”

### Suggested steps

1. Edit `_STANDARD` examples only (preserve byte-level parity tests — **re-run** `verify_hardened_prompts_parity.py` / `test_prompt_hardening.py`; expect prompt hash updates if production prompts change).
2. Document in PR that parity guard is intentionally updated.

### Acceptance

- No `ActionType` enum values in `_STANDARD` string.
- AE structured-output behavior unchanged (same schema, same rubric intent).

**Priority:** Low / optional — cosmetic strictness unless parity policy forbids any standard-body edit.

---

## TODO 4 — Stale routing doc

### Problem

`intentframe_components/routing/__init__.py` still documents:

- `AIAnalysisEngine._PASSIVE_READ_ACTIONS` as conceptual inverse of `CRITICAL_ACTIONS`.

Passive-read set now lives in `intentframe_action_bundle.passive_read.actions.PASSIVE_READ_ACTIONS`; AE engine no longer owns that attribute.

### Suggested steps

1. Update module docstring to reference `intentframe_action_bundle.passive_read.actions.PASSIVE_READ_ACTIONS`.
2. Keep drift invariant: `CRITICAL_ACTIONS & PASSIVE_READ_ACTIONS == ∅` (already tested in `tests/test_prompt_strategy.py`).
3. Fix `prompt/hardening.py` module docstring example (`SEND_EMAIL`) if touching docs—optional one-liner.

### Acceptance

- No references to removed `AIAnalysisEngine._PASSIVE_READ_ACTIONS` in components docs.
- Drift test still green.

---

## Out of scope (for this doc)

| Item | Note |
|------|------|
| Moving `guardian/domains/*` into bundles | Domain-keyed, not action-literal tables; separate refactor |
| Moving full AE/Guardian prompt libraries to bundle | Largely done for AE critical forks; Guardian bodies still in components |
| `intentframe_components/TODO/AE_Guardian_specialisation_routes.md` | Historical; link from here, do not duplicate |
| Payload ALLOW / passive-write fast-path | Never shipped at `66e567c`; not a regression |

---

## Suggested PR order

1. **TODO 4** — doc-only, zero risk  
2. **TODO 1** — Guardian routing parity with AE (highest architectural value)  
3. **TODO 2** — User-IO prompt fragments  
4. **TODO 3** — optional standard-body example genericisation (parity review required)

---

## Verification command (after each PR)

```bash
# Action literals in substrate Python (excluding TODO markdown)
rg 'RUN_COMMAND|WRITE_FILE|SEND_EMAIL|ASK_USER|DELETE_FILE|READ_FILE' intentframe_components --type py

# Should trend toward: prompt library only (until TODO 2–3), then empty
```

```bash
uv run pytest tests/test_prompt_strategy.py tests/test_prompt_hardening.py tests/test_onboarding_constraint_summary.py -q
```
**Short answer:** Not automatically. It depends which TODO you implement. **PR A and PR B already pass parity today** (12/12 sections). The baseline only covers **AE + Guardian hardened prompts** from `inspect_hardened_prompts.py` — **not onboarding**.

---

## What the baseline actually guards

`hardened_prompts_legacy_baseline.txt` is a byte-normalized snapshot of **12 sections**:

- AE system + per-request prompts (SEND_EMAIL, RUN_COMMAND, WRITE_FILE scenarios)
- Guardian system + per-request prompts (same scenarios)

It does **not** include onboarding meta-prompts. So **PR B (onboarding move) does not affect this file** — and parity is still **12/12** after A + B.

---

## Per TODO item vs parity

| TODO | Will baseline stay true? | Why |
|------|---------------------------|-----|
| **4 — Stale routing doc** | **Yes** | Doc-only; no prompt bytes change. |
| **1 — Guardian routing via bundle** | **Yes, if behavior-preserving** | Same `critical` vs `standard` ids for the inspect scenarios → same `gu._agents[...].instructions` and same request prompts. Parity breaks only if bundle selection **changes** which lane fires (e.g. WRITE_FILE Guardian id changes — today 7b is `standard`). |
| **2 — User-IO text → bundle** | **Yes only if bytes identical** | `ASK_USER` / `SHOW_MESSAGE` / `GET_CONFIRMATION` live in Guardian `_STANDARD` and the closing line in `guardian/engine.py`. Moving to bundle is safe **only if** reassembly produces the **exact same** system + per-request text. Any wording/whitespace change → mismatch. |
| **3 — Generic AE examples** | **No (by design)** | Edits `_STANDARD` in `analysis.py` → AE system prompt (section 1) and any fork built on it change. The TODO already says: **regenerate baseline** and treat as intentional parity update. |

---

## Practical rule

- **Refactor-only PRs (1, 2):** Keep parity green by **lift-and-shift** — same strings, same prompt ids, same assembly order. Run:

  ```bash
  uv run python tests/verify_hardened_prompts_parity.py
  ```

- **Content PR (3):** Expect failure → refresh `hardened_prompts_legacy_baseline.txt` (and report) with an explicit “intentional prompt change” note, same as any production AE body edit.

---

## Note on WRITE_FILE Guardian (7b)

Inspect currently expects Guardian **WRITE_FILE** system prompt = **`standard`** (SEND_EMAIL is `critical`, WRITE_FILE system is `standard` in section 7b). TODO 1 must preserve that mapping or section 7b will fail even if routing code “looks cleaner.”

---

**Bottom line:** After TODO **4** and careful **1** / **2**, parity **can** remain true. After TODO **3**, it **will not** unless you update the baseline on purpose. Onboarding hygiene (PR B) was never part of this guard.

They **can** be fetched from bundles. Nothing in the architecture blocks it — it’s a **design choice + parity policy**, not a technical limit.

---

## What the code does today

Critical AE bodies already come from bundles:

```35:42:intentframe_action_bundle/prompts/registry.py
def build_analysis_prompts(standard_body: str) -> Mapping[str, str]:
    """Assemble the full AE prompt catalog from substrate + bundle contributions."""
    merged: dict[str, str] = {
        "standard": standard_body,
        "critical_generic": standard_body,
        **_BUNDLE_PROMPT_BODIES,
    }
```

Substrate passes in `_STANDARD` (including the `HTTP_POST` / `DELETE_FILE` / `READ_FILE` examples). Bundles add `critical_run_command`, `critical_write_file`, etc.

So the split is already **“substrate owns generic standard; bundles own family forks.”** The examples stayed in substrate because they’re part of that frozen **standard** string, not because bundles can’t supply text.

---

## Why they weren’t moved to bundles (yet)

1. **Parity guard** — `_STANDARD` was kept **byte-identical** to legacy (`ee04d7f`) for `hardened_prompts_legacy_baseline.txt`. Moving examples to bundles is fine **if** the assembled `standard` prompt is still the same bytes (lift-and-shift) or you **intentionally** refresh the baseline.

2. **Examples are cross-family** — One line mentions `HTTP_POST`, another `DELETE_FILE`, another `READ_FILE`. That isn’t owned by a single action bundle (terminal / files / api). You’d put them in a **shared bundle module**, e.g.  
   `intentframe_action_bundle/prompts/standard_body.py` or `semantic_domain_examples.py`,  
   not in `terminal/prompts.py` alone.

3. **TODO 3 was the cheap option** — “Reword examples in substrate to generic phrases” avoids touching assembly. **Bundle-owned examples** is the better match for your substrate/bundle boundary; TODO 3 just didn’t spell that out as the preferred path.

4. **Inconsistent already** — Hidden-behavior examples in the same `_STANDARD` block are already generic (“send email”, “delete file”). Only the **semantic domains** bullet list still uses action ids. That’s legacy inconsistency, not a rule that examples must live in components.

---

## What “fetch from bundles” would look like

**Option A — splice a fragment (minimal)**

```python
# intentframe_action_bundle/prompts/standard_fragments.py
def semantic_domain_examples_section() -> str: ...

# analysis.py
_STANDARD_CORE = """... without Examples block ..."""
STANDARD = _STANDARD_CORE + semantic_domain_examples_section()
ANALYSIS_PROMPTS = build_analysis_prompts(STANDARD)
```

**Option B — bundle owns full standard body**

```python
# registry.py
def build_analysis_prompts() -> Mapping[str, str]:
    standard = build_standard_ae_body()  # all in bundle
    ...
```

Substrate `analysis.py` becomes a thin import/wire-up only.

---

## Parity impact

| Approach | Baseline |
|----------|----------|
| Move to bundle, **same text** | Still **12/12** |
| Move to bundle, **generic wording** | **Breaks** until you regenerate baseline (same as TODO 3) |
| Onboarding-style move (PR B) | **Unaffected** — onboarding isn’t in the parity fixture |

---

## Bottom line

Examples **can** and probably **should** live in bundles (shared prompts module), same pattern as critical forks and onboarding. They’re still in substrate because:

- standard body was the parity-frozen core, and  
- TODO 3 listed “genericize in place” as optional/low priority.

If you want zero action literals in components **and** keep parity, do a **byte-preserving lift** to `intentframe_action_bundle/prompts/` first; genericize wording in a **second** PR with an explicit baseline update. I can add that as the preferred path in `substrate_vocabulary_hygiene.md` if you want.