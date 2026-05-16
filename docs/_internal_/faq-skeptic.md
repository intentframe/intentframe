# IntentFrame Skeptic FAQ

Hard questions from a skeptical developer who knows they could build this themselves in a weekend. Honest answers without marketing.

---

## Q1. Isn't IntentFrame just a different kind of sandboxing?

Yes — in the broad sense that it constrains what an agent can affect.

But "sandboxing" is a family of techniques that are not interchangeable:

- **OS-level capability sandboxing** (Seatbelt, seccomp, namespaces, VMs) — the kernel decides what a process can do. Coarse, strong, hard to express semantic policy in.
- **API-surface sandboxing** (browser JS, WASM) — the host exposes only allowed operations. Strong, but you have to design the entire API surface up front.
- **Intent mediation with a separate trusted actor** — what IntentFrame is. Policy + IPC + an isolated executor that holds credentials.

The Seatbelt sandbox under `RUN_COMMAND` is the first kind, used as a fallback safety net. The primary mechanism is the third kind. Both exist in the architecture simultaneously.

IntentFrame also does bi-directional protection:

- **Protects the user from the agent** — blocks unauthorized actions before execution.
- **Protects the agent from its own mistakes** — stops an LLM hallucinating a destructive action it didn't really intend.

The accurate framing: IntentFrame is a **policy-mediated intent gateway with an isolated actor**, and it uses OS sandboxing only as a backstop underneath.

---

## Q2. Why can't I just call `validate(action)` in my tool body and execute however I want?

You absolutely can. Most "guardrails" libraries work this way. The question is what your validator buys you against which threats.

**Where inline validation is genuinely sufficient:**

- Honest agent making mistakes in a controlled environment
- Single team, vetted tool set, no untrusted content in prompts
- Threat model is "prevent accidents," not "prevent attacks"

**Where inline validation fails structurally:**

1. **The verdict is just a return value.** "If validator says no, do nothing" is enforced by code discipline. Anything in your process — a forgotten `if`, a compromised dependency, a refactor that swaps `&&` for `||`, an exception handler that falls through — can ignore it. With a separate executor, the agent process has no other path to credentials/sockets/file descriptors.
2. **Intent ≠ implementation.** When `validate({SEND_EMAIL, to: alice})` returns OK and the tool then calls `smtp.send(...)`, nothing guarantees the validated payload matches what was sent. The tool might validate one payload and execute another (accidentally or via injection). With a separate executor, the validated structured intent is the unit that travels and gets executed.
3. **Credential reach.** For in-process execution, the agent process holds credentials. Any reflection path (`os.environ`, `__import__('keyring')`, `ctypes`, a malicious transitive dependency) can siphon them. With a separate executor, the LLM-adjacent process never held the credentials. This is an address-space property, not a code-discipline property.
4. **Tool authors are the weakest link.** Inline validation pushes the burden onto every tool author: call validate, branch on result, ensure args match, write audit, catch exceptions, don't leak creds. N tools = N places to get it wrong. Out-of-process execution turns "did you call the validator correctly?" into "did you submit an intent at all?" — and there's no other interface.

**Useful analogy:** inline validation is to the separate executor what client-side `if (user.isAdmin) deleteUser()` is to a server-side authorization check. Both look like they do the same job until an attacker calls the underlying primitive directly.

---

## Q3. The executor is just deterministic code — why does the process boundary matter?

Determinism describes what code computes. Processes describe what code is allowed to touch and who can interfere with it. Those are orthogonal.

`rm -rf /` is deterministic too. What matters about a separate process isn't that it computes differently — it's:

1. **Address-space isolation.** Different process = different virtual memory. The agent cannot mutate the executor's policy module, replace its function table, monkey-patch its sender, or read its credential cache. In Python especially, `sys.modules`, `gc.get_objects()`, attribute reflection, and import hooks make in-process "isolation" fictional.
2. **Distinct OS-level identity.** The executor can run under a different Seatbelt/AppArmor profile, different UID, different TCC-granted identity. You cannot apply different OS privileges to two function calls in the same process.
3. **The serialization contract is itself the enforcement.** IPC forces every cross-boundary value to be serializable and fit a schema. The executor cannot be talked into "just run this callback the agent gave me" because there's no representation of that which crosses the wire. Structural anti-confused-deputy property.
4. **Policy and audit integrity.** Policy is loaded once, in the executor, in memory the agent can't reach. `policy.allow_all = True` from the agent process does nothing — that mutation isn't shared across processes. Audit records are written by the executor; the agent can't suppress or forge them.
5. **Failure containment.** Agent crashes, OOM, infinite loops — none take the executor down. Audit keeps flowing.
6. **Credential carrier.** Credentials only live in the executor's environment/keychain. Process boundary = credential boundary.

