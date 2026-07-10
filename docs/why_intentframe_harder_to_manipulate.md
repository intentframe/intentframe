## Why IntentFrame Is Harder to Manipulate

AI agents are vulnerable because being helpful is their job. They must read emails, documents, websites, and user messages, then use that information to complete tasks. Unfortunately, malicious instructions can arrive through those same channels.

IntentFrame changes the security model.

### 1. The agent helps; IntentFrame judges

The agent is expected to cooperate with users and external content. IntentFrame has no customer to satisfy and no task to complete.

Its only job is to ask:

- What is the agent attempting to do?
- Does the action match the stated purpose?
- Is it permitted by the business’s policy?
- What damage could it cause?

This removes the conflict between being helpful and enforcing security.

### 2. The agent cannot approve its own actions

Putting security instructions inside an agent makes the same AI both:

- the employee requesting an action, and
- the security officer approving it.

If the agent is manipulated, both roles can fail together.

IntentFrame separates them. The agent proposes an action; an independent system evaluates it before execution. This resembles payment approval, code review, and maker-checker controls used in banks.

### 3. IntentFrame does not trust the agent’s explanation

Every action includes a reason, but IntentFrame treats it as an untrusted claim—not as proof.

It compares:

- what the agent says it wants to do,
- what the proposed action will actually do,
- what the business policy permits,
- and the action’s scope, risk, and reversibility.

A plausible explanation cannot make an inconsistent action safe.

### 4. External content is evidence, not instruction

A malicious email or document may reach IntentFrame, but it arrives as untrusted evidence attached to an action request.

IntentFrame is not supposed to obey that content. It evaluates whether the content has manipulated the agent into proposing an inappropriate action.

### 5. IntentFrame has different information

The Guardian receives information the agent cannot control directly, including:

- deterministic analysis of the action,
- detected capabilities and system effects,
- execution privileges,
- an independent risk assessment,
- business policy and hard limits.

It therefore reviews the agent’s request using a forensic dossier, rather than relying on the agent’s story.

### 6. Security does not depend on one AI decision

IntentFrame uses multiple layers:

1. The agent proposes an action.
2. Deterministic controls check hard rules.
3. The Analysis Engine explains the action’s effects and risks.
4. The Guardian evaluates authorization and policy.
5. The executor enforces runtime and sandbox limits.
6. The action and decision are recorded for audit.

Approval requires the relevant layers to agree. A block from a hard policy rule cannot be overridden by the AI.

### 7. It supports business rules, not only technical restrictions

Traditional permissions can answer:

> “Can this application issue a refund?”

IntentFrame can also evaluate:

> “Is this refund appropriate for this customer request, and must it return to the original payment method?”

This allows businesses to express controls in ordinary operational language while retaining deterministic limits for amounts, destinations, paths, and permitted actions.

### 8. It reduces the human approval burden

Without purpose-aware review, businesses must either:

- trust the agent broadly,
- block useful automation, or
- ask a human to approve every meaningful action.

IntentFrame automatically decides clear cases and escalates only genuinely ambiguous or high-risk requests. This makes greater agent autonomy practical without giving the agent unchecked authority.

## The honest security claim

IntentFrame should not claim that it “cannot be hacked.” No LLM-based system can honestly guarantee that.

The defensible claim is:

> IntentFrame assumes that agents can be manipulated. It prevents a manipulated agent from automatically gaining unchecked execution by moving authorization outside the agent, evaluating every proposed action against independent evidence and policy, and enforcing hard limits through non-AI controls.

In simple terms:

> The agent is the requester. IntentFrame is the independent reviewer. The executor is the enforcement point.

IntentFrame does not need to trust the agent, believe its explanation, or help it complete its task. It only needs to determine whether the proposed real-world action is authorized.