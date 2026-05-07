# IntentFrame Documentation

> Index of every public IntentFrame doc — what to read for what question.

This is the entry point. Pick the path that matches what you came here to do.

---

## Start here

If you're new to IntentFrame, read in this order:

1. **[autonomy.md](autonomy.md)** — what IntentFrame is for: delegatable autonomy for AI agents, the licensing-shape thesis
2. **[quickstart.md](quickstart.md)** — install, first run, demo commands
3. **[architecture.md](architecture.md)** — the full pipeline (agent → actor → analysis engine → guardian → executor)
4. **[principles.md](principles.md)** — the structural invariants that implement the autonomy thesis
5. **[evidence.md](evidence.md)** — test results, root demo, failure reports

---

## By question

### "How do I install and run it?"

- [quickstart.md](quickstart.md) — install, configure OpenAI key, run the gateway, run the demo
- [processes.md](processes.md) — what processes will be running on your machine after startup
- [faq.md](faq.md) — common setup and operational questions

### "What is this for, conceptually?"

- [autonomy.md](autonomy.md) — the canonical thesis: delegatable autonomy as the goal, structural supervision as the means, the professional-licensing analogy
- [principles.md § 2 — Prevention before containment](principles.md#2-prevention-before-containment) — why IntentFrame blocks before execution instead of sandboxing after

### "What does it actually protect against?"

- [threat-model.md](threat-model.md) — what's in scope, what's out of scope
- [evidence.md](evidence.md) — verified test results, including a failure report and remediation
- [why_trust_ai_hybrid_intentframe.md](why_trust_ai_hybrid_intentframe.md) — why a hybrid AI/deterministic model is trustworthy
- [why_llm_guarding_llm_deep_dive.md](why_llm_guarding_llm_deep_dive.md) — the deep version of "isn't this just one LLM watching another?"
- [why-not-injection-shield.md](why-not-injection-shield.md) — why no dedicated prompt-injection detector

### "How is it built?"

- [architecture.md](architecture.md) — the logical pipeline
- [processes.md](processes.md) — the physical process model (what runs where)
- [modules.md](modules.md) — every workspace module, what it is, what it does, where its docs are
- [executor.md](executor.md) — the executor, the only component that touches the real world
- [executor/](executor/) — long-form material on the executor (architecture, security model, foundation argument, standalone-product positioning)

### "Where does my data live and what leaves the machine?"

- [privacy.md](privacy.md) — on-disk layout, outbound traffic catalog, what never happens
- [credentials-vault.md](credentials-vault.md) — how secrets are stored and accessed

### "How do specific subsystems work?"

- [credentials-vault.md](credentials-vault.md) — secret storage and the vault service
- [registries.md](registries.md) — policy registry, resource registry, action registry
- [email-sync.md](email-sync.md) — IMAP / SMTP sync daemon (EDI)
- [macos-platform-server.md](macos-platform-server.md) — Swift native bridge for Calendar / Contacts / iMessage / etc.
- [vfs-vs-host-tools.md](vfs-vs-host-tools.md) — workspace VFS vs host filesystem tools
- [executor/security-model.md](executor/security-model.md) — prevention pipeline + sandbox templates

### "How does the root demo work?"

- [root_demo/PROOF.md](root_demo/PROOF.md) — proof snapshot
- [root_demo/executor-root-mode.md](root_demo/executor-root-mode.md) — the root execution model
- [root_demo/root-policy-design.md](root_demo/root-policy-design.md) — the policies enforced in the demo

### "How are terminal commands handled?"

- [executor/security-model.md](executor/security-model.md) — the full prevention pipeline for `RUN_COMMAND`
- [terminal_use/current_pragmatic_choice.md](terminal_use/current_pragmatic_choice.md) — why the terminal surface is treated as universal
- [terminal_use/current_terminal_policy_rationale.md](terminal_use/current_terminal_policy_rationale.md) — terminal policy reasoning
- [terminal_use/current_deterministic_gates_mapping.md](terminal_use/current_deterministic_gates_mapping.md) — which gates fire on which command shapes

### "I want to extend IntentFrame"

- [executor/architecture.md](executor/architecture.md) — adapter pattern, how to add a new capability
- [executor/standalone-product.md](executor/standalone-product.md) — how the executor stands alone as infrastructure
- [dev/action-family-wiring.md](dev/action-family-wiring.md) — wiring new action families end-to-end

---

## By topic area

### Core docs

| Doc | What it covers |
|---|---|
| [autonomy.md](autonomy.md) | The thesis: delegatable autonomy as the goal, structural supervision as the means, professional licensing as the analogy |
| [architecture.md](architecture.md) | The logical pipeline, the separation invariant, fast-path security, the no-self-IO principle |
| [principles.md](principles.md) | The invariants that implement the thesis |
| [threat-model.md](threat-model.md) | What's protected, what isn't, the trust boundaries |
| [evidence.md](evidence.md) | Test results and proof artifacts |
| [faq.md](faq.md) | Common questions and objections |

### Runtime, processes, and data

| Doc | What it covers |
|---|---|
| [processes.md](processes.md) | Every long-lived process, what it does, what socket it listens on, what it depends on |
| [privacy.md](privacy.md) | What's on disk, what leaves the machine, what never happens |
| [modules.md](modules.md) | Every workspace module, with WH (what / why / where / who / how) for each |

### The executor

| Doc | What it covers |
|---|---|
| [executor.md](executor.md) | The Executor reference — engine analogy, credential isolation, adapter pattern, sandbox, audit |
| [executor/architecture.md](executor/architecture.md) | Internal four-layer architecture, gateway flow, registry pattern |
| [executor/security-model.md](executor/security-model.md) | Prevention pipeline + sandbox templates as safety net |
| [executor/why-foundation.md](executor/why-foundation.md) | Why the Executor (not Guardian) is the structural foundation |
| [executor/standalone-product.md](executor/standalone-product.md) | The Executor as a novel piece of infrastructure |

### Subsystems

| Doc | What it covers |
|---|---|
| [credentials-vault.md](credentials-vault.md) | Secret storage backed by OS keyring, exposed over a UDS service |
| [registries.md](registries.md) | Policy registry (rules), resource registry (VFS + adapters), action registry (taxonomy) |
| [email-sync.md](email-sync.md) | The EDI daemon — IMAP IDLE + SMTP + local SQLite mirror |
| [macos-platform-server.md](macos-platform-server.md) | Swift native bridge for Calendar / Contacts / Reminders / iMessage / Notes / Notifications |
| [vfs-vs-host-tools.md](vfs-vs-host-tools.md) | Workspace VFS file tools vs host file tools |

### Reasoning and design

| Doc | What it covers |
|---|---|
| [why_trust_ai_hybrid_intentframe.md](why_trust_ai_hybrid_intentframe.md) | Why the hybrid deterministic + AI model is trustworthy |
| [why_llm_guarding_llm_deep_dive.md](why_llm_guarding_llm_deep_dive.md) | Deep version: independence between agent and guardian LLMs |
| [why-not-injection-shield.md](why-not-injection-shield.md) | Why IntentFrame doesn't ship a dedicated injection shield |

### Root demo

| Doc | What it covers |
|---|---|
| [root_demo/PROOF.md](root_demo/PROOF.md) | Proof snapshot of the 100-attack sweep |
| [root_demo/executor-root-mode.md](root_demo/executor-root-mode.md) | Root execution mode, scoping, safety notes |
| [root_demo/root-policy-design.md](root_demo/root-policy-design.md) | The plain-English policy used in the demo |

### Terminal handling

| Doc | What it covers |
|---|---|
| [terminal_use/current_pragmatic_choice.md](terminal_use/current_pragmatic_choice.md) | Why terminal is treated as the universal surface |
| [terminal_use/current_terminal_policy_rationale.md](terminal_use/current_terminal_policy_rationale.md) | Reasoning behind current terminal policy |
| [terminal_use/current_deterministic_gates_mapping.md](terminal_use/current_deterministic_gates_mapping.md) | Which gates fire on which command shapes |

### Developer

| Doc | What it covers |
|---|---|
| [dev/action-family-wiring.md](dev/action-family-wiring.md) | How to wire a new action family end-to-end |

---

## Where deep implementation references live

A handful of references are kept inside the relevant module rather than in `docs/`, because they need to ship with the code and stay in sync with it:

| Reference | Lives in |
|---|---|
| Executor sandbox implementation | [`../executor/sandbox.md`](../executor/sandbox.md) |
| Executor implementation plan | [`../executor/plan.md`](../executor/plan.md) |
| Command Shield contract and capability tags | [`../command_shield/README.md`](../command_shield/README.md) |
| EDI design and configuration | [`../external_data_ingestion/README.md`](../external_data_ingestion/README.md) |
| Credential vault API and backends | [`../intentframe_credentials/README.md`](../intentframe_credentials/README.md) |
| Gateway service architecture | [`../intentframe_gateway/README.md`](../intentframe_gateway/README.md) |
| Jarvis assistant architecture | [`../jarvis_pa/README.md`](../jarvis_pa/README.md) |
| macOS platform server | [`../macos-appkit-server/README.md`](../macos-appkit-server/README.md) |
| Telegram bridge | [`../jarvis_telegram/README.md`](../jarvis_telegram/README.md) |
| CLI client | [`../intentframe_cli/README.md`](../intentframe_cli/README.md) |

The public-audience versions of these (in `docs/`) summarize what evaluators and integrators need to know; the module READMEs are the source of truth for engineers working on the code.

---

## Convention

- Docs in `docs/` are public-audience: anyone evaluating or integrating IntentFrame.
- Docs in `docs/_internal_/` are working notes — not part of the publish surface.
- Module READMEs (in `module_name/README.md`) are engineer-audience implementation references.
- When two docs cover the same topic at different depths, the public doc summarizes and links into the module README.

---

## Related top-level files

- [`../README.md`](../README.md) — project README (Why IntentFrame, getting started, demo, architecture overview)
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — contributor guidelines
- [`../SECURITY.md`](../SECURITY.md) — how to report security issues
- [`../LICENSE`](../LICENSE) — AGPL-3.0