---

## Q4. I can build this myself in an hour — subprocess for tools, a skeptical-agent monitor, deterministic validation, credentials in env. Why use IntentFrame?

For a single agent with a known tool set in a controlled environment, **you are right and should probably build it yourself.** IntentFrame does not try to convince you otherwise for that case.

What IntentFrame buys over DIY — honestly:

1. **A red-teamed attack corpus.** 100 attacks, 9 initially missed, fixed, re-run. That failure-then-fix iteration is the thing your hand-rolled monitor has not been through. Most homegrown "skeptical-agent monitors" pass a few obvious tests and silently miss ARP spoofing, time-sync hijacks, base64 indirection, and unicode smuggling. The value is not the architecture; it's the **attack/defense iteration you've already paid for.**
2. **A shared pattern across multiple agents.** If your company will eventually have 1 agent, build it yourself. If it will have 5+ (and almost every company will, within 18 months), you want one runtime, one audit chain, one policy surface, one place a security team can review — for the same reason no one runs five different authentication systems in production.
3. **A policy vocabulary that survives refactors.** A homegrown "if-this-then-that" check drifts. A framework with a real policy DSL (even an imperfect one) tends to keep its invariants over time. This is the same argument for using a real authz library vs. hand-rolled `if user.role == 'admin'` scattered across a codebase.
4. **Audit chain integrity.** "Subprocess + log writes" doesn't get you a tamper-evident hash chain. You can build one. Most teams don't.
5. **Outsourced security research labor.** Every new attack class published, every new prompt-injection trick, becomes someone else's problem to add to the corpus. That's the same reason you don't write your own crypto or your own OAuth library.

---

## Q5. "Credentials in env are already low risk" — right?

Wrong comparison. Environment variables are "less risky" compared to hardcoded secrets in source. The relevant comparison is:

- **In-process (any mechanism — env, keyring, vault SDK):** anything in your process can read them. `os.environ.get`, `__import__('keyring')`, any dependency, any prompt-injected eval path. Memory dumps, log frameworks, stack traces routinely leak them. `ps eww` shows env on many systems. A prompt-injected agent that emits `subprocess.run("env", capture_output=True)` exfils them in one line.
- **Out-of-process (agent never had them):** the agent's exfiltration surface is zero, regardless of what code the LLM is convinced to emit.

The threat model where this matters is **prompt injection that gets the agent to emit credential-exfiltrating code**, not "developer accidentally committed a key to git." Env vars protect against the second. They do nothing for the first.

If your agents never read external content (email, web, docs, user-uploaded files), the prompt injection risk is low and env is fine. If they do read external content — and most useful agents do — you're one injected instruction away from `os.environ` in a tool call.

---

## Q6. Who actually needs a unified runtime and policy surface?

**Genuinely needs it (will pay for it):**

- Enterprises running multiple agents across teams — security team needs one audit point, not N.
- Regulated industries (finance, healthcare, legal, defense) — compliance can't sign off on per-agent ad-hoc validators.
- Platforms hosting third-party agents — the operator needs one runtime they trust regardless of who wrote the agent.
- IT-managed device fleets — admin wants policy on what AI can do across all managed devices.
- Robotics / industrial automation — physical safety certification regimes effectively require structural separation already.
- Consumer product companies that will be sued when an agent harms a customer's data — audit chain as legal defense.

**Doesn't need it:**

- Solo developer running a personal agent.
- Single-team internal automation with one agent.
- Hobbyists, research projects, demos.
- Any team where DIY + a few hours of validation covers their threat model.

---

## Q7. Don't consumers need protection too?

Consumers absolutely need protection. Every person running ChatGPT desktop, Claude, Cursor, or a browser agent is exposed to the same threats. The need is real.

What's different is the commercial shape. Consumers don't buy "unified runtime" or "policy surface" or YAML files. They buy outcomes:

- "My files are safe"
- "The AI won't email my boss by accident"
- "My passwords stay private"

A consumer-facing IntentFrame would be a different product on the same engine: a menu bar app, three preset policies (Strict/Balanced/Permissive), toggles instead of YAML, local-only by default. The *kernel* is the same; the *shell* is completely different.

---

## Q8. Why should critical adapters (finance, medical, legal) not be no-code?

They shouldn't. The "anyone can onboard any action with no code" pitch is dangerous when applied uniformly. Critical actions need professional engineering, not convenience.

The correct model is **tiered adapters**:


