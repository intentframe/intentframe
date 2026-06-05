# Model support — AE, Guardian, and Onboarding

> **Scope:** `intentframe_components` AI engines and how `intentframe-server` wires them.  
> **Out of scope here:** Jarvis agent model config (`~/.jarvis/config.yaml`, `JARVIS_MODEL`) — that path is separate and already supports non-OpenAI models via LiteLLM.

---

## Current state

| Engine | Default model | Constructor | Provider routing | ModelSettings |
|--------|---------------|-------------|------------------|---------------|
| `AIAnalysisEngine` | `gpt-4o-mini` | `model: str` only | OpenAI string → Agents SDK default provider | `temperature=0` (hardcoded) |
| `AIGuardian` | `gpt-5-mini-2025-08-07` | `model: str` only | OpenAI string → Agents SDK default provider | SDK defaults (GPT-5 reasoning effort when applicable) |
| `AIOnboardingEngine` | `gpt-4o-mini` | `model: str` only | OpenAI string → Agents SDK default provider | SDK defaults |

**Wiring today**

- Engines accept a `model` string at construction time; tests and demos pass it explicitly (`AE_MODEL`, `GUARDIAN_MODEL` constants).
- `intentframe-server` `_create_runtime()` instantiates all three with **defaults only** — no `model=` argument, no env vars, no `core.yaml` fields.
- All three use OpenAI Agents SDK `Agent(..., output_type=<Pydantic schema>)` and `Runner.run(agent, prompt)` with no `RunConfig`, no `Model` object, and no custom `ModelProvider`.
- AE and Guardian are **OpenAI cloud only** in production; prompts and policy text leave the machine when the AI path runs. Docs describe local / multi-provider support as roadmap, not shipped for these layers.

**Constraints inherited from the stack**

- Structured output is required for AE, Guardian, and Onboarding — not every model or provider backend supports the JSON-schema path the SDK uses.
- AE is tuned for completion-style models (`temperature=0`); Guardian defaults to a GPT-5 reasoning model — the two roles assume different model families today.
- The OpenAI Agents SDK itself supports cloud, LiteLLM, Any-LLM, and OpenAI-compatible local endpoints; **this package does not expose any of that** beyond a bare model string on three constructors.

---

## What to do

1. **Make AE, Guardian, and Onboarding models configurable at deploy time** — not only via code changes or constructor overrides in tests. The server / core profile should own the wiring; components should remain injectable.

2. **Decide and document the supported provider surface** — OpenAI-only vs proxy-backed multi-provider vs local — and which backends are in scope for security-critical structured output.

3. **Keep per-role model selection** — analysis, judge, and onboarding may intentionally use different models; configuration should allow that without coupling them to Jarvis or a single global default.

4. **Align model settings with chosen model families** — AE and Guardian should not assume incompatible settings (e.g. `temperature` on reasoning-only models) once models become configurable.

5. **Validate before claiming support** — any new backend must be red-teamed for structured-output reliability on the AE and Guardian schemas; “configurable” is not the same as “safe to run in production.”

6. **Update consumer-facing docs** — privacy, deployment, and Jarvis guides currently say AE/Guardian are separate from agent model config; once support lands, document what is configurable, what stays on OpenAI by default, and what operators must provide (keys, proxy, tracing).

---

## Not in this TODO

- Implementation design (LiteLLM proxy vs `LitellmModel` vs `RunConfig.model_provider`, schema of `core.yaml`, etc.).
- Changing default models or prompts.
- Jarvis multi-provider wiring — reuse patterns only if useful; do not merge agent and security-layer config into one knob.
