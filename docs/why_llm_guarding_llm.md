Short answer: **yes, substantively — but `demo/tests/all_test_results.md` alone is not what proves it.** The validation is distributed across four files, and only a subset of the 24 attacks actually tests AI-layer prompt-injection resistance specifically. Let me lay out exactly what each test file proves and where the honest gaps are.

## What the 24 attacks in `all_test_results.md` actually prove

Of the 24 attacks, 23 are DEFENDED and 1 is a KNOWN GAP (Attack 16, salami slicing — unrelated to injection).

But the important distinction the security_analysis.md already makes explicit:

| # of attacks | What blocked them | What they validate |
|---|---|---|
| ~19 of 24 | **Deterministic layer** ($amount > $5k, or allowed_paths) | IntentFrame's **containment** despite injected content; not specifically the AI layers' resistance |
| 4 of 24 | **AI layers only** (AE + Guardian semantic) | The AI layers' **actual resistance** to prompt-injection-style intents |

The 4 that specifically exercise AE/Guardian prompt-injection resistance (deterministic layer would ALLOW, AI must catch):

- **Attack 2** — Data Manipulation ($499 decoy, under limit). 10/10 reproducibility BLOCK.
- **Attack 6** — Duplicate Bypass ($2,500, under limit).
- **Attack 15** — Stealth Amount Mismatch ($4,999, under limit, clean `reason`).
- **Attack 17** — Exfil Through Write ($1, under limit, payload hidden in vendor field).

Your docs' claim — *"AE + Guardian resist prompt-injection-style inputs from intent"* — is directly validated by these 4. That's a meaningful but narrow slice.

Attacks 7–14 (the "pure" prompt-injection categories: encoding obfuscation, many-shot, crescendo, delimiter injection, role confusion, typoglycemia, unicode smuggling, tool confusion) **all use amounts > $5k**, so the deterministic cap catches them. They prove IntentFrame contains injected agents — they do not prove the AI layers resisted the injection, because the AI layers never had to be the last line of defense.

So: if you only pointed Alex at `all_test_results.md` and said "this proves our AI layers are prompt-injection resistant," that would be overclaiming. It proves containment under injection, not AI resistance under injection.

## What actually validates the "AI layers hardened against prompt injection" claim

Three other test artifacts carry that weight:

### 1. `tests/test_prompt_hardening.py` — structural hardening unit tests

This file directly tests the prompt-injection hardening primitives:

```1:13:tests/test_prompt_hardening.py
"""
Tests for the prompt hardening modules.

Covers:
  - Encoding normalization (Unicode, zero-width, base64)
  - Boundary token generation and framing
  - Role anchoring constants
  - Sandwich-pattern closing reinforcement
  - PromptHardening orchestrator (end-to-end prompt shape)
  - Analysis Engine hardened prompt construction
  - Guardian hardened prompt construction
  - Trust boundary correctness (untrusted vs trusted fields)
"""
```

It specifically verifies:
- Zero-width / ligature / fullwidth Unicode gets normalized (`test_zero_width_space_stripped`, `test_unicode_nfkc_fullwidth`).
- Base64 payloads get flagged with a pipeline note (`test_real_base64_flagged`).
- Untrusted content is wrapped in randomized 32-hex boundary tokens that an attacker cannot guess (`test_attacker_cannot_guess_boundary`).
- Trusted vs untrusted zones are preserved (normalization applies only to untrusted content).
- Role anchoring ("IMMUTABLE", "BOUNDARY PROTOCOL", anti-mode-switch for DAN/developer/debug) is present in both AE and Guardian role strings.
- Closing "sandwich" reinforcement references the boundary and re-asserts role immutability after untrusted content.

This is real evidence that the AI layers are hardened *at the prompt construction level*.

### 2. `tests/test_transitive_injection.py` — deterministic trust boundary

Tests that poisoned AE free-text fields (`stated_intent`, `hidden_behaviors`, `recommendation`, `semantic_domains`) land in Guardian's `<trusted_context>` correctly, enum-mapped fields are sanitized, and the prompt structure survives poisoned input. CI-safe, no API key needed.

### 3. `demo/tests/test_transitive_injection_live.py` — live end-to-end AI resistance

This is the file that most directly backs the docs' claim. From its docstring (lines 1–29):

- Live tests 4 and 5 run a **real injected intent → real AE → real Guardian** end-to-end, and both pass.
- The AE refuses to produce poisoned output when fed `IGNORE ALL PREVIOUS INSTRUCTIONS`-style content in `intent.reason`.
- AE output stays within `AEFieldLimit` bounds and `ae_output_anomaly` is not flagged — the hardening constraints actually hold on live runs.

