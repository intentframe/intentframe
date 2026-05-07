# Mental Models for IntentFrame

> **Pick the on-ramp that fits how you already think.**

IntentFrame is structurally simple but conceptually new: an AI agent acts on its own, but only *through* a pipeline that judges every action at the boundary where it would touch the real world. There is no perfect single analogy for this — every analogy gets some things right and some things wrong. So instead of forcing one official metaphor, this doc gives you several. Find the one that clicks, then read [autonomy.md](autonomy.md) for the precise thesis and [architecture.md](architecture.md) for the actual mechanics.

Each model below has the same shape:

- **Setup** — one or two sentences in plain language.
- **The mapping** — which real-world role corresponds to which IntentFrame component.
- **What it gets right** — the part of the system this analogy explains well.
- **Where it breaks** — what the analogy misleads about, so you don't over-extend it.

Reading order is from least-technical to most-technical. You can stop wherever it clicks.

---

## 1. The pharmacy / prescription system

> **Best for: anyone reading about IntentFrame for the first time.**

A doctor diagnoses a patient and writes a prescription. They cannot reach into a drawer and dispense medication directly — the pharmacy stands between the prescription and the patient. The pharmacy checks whether the prescription is valid, whether it interacts dangerously with other drugs, whether the dose makes sense, whether insurance covers it. Only then does the pharmacist dispense it.

```
DOCTOR (the agent)
   "Patient needs Medication X, 50mg daily"
                │
                ▼
PHARMACY SYSTEM (the IntentFrame pipeline)
   ├── Valid prescription?         (deterministic check)
   ├── Drug interactions?          (semantic review)
   ├── Within policy limits?       (Guardian decision)
   └── Within scope of practice?   (allowed actions)
                │
                ▼
PHARMACIST (the Executor)
   Dispenses the medication, logs the dispense
```

| Pharmacy world | IntentFrame |
|---|---|
| Doctor decides the treatment | Agent decides what to do |
| Doctor cannot hand pills to the patient directly | Agent has no direct I/O capability |
| Pharmacy validates the prescription | Pipeline validates the intent |
| Pharmacy checks drug interactions | Analysis Engine checks side effects |
| Pharmacist dispenses, logs the dispense | Executor performs the action, writes the audit record |
| Some drugs need a second signature | Some actions need user approval |

**What it gets right.** This is the cleanest picture of the *separation of concerns* and the fact that even an expert (the doctor) cannot bypass the validation step. The doctor is not assumed to be malicious — but medicine is powerful, and the pharmacy exists because mistakes happen even with well-intentioned, expert prescribers. Same with the agent.

**Where it breaks.** Doctors are licensed humans with personal accountability; the agent isn't. Pharmacies serve many doctors; an IntentFrame instance is dedicated to one user's policies. And in the real world the doctor *can* hand someone a sample — IntentFrame's separation is stricter than this.

---

## 2. The contractor in your office

> **Best for: anyone who has ever hired someone they only half-trusted.**

Imagine you hire a contractor to come into your office and do work. They're smart, useful, probably honest — but you don't fully trust them with everything in the building. They might make mistakes. They might be compromised (someone could have gotten to them). They might quietly try things they shouldn't.

So you don't give them the master key. They ask the security desk: *"Can I get into the filing cabinet?"* The security desk checks: is this contractor allowed in there at this time? If yes, someone with the actual key opens it for them.

| Office world | IntentFrame |
|---|---|
| Contractor (smart, useful, possibly compromised) | The agent |
| Security desk (checks the request against the rules) | Analysis Engine + Guardian |
| Person with the actual keys | Executor |
| Building access policy | User policy |
| Sign-in log at the front desk | Audit trail |

**What it gets right.** Captures the vernacular intuition: *"I want the work done, but I don't want them to mess up my stuff."* It also explains why "trust" here is structural, not personal — even a contractor with a perfect record goes through the security desk. It's not a judgment about them; it's a property of the building.

**Where it breaks.** A contractor has personal motivation, knows the rules, and could be argued with. An AI agent has none of that. Treating the agent like a person you can negotiate with leads to wrong design intuitions.

---

## 3. The accountant and the CFO

> **Best for: business buyers, ops leaders, anyone thinking about vendor lock-in.**

An accountant does the work — books, payments, reconciliations. The CFO doesn't do those tasks themselves. What the CFO does is set the rules ("no checks over $5,000 without a second signature; no payments to vendors who aren't on the approved list") and make sure those rules apply to *every* transaction, regardless of who the accountant is.

If you fire your accountant tomorrow and hire a new one — genius or intern, in-house or contractor — the rules don't change. The CFO stands at the door and checks every transaction before it leaves the company.

| Finance world | IntentFrame |
|---|---|
| Accountant (does the work) | The agent — interchangeable |
| CFO / compliance department (sets and enforces the rules) | IntentFrame |
| Approved-vendor list, signature limits | User policy |
| The CFO doesn't run payroll personally | The pipeline doesn't replace the agent's reasoning |
| New accountant, same rules | Swap GPT-5 → Claude → local model, same policies |

**What it gets right.** This is the cleanest way to explain why IntentFrame matters *commercially*: it turns the model itself into a swappable commodity, while governance stays stable. You're not locked into one vendor's safety filters. You're not re-auditing every time a new model ships. The rules live in *your* control plane, not the model provider's.

**Where it breaks.** Accountants and CFOs are humans with shared context and judgment. An agent can't read the room, ask "is this what you really meant?" or improvise around an unwritten norm. The IntentFrame analog is more rigid because the agent is more rigid.

---

## 4. The financial advisor and the brokerage

> **Best for: people who get stuck on "but the agent is the smart one — why should it be constrained?"**

A financial advisor analyses your portfolio, researches investments, recommends trades. They are the expert in the room. But the advisor cannot reach into your account and execute trades themselves. The brokerage is what touches the money. The bank validates the authority. The advisor's intelligence is real — and entirely routed through other systems' authorisation.

| Finance world | IntentFrame |
|---|---|
| Advisor — analyses, researches, recommends | Agent — reasons, plans, proposes actions |
| Bank — validates authority, checks limits | Guardian — applies policy |
| Brokerage — actually buys and sells | Executor — actually acts |
| The advisor's expertise is real | The agent's reasoning is real |
| The advisor's expertise doesn't bypass the bank | The agent's intelligence doesn't bypass the pipeline |

A close cousin: **air traffic control**. A pilot in command is the expert. They decide every input, every diversion, every emergency call. But they don't get to claim airspace, change altitude into traffic, or land at a closed airport just because they're expert. ATC validates clearance. Everyone — including the most experienced pilot in the system — requests and waits.

**What it gets right.** This dissolves the "but the agent is smart, isn't constraining it wasteful?" objection. Expertise has never been a license to bypass authorisation in any consequential profession. ATC doesn't second-guess the pilot's flying, and the pipeline doesn't second-guess the agent's reasoning. They authorise the *boundary crossing*, which is a different job.

**Where it breaks.** Pilots and advisors face personal liability that sharpens their judgment; the agent doesn't. So IntentFrame has to compensate by making the *structural* checks tighter than what humans rely on for human professionals.

---

## 5. The licensed professional

> **Best for: regulators, security architects, anyone asking "what is this *for*?"**

This is the canonical thesis — covered fully in [autonomy.md](autonomy.md). One-paragraph version:

Every consequential profession humans have ever built — surgery, aviation, finance, law, structural engineering — solved the same problem: how do you let someone act on your behalf, on their own initiative, without watching them do it? The answer was never "remove their autonomy." The answer was always *structural supervision*: pre-granted privileges (a license), scope-of-practice limits (you can do appendectomies, not heart transplants), pre-declared protocols (standing orders), peer review (M&M conferences), and post-hoc audit (malpractice law). The professional decides operationally; the structure bounds them structurally.

IntentFrame is that licensing-shape supervision layer for AI agents — the same pattern that already works for human professionals, brought into being for AI agents for the first time.

**What it gets right.** This is the most *honest* analogy because the mapping is structural, not aesthetic. Every component of IntentFrame has a real licensing-system counterpart, and the analogy survives detailed inspection. It's also the only analogy that correctly frames *autonomy* as the goal, not the threat.

**Where it breaks.** Licensing systems are slow-moving, jurisdictional, and rely on human judgment about edge cases. IntentFrame is fast, deterministic where it can be, and has to handle edge cases programmatically. The shape is right; the speed and substrate are different.

---

## 6. The fire and the safety engineer

> **Best for: anyone stuck in the "AI is hostile / adversarial" mental model.**

If you've been reading AI-safety discourse for the last few years, you've probably absorbed the *adversarial* frame: the AI is potentially scheming, trying to deceive, trying to escape. Under that frame, IntentFrame looks like a prison: walls to keep the prisoner in.

A more accurate frame: the AI is like fire.

Fire has no intentions. It's incredibly powerful, incredibly useful, and can cause enormous damage if it isn't contained. We don't assume the fire is "trying" to burn the curtains — fire just spreads, because that's what fire does when conditions allow. We build fireplaces, not fire prisons. We have fire codes, not fire trials. When something goes wrong, we send a fire department report, not a prosecutor.

| Fire world | IntentFrame |
|---|---|
| Fire is neutral capability, not malicious agent | AI is neutral capability, not malicious agent |
| Fireplace contains fire so it's useful | Executor contains agent action so it's useful |
| Fire codes regulate where fire can be | Policy regulates where the agent can act |
| Fire safety inspector checks the building | Analysis Engine checks the action |
| Fire marshal enforces the codes | Guardian enforces the policy |
| Fire department report after an incident | Audit trail |
| We prosecute the arsonist, not the fire | We hold the human deploying the agent accountable, not the model |

**What it gets right.** This pre-empts an entire wrong reading. You're not building anti-AI infrastructure. You're building *operational safety infrastructure for a powerful new capability*. The system makes sense even if you fully believe modern AI has no goals, no scheming, no hostility — because mistakes alone would still produce catastrophic outcomes without a structural boundary, exactly the way an unattended fire does.