| Tier              | Examples                                                                       | Authoring                                                           | Review                              |
| ----------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------- | ----------------------------------- |
| **Low-stakes**    | Read public APIs, summarize, search                                            | Natural language / community-contributed                            | Casual                              |
| **Medium-stakes** | Internal API writes, calendar mutations, low-value transactions                | YAML/DSL from templates, hand-reviewed                              | Maintainer review                   |
| **Critical**      | Payments, medical records, legal filings, identity changes, physical actuation | Professionally authored, formally specified, version-pinned, signed | Code review + certification + audit |


The runtime should enforce tiering **structurally**:

- Critical adapters live in a separate signed bundle, loaded only at executor startup, immutable at runtime.
- Critical intents fail closed if any gate is uncertain — no "the LLM thought it was fine" override.
- Critical actions require dual-control (human-in-the-loop) by default.
- Critical adapter changes go through a separate review path.
- Audit records for critical actions have stronger guarantees (synchronous write, append-only storage).

This mirrors what finance already does: STP for small transactions, human review for large, dual approval for very large. The marketing story is stronger this way:

> IntentFrame lets you onboard low-stakes tools without engineering effort while keeping critical adapters under formal specification, code review, and dual control. Same runtime, two enforcement paths, no shortcuts on the things that matter.

---

## Q9. Can IntentFrame work for physical robots or smart devices?

**The pattern, yes. The current code, no.**

Physical robotics is actually the most compelling use case — consequences are physical, often irreversible. ROS and AV stacks already separate planning from actuation. What's new with LLMs is that the planner is non-deterministic, so the gate needs semantic checking.

But: current Python + macOS + 10-second OpenAI round-trips is not robot-ready. A robotics profile would need:

- Deterministic gates only in the hot path (no LLM blocking actuation)
- Policy compiled to a state machine ahead of time
- Semantic review on a supervisory loop (reviewing plans, not gating each motor command)
- Memory-safe systems language, hard real-time guarantees

For IoT/smart devices: constrained hardware can't afford the full pipeline. Edge appliances with real compute (smart speakers, hubs, AI cameras) can run a stripped-down deterministic-only profile. Tiny devices cannot.

For LLM-driven physical agents (Figure, Optimus, RT-2): regulators will eventually require something like an intent gateway between the AI brain and actuators. Positioning as the reference architecture before regulators write their own is a long game (3-5 years) but a real one.

---

## Q10. What is IntentFrame today — honestly?

Three things, in decreasing order of completeness:

1. **A crystallized architectural pattern.** "Separate the reasoner from the actor; mediate through structured intents; keep credentials out of the LLM process; gate semantically, not just syntactically." The pattern is more valuable than the code right now.
2. **A reference implementation for a narrow profile.** macOS + Python 3.14 + OpenAI + a hand-curated action registry + Jarvis as the canonical agent. It works. The root-demo result is real evidence. But it's a demo of the pattern, not a general-purpose middleware.
3. **A working alpha product for one user shape:** someone on Apple Silicon who wants a personal assistant with strong policy controls and is willing to write YAML.

The honest assessment: closer to "thesis with code" than "product." That's not bad — Linux started that way — but the gap between the thesis and a general-purpose adoptable product is the work ahead.

---

## Q11. What would make IntentFrame generally adoptable?

In priority order:

1. **Generic protocol adapters** — MCP bridge, OpenAPI bridge. If every MCP-compatible agent routes through IntentFrame with zero custom code, TAM goes from "Jarvis users" to "everyone running an MCP-aware agent."
2. **Linux + Windows support** — macOS-only kills enterprise.
3. **Local model support** — OpenAI-only dependency kills regulated industries.
4. **Adapter tiering** (Q8) — formal separation between critical and casual action types.
5. **Natural-language policy authoring** with YAML as the export format, not the authoring format.
6. **Stateful/cumulative policy** — closes the salami-slicing gap.
7. **Third-party security audit** — enterprise buyers discount first-party claims by an order of magnitude.
8. **Drop-in proxy mode** for existing frameworks (LangChain, OpenAI Agents SDK, Anthropic tool use). One config line, zero adapter writing.

---

## Related Documents

- [docs/faq.md](faq.md) — primary FAQ (security and architecture focus)
- [docs/threat-model.md](threat-model.md) — full threat model
- [docs/executor.md](executor.md) — executor design
- [docs/actor-sdk.md](actor-sdk.md) — integration guide
- [docs/single-runtime.md](single-runtime.md) — unified runtime argument
- [docs/autonomy.md](autonomy.md) — the delegatable-autonomy thesis