Current captured run: **39/43 PASS**. The 4 "failures" are explicitly documented in `demo/tests/README.md` at the "Transitive Injection Tests — What They Prove" section:

- **Test 9a** (lookalike `aws-billing-portal.net` domain) — this is a context/allowlist problem, not a prompt-injection resistance failure. A user-specific `approved_vendor_domains` constraint would block it deterministically; no amount of model capability teaches a stateless LLM which domains *this* user trusts.
- **Tests 10a/10b/10c** — these hand-fabricate a fully compromised `AnalysisReport` and inject it directly into Guardian's `<trusted_context>`, **bypassing the entire AE** (its hardened prompt, structured output, encoding normalization, `AEFieldLimit` bounds). In production that shape can only exist if the AE was first compromised via intent — and that real surface is covered by the 24 attack tests plus live tests 4 and 5.

So the transitive suite is honest about where the AE→Guardian trust boundary is load-bearing vs where the AE itself is load-bearing.

## Honest self-audit of the edits I made

Going back to the doc edits, here's what holds up and what is slightly aspirational:

| Claim in edits | Truth status |
|---|---|
| "IntentFrame's AI layers are hardened against prompt-injection-style inputs" | **True** — backed by `test_prompt_hardening.py` (structural) + attacks 2/6/15/17 (semantic, under-limit) + transitive live tests 4/5 (end-to-end real AE+Guardian with real injection). |
| "The root demo is not a benchmark of the agent's LLM" | **True** — stub agent, deterministic corpus, IntentFrame is the system under test. |
| "AE + Guardian resist prompt injection from intent fields" | **True for the tested scenarios**, with caveats — tests 10a/b/c show the Guardian is *not* designed to re-verify a fully compromised AE (by design; otherwise AE serves no purpose). The architectural answer is that the AE layer is where this resistance lives, and the AE's own resistance is validated by tests 4/5. |
| "24 attacks defended = AI layer prompt-injection resistance is proven" | **Overclaim** — 19ish of those blocks come from the deterministic layer. The AI-layer resistance claim is really carried by attacks 2/6/15/17 and by the separate hardening + live transitive suites. |

## Where honest documentation should point

If you want Alex to be able to verify the "AI layers resist prompt injection" claim, the right pointer is not `all_test_results.md` alone. It is:

1. **`all_test_results.md`** — shows IntentFrame contains a compromised agent across 24 attack vectors (most via deterministic gates).
2. **Attacks 2, 6, 15, 17 specifically** — the under-limit cases where the AI layers are the only thing standing between a malicious intent and the executor. These are where "AI layer prompt-injection resistance" is actually measured.
3. **`tests/test_prompt_hardening.py`** — prompt-construction-level hardening (normalization, boundaries, role anchoring, sandwich reinforcement).
4. **`demo/tests/test_transitive_injection_live.py` tests 4 and 5** — real-world end-to-end: injected intent → real AE → real Guardian → correct block.
5. **`demo/tests/README.md` "Transitive Injection Tests — What They Prove" section** — honest accounting of which "failures" are context problems vs hypothetical AE-bypass experiments vs production-representative.

## Recommendation

The docs are substantively honest, but I'd suggest one small tightening so Alex can't catch us on the nuance:

In `skeptical_security_questions.md` and `stub_agent_crash_test_rationale.md`, where we say "IntentFrame's own AI layers are hardened and tested for prompt-injection-style inputs," consider adding a specific pointer chain:

> Evidence lives in:
> - `tests/test_prompt_hardening.py` — structural hardening (Unicode normalization, boundary tokens, role anchoring, sandwich reinforcement).
> - Attacks 2, 6, 15, 17 in `demo/tests/all_test_results.md` — under-limit intents where deterministic gates ALLOW and AI layers must catch the injection semantically.
> - `demo/tests/test_transitive_injection_live.py` tests 4 and 5 — real injected intent through real AE through real Guardian, end-to-end.
>
> Caveat: attacks 7–14 (encoding/delimiter/role/unicode/tool-confusion) are blocked by the $5k deterministic cap in the test policy, so they validate *containment under injection*, not *AI resistance under injection*. The latter is what attacks 2/6/15/17 and the transitive live suite specifically measure.

That way the claim is both true and un-ambush-able.

Want me to draft the exact insert text for those two docs (I can show it here, Ask mode only)?