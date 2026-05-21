# IntentFrame Refactor Abstract

IntentFrame should become an action-agnostic runtime substrate: the core engine should know how to process, authorize, audit, and route actions, but it should not own the list of possible actions.

The current system is not there yet. `ActionType` is a closed enum in `action_registry/types.py`, `IntentFrame.action` is typed to that enum in `intentframe_core/types.py`, and `intentframe_actor/actor.py` rejects unknown actions before the runtime can evaluate them. Adding a new action family still fans out across policy, guardian, prompt, executor, onboarding, tests, and Jarvis wiring.

The refactor goal is to invert that ownership model.

## Core Thesis

The runtime should process any registered action the same way it processes current actions today.

The core keeps:

- intent framing
- schema validation
- policy lookup
- deterministic checks
- semantic analysis
- guardian decisioning
- audit
- execution orchestration
- fail-closed behavior

The core loses:

- hardcoded action enum ownership
- bundled first-party action assumptions
- in-process customer action code
- Python-only actor protocol coupling
- action-specific drift across many internal lists

Today’s native actions should become first-party bundles, not privileged runtime concepts.

## Target Abstractions

Use one core engine for every profile: local consumer, developer, design partner, self-hosted org, and future SaaS/hybrid deployment.

The difference between profiles should be in installed bundles, policies, deployment topology, audit depth, RBAC, storage backends, and licensing. It should not be separate runtime forks.

Primary concepts:

- `ActionManifest`: versioned data declaration for one action.
- `ActionBundle`: package of one or more action manifests plus provider metadata.
- `ActionProvider`: external process/service that executes actions.
- `ActionRegistry`: registry of installed action manifests and provider endpoints.
- `AgentRegistration`: identity and declared needs of an agent.
- `PolicyGrant`: which agent/user/org may call which action under what constraints.
- `AuditEvent`: append-only event for every decision and execution step.

Action IDs should be namespaced and versioned, for example:

- `com.intentframe.local.read_file@1`
- `com.intentframe.local.run_command@1`
- `com.acme.crm.create_refund@2`
- `com.partner.billing.pay_invoice@1`

Policies should reference action IDs, not Python enum members.

## Actor SDK Boundary

The Actor SDK should be language-agnostic.

It should depend on a wire protocol, not IntentFrame Python modules. A TypeScript, Go, Java, or Python agent should be able to submit the same JSON request.

Actor should know:

- runtime endpoint
- handshake protocol
- submit protocol
- action IDs as strings
- request signing/auth
- JSON request/response schemas

Actor should not import:

- `action_registry`
- `ActionType`
- `intentframe_core`
- `policy_registry`
- domain-specific Python models

First milestone: make Actor submit arbitrary action IDs as strings and move protocol DTOs into a small protocol package.

## Bundle SDK Boundary

The Bundle SDK can be Python-only for v1.

It exists for bundle authors, not for the core engine. It can provide decorators, base classes, FastAPI helpers, test harnesses, manifest validation, local serve commands, and packaging templates.

The core should not import bundle Python code. Bundles run out of process and expose a manifest plus provider protocol.

A bundle should be able to declare:

- action ID and version
- display name and description
- input JSON Schema
- output JSON Schema
- risk metadata
- required credentials
- privacy/sensitive-field annotations
- rollback support
- sync or async-job behavior
- provider endpoint and health check
- compatibility requirements

## Provider Protocol

For v1, use request/response JSON over HTTP.

Local default transport should remain HTTP over Unix Domain Socket. That is the right default for local Mac/dev deployments because it avoids exposed ports and composes well with local supervision.

But the protocol should be transport-configurable:

- local single-user: HTTP over UDS
- local multi-worker: one public UDS router to multiple worker sockets
- enterprise/self-hosted: HTTP or gRPC over TCP with mTLS/JWT

The protocol should not be described as “UDS-only.” UDS is a transport binding, not the product contract.

## Runtime State Model

Engine workers should be mostly stateless.

Shared state should move behind stores/services:

- action registry
- agent registry
- policy store
- memory/idempotency store
- audit store

Local default can use SQLite plus a lightweight local memory service. Redis support should be available for multi-worker or deployed environments, but Redis should not be required for a local developer to start.

Redis-like state is for coordination, leases, sessions, rate limits, and idempotency. It should not be the only source of truth for policies, action manifests, or audit.

## Audit Target

Audit must become a system-level event ledger, not only executor-local logs.

Every lifecycle step should emit an event:

- intent received
- actor verified
- schema validated or rejected
- action manifest resolved
- policy version loaded
- deterministic checks run
- analysis/guardian decision made
- approval requested/granted/denied
- execution started
- execution completed/failed
- rollback registered/executed
- provider failure
- security event

Every event should include org/user/agent/session/intent/action/bundle/provider IDs, relevant versions, hashes of sensitive payloads, decision path, worker ID, previous hash, event hash, and eventually signature/checkpoint metadata.

Local mode can use SQLite append-only hash chaining. Org mode should support signed checkpoints, durable storage, and SIEM/export hooks later.

## What To Build First

Do not start with enterprise Kubernetes, SOC2 machinery, or a full plugin marketplace.

Start with the smallest refactor that proves the new abstraction:

1. Extract protocol DTOs/schemas into `intentframe-protocol`.
2. Decouple `intentframe-actor` from all runtime/core/action modules.
3. Replace `ActionType` usage at the Actor/Core boundary with string action IDs.
4. Define `ActionManifest` and `ActionBundle` schema.
5. Build a Python-only `intentframe-bundle-sdk`.
6. Convert one current first-party action family into an external bundle.
7. Add runtime action registration from bundle manifests.
8. Route execution through a provider endpoint instead of hardcoded adapter lookup.
9. Make Core-to-executor/provider execution async.
10. Start unified audit events for decision and execution.

The first converted action family should be boring and bounded. Pick one that proves manifest registration, policy grant, schema validation, provider execution, and audit without dragging in every hard problem at once.

## Non-Goals For V1

Do not create separate consumer, SMB, and enterprise cores.

Do not make `ActionType` a base abstract class that external actions subclass inside the runtime.

Do not load arbitrary partner Python code into the core process.

Do not solve multi-language bundle authoring in v1.

Do not require Redis, Kubernetes, mTLS PKI, SOC2 controls, or SIEM integration for the first local/developer milestone.

Do not build streaming tool-call output for LLMs. Long-running actions should use job IDs plus polling actions.

## Product Outcome

The desired end state is:

Any agent workflow can integrate with IntentFrame by speaking a small protocol and submitting namespaced action IDs.

Any developer or org can add capabilities by installing or connecting bundles.

IntentFrame remains the trusted substrate that evaluates intent, policy, risk, authorization, audit, and execution routing.

This lets the same engine support:

- a consumer running a local assistant on their laptop
- a startup installing a pip package and adding safe agent actions
- a design partner self-hosting in their own cloud/VPC
- first-party IntentFrame agents built quickly from business docs and bundle templates

The simplest sentence for the refactor is:

IntentFrame should not be the place where actions are hardcoded. It should be the place where registered actions become safe to use.