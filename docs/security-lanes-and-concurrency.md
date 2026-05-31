# Security Lanes and Concurrency

> **Core Principle:** IntentFrame is an AI action firewall, not an async job runner. It prioritizes causal safety, perfect auditability, and deterministic evaluation over raw throughput.

This document explains why IntentFrame processes AI intents sequentially within a given environment, why the global `asyncio.Lock` is a load-bearing security feature, and how the system scales for B2B and enterprise use cases.

---

## 1. The Air-Lock Analogy

Most AI frameworks treat tool calls like web traffic: thousands of requests flowing simultaneously. That is fine for pulling weather data, but it is catastrophic for autonomous agents modifying infrastructure, code, or finances.

IntentFrame operates like a submarine air-lock. When an AI agent decides to act:
1. It enters the air-lock.
2. The outer door closes. **The system is frozen.**
3. IntentFrame inspects the action, evaluates the exact state of the environment, and verifies the policy.
4. Only when it is proven safe does the inner door open to execute the action.
5. The result is recorded, and the air-lock opens for the next action.

Yes, it processes one action at a time per environment. This is intentional. When an AI has root access to a Mac, or admin access to a Stripe account, you do not want maximum concurrency. You want absolute, provable, causal safety.

## 2. The Danger of Parallel Intents (TOCTOU)

If you evaluate and execute two intents in parallel, you create a classic security vulnerability called **Time-Of-Check to Time-Of-Use (TOCTOU)**.

Imagine an agent fires two intents in parallel:
* **Intent A:** Delete the file `invoice.pdf`
* **Intent B:** Read the file `invoice.pdf`

If processed simultaneously:
1. The Guardian evaluates A. (Is it safe to delete? Yes, it's a known file).
2. The Guardian evaluates B. (Is it safe to read? Yes, it's a known file).
3. They both execute at the exact same time.
4. **The result is a race condition.** Maybe B reads successfully, maybe it crashes because the file just vanished.

If an attacker controls the agent, they can intentionally fire overlapping intents to confuse security checks—tricking the Guardian into approving an action based on a file that is simultaneously being rewritten with malicious code.

**Security Rule:** You cannot confidently approve an action if the environment it operates on is shifting beneath its feet. The lock ensures the Guardian evaluates an intent against a stable, motionless world.

### Why intents are rarely truly independent

It is tempting to say "Intent A touches a file and Intent B sends an email — they are independent, run them in parallel." From an AI security perspective they are rarely independent:

* **Context is cumulative.** The LLM's decision to send the email was likely based on what it just read in the file. Evaluating B in parallel with A means B is evaluated before A's outcome is known to the system.
* **Audit trails require causal ordering.** A security auditor needs to read the log as a timeline: "The agent did X, which caused Y, so it decided Z." Parallel execution produces a scrambled timeline. You lose the ability to prove *why* the agent did something.
* **Blast radius containment.** A rogue agent firing 100 parallel intents is a Denial of Service attack on the protected environment. Forcing intents into a single-file line acts as an automatic throttle, physically limiting the blast radius of a compromised agent.
* **A compromised agent benefits from concurrency.** It can flood the system, create race conditions, obscure audit causality, and trigger conflicting operations. Serial execution is a containment boundary against a hostile agent.

The correct default posture is: **sequential unless independence is proven**, not parallel unless something breaks.

## 3. The Database Analogy: Strict Serializability

In computer science, databases solve this exact problem using **ACID** properties, specifically Isolation. When a bank transfers money, it locks the accounts to prevent "dirty reads."

IntentFrame acts as the Transaction Manager for the user's environment. But IntentFrame's job is harder than a database's:
* If a database transaction fails halfway through, it can just `ROLLBACK`.
* If an AI agent sends an email, deletes a production database, or posts a Slack message, **there is no rollback.**

Because there is no rollback in the real world, IntentFrame must use the strictest possible isolation level: **Strict Serializability**. It processes one transaction fully from start to finish before looking at the next one.

## 4. Security Lanes (How IntentFrame Scales)

We do not scale by removing the lock and running intents in parallel within a single process. We scale by adding **Security Lanes**.

A Security Lane is defined as: **One Runtime Process + One Executor Instance + One Environment.**

* **Parallel across isolated lanes.**
* **Sequential inside each lane.**

### B2B Scaling Models Today

1. **Single-Tenant Appliance:** One IntentFrame Core + One Executor service. Perfect for local users or small, isolated deployments.
2. **Tenant-Sharded SaaS:** Tenant A gets Core A, Tenant B gets Core B. They run in parallel because they share no physical environment.
3. **Workflow-Sharded Deployment:** Finance agents route to a Finance Core; Dev agents route to a Dev Core. This reduces blast radius and prevents a slow CI executor action from blocking a finance approval.

**What we do NOT do:** We do not run a single shared Core serving many tenants concurrently. That would cause noisy-neighbor problems, mix audit chains, and risk cross-tenant contamination.

### Lanes cannot be inferred from identity fields

`IntentFrame` carries `user_id`, `agent_id`, `session_id`. It is tempting to key a per-session or per-agent lock on these fields. That is a footgun.

A lane must be the boundary of the shared *environment* whose state an intent's safety depends on. That is a statement about **what gets touched**, not **who is asking**. Two sessions of Jarvis on the same Mac have different `session_id` values but share one physical filesystem. If you lock on `session_id` and run them in parallel, you reintroduce the exact TOCTOU race you were trying to prevent — silently, with no error.

Identity fields answer *who*. Safety depends on *what is being mutated*.

A generic IntentFrame core cannot compute the shared-resource boundary on its own because it is deliberately action-agnostic — it does not know that `WRITE_FILE` touches a disk or `RUN_COMMAND` touches the whole machine. Only two parties know the blast radius:
* **The bundle/executor author** — this action mutates these resources.
* **The operator** — this deployment governs this environment.

This is why the current model defines the lane at the deployment level (process + executor scope), not the identity level. If finer-grained lanes are ever needed, they must be **declared by the author** (e.g. resource scope tags on an action manifest), never inferred by the core from identity fields.

## 5. Structural Enforcement

The "one writer per environment" rule is not just a philosophy; it is structurally enforced by the OS.

* **Unix Domain Sockets (UDS):** The `executor.sock` is owned by one process. A second core cannot claim it.
* **PID Files:** If a second supervisor tries to start against the same `~/.intentframe/run/` directory, it detects the stale PID and kills it before binding.

You cannot connect two cores to one executor without the OS refusing the socket conflict. The enforcement is structural, not application-logic.

## 6. Summary of the Engineering Stance

* **Sequential Evaluation:** Principled, not an excuse. It guarantees frozen-context evaluation and causal auditability.
* **The Lock:** The `asyncio.Lock` must cover the *entire* lifecycle of the intent: `[ Acquire Lock -> Evaluate -> Decide -> Execute -> Await Result -> Release Lock ]`. Releasing the lock while an executor runs a background task would destroy the frozen context guarantee.
* **Scaling:** Deferred to horizontal deployment sharding (adding more lanes), which is the correct architecture for a zero-trust system.

IntentFrame is shipping a mathematically sound, race-condition-proof vault. We prioritize safety and perfect auditability over reckless speed.

---

## 7. When to Revisit This Decision

This is not philosophy hardened into dogma. The conditions under which this decision gets reopened are specific and observable. Until one of these is concretely true, the answer remains "keep the lock, scale by sharding":

1. **A paying customer's workload exceeds what sharding can absorb.** A new lane is always cheaper than a concurrency rewrite. Revisit only when sharding itself is the bottleneck.
2. **Latency for sequential intents (excluding LLM time) exceeds a measurable SLO.** Not "it feels slow" — a concrete, agreed number under a real workload.
3. **Multi-tenant SaaS with shared-process cores becomes a deliberate product bet.** Not "maybe someday" — an explicit architectural direction chosen for cost or product reasons.
4. **Long-running executions routinely block short ones in the same lane.** The correct fix for this specific case is a job-ID + async-result pattern for long actions, not blanket removal of the lock. Even then, the security decision remains sequential; only waiting on the execution result becomes async.

If one of these triggers arrives and you still do not act, *then* the decision has become an excuse. Until then, it is the right call.

### What to keep clean while waiting

These are low-cost disciplines that keep the future refactor tractable without building it now:

* Do not add new shared mutable state to long-lived engine objects (`last_*` style fields). Per-request data should flow as function arguments and return values.
* Keep audit writes funneled through one method/path. Scattered `audit_log.append(...)` calls make a future single-writer migration harder.
* Keep the executor behind its ABC. Do not add logic that assumes `execute()` is synchronous and serialized forever.
* Write concurrency tests *now* — they pass trivially because of the lock, and they become the safety net the day the lock is relaxed.