**Where it breaks.** Fire is purely physical; AI agents are produced by a model whose training data, alignment, and prompt environment all matter. Fire can't be prompt-injected. So while the *neutral-capability* framing is right, the *threat surface* is broader than fire's: a hostile *human* can compromise the agent, and the system has to withstand that too. (Which it does — see [threat-model.md](threat-model.md).)

---

## 7. The OS kernel / syscall interface

> **Best for: systems engineers, OS people, anyone who instinctively reaches for "process boundary."**

In an operating system, user-space processes cannot touch hardware directly. They make *system calls* into the kernel. The kernel is the only thing that owns the keyboard, the disk, the network, the memory map. Each syscall is checked against permissions. Each is logged (or can be). User-space programs are powerful — they're where all the actual work happens — but the privileged operations route through one trusted boundary.

```
APPLICATIONS (user space)               AGENTS (the agent process)
   ↓ syscall                                ↓ Intent Frame
KERNEL (privileged ring)                EXECUTOR (only thing with credentials)
   ↓ touches hardware                      ↓ touches the real world
```

| OS world | IntentFrame |
|---|---|
| User-space process | Agent |
| Syscall ABI | Intent Frame schema |
| Kernel permission check | Guardian + deterministic gates |
| Kernel touches hardware | Executor touches real-world resources |
| `dmesg` / audit subsystem | Audit logger + hash chain |
| Capabilities, seccomp, MAC | Allowed actions, policy, sandbox profile |

**What it gets right.** This is the most precise systems-level analogy. It captures: (a) the agent isn't *less powerful*, it's *less privileged*; (b) the boundary is structural, not aspirational; (c) the audit is a kernel-style record, not an application log; (d) breakage of the boundary would require kernel-equivalent escalation, not just clever requests.

**Where it breaks.** Real OS kernels are mostly mechanical (`open` returns a file descriptor). IntentFrame's "kernel" includes a semantic-review layer — the Analysis Engine — which is *not* a syscall-style check. This is a real architectural difference, intentional, and discussed in [why_trust_ai_hybrid_intentframe.md](why_trust_ai_hybrid_intentframe.md).

A close engineering cousin: **the database engine vs. its workbench.** Workbench is the GUI most users see; the database engine (MySQL, Postgres) is what actually owns storage, auth, and the binary log. The agent is like the GUI; the Executor is like the database engine. See [executor.md § The mental model: an engine, not a workbench](executor.md#2-the-mental-model-an-engine-not-a-workbench) and [executor/standalone-product.md](executor/standalone-product.md) for the full development of these analogies.

---

## When the analogies disagree

You may have noticed these analogies sometimes pull in different directions:

- The **pharmacy** model treats the agent as a trusted-but-error-prone expert.
- The **contractor** model treats the agent as a smart-but-not-fully-trusted outsider.
- The **fire** model treats the agent as morally neutral — neither trusted nor untrusted, just powerful.
- The **kernel** model treats the agent as user-space — unprivileged by design.
- The **licensed professional** model treats the agent as operationally autonomous under structural bounds.

This isn't a contradiction. It's a sign that the actual system is doing several things at once:

| What IntentFrame is doing | Which analogy explains it best |
|---|---|
| Validating proposed actions against rules | Pharmacy, accountant/CFO |
| Containing damage from a compromised or confused agent | Contractor, fire |
| Routing privileged operations through a single boundary | Kernel, database engine |
| Enabling delegated autonomy | Licensed professional |
| Pre-empting the "AI is adversarial" frame | Fire |

Use the analogy that helps with the question you're trying to answer. Don't try to make one analogy do all the work — none of them can.

---

## What none of these analogies capture

A few things are unique to AI agents and don't have a clean real-world predecessor:

- **The agent is generated at runtime.** A surgeon's training is fixed; an AI agent's reasoning is produced fresh on every prompt. Validation has to handle decisions that don't exist until the moment they're made. This is the part of IntentFrame that traditional code review, static analysis, and licensing all *cannot* solve. See [principles.md § 1](principles.md#1-intentframe-supervises-ai-decided-actions-not-all-code).
- **The agent can be prompt-injected.** Fire can't be talked into burning the curtains. Doctors can't be social-engineered through the patient chart. Agents can. The threat model has to handle this explicitly. See [threat-model.md](threat-model.md).
- **Capability changes faster than policy.** Models gain new abilities every few months. Pharmacy regulations and fire codes evolve over decades. IntentFrame's structural supervision has to be cheap to update without re-architecting. See [principles.md](principles.md).

These are the parts of the design that *don't* show up in any human-system analogy because humans haven't faced the same problem before. They're also the parts that make IntentFrame actually new infrastructure rather than a rebrand of existing security tools.

---

## Related Documents

- [autonomy.md](autonomy.md) — the canonical thesis: delegatable autonomy and the licensing analogy in full
- [architecture.md](architecture.md) — the actual mechanics behind these analogies
- [principles.md](principles.md) — the structural invariants
- [threat-model.md](threat-model.md) — what the boundary protects against
- [executor.md](executor.md) — the database-engine and OS-kernel analogies developed for the executor specifically
- [faq.md](faq.md) — common questions and objections
