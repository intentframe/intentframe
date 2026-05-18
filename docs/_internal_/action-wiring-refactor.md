This is the classic "extensible runtime" problem. Every database, web framework, IDE, service mesh, CDN, and policy engine has solved a version of it. Here's the honest survey of what industry actually does, with concrete real-world examples, and how each applies to IntentFrame.

## The seven patterns that exist

### 1. Pure declarative / policy DSL (no partner code runs)

**Examples:**
- **OPA (Open Policy Agent) + Rego** — Kubernetes admission, Styra DAS, Netflix authz, ~7K production users. Partners write `.rego` files; OPA evaluates them. Sandboxed by design (Rego has no I/O, no loops over external data).
- **AWS Cedar** — Verified Permissions, used by Amazon, Strata. Specifically designed for permissions with formal verification.
- **CEL (Common Expression Language)** — Google's expression DSL, used in Kubernetes (`ValidatingAdmissionPolicy`), Envoy, gRPC, GCP IAM. Restricted enough to be safe and fast.
- **JSON Schema / OpenAPI** — Stripe, GitHub, basically every API gateway. Pure data validation.

**Mechanism:** partner writes constraints in a restricted language or schema; you ship the evaluator.

**Pros:** zero trust extended to partners; deterministic; small footprint; auditable.
**Cons:** can't express everything. Bashlex AST analysis, RFC-822 parsing, semantic similarity — these don't fit a DSL.

**Fit for IntentFrame:** strong match for Guardian constraint checks. Adding a Rego or CEL evaluator alongside `CONSTRAINT_CHECKERS` lets partners write `deny if input.intent.target.startswith("/etc/")` without shipping code. Cedar is purpose-built for this and would be the most narrowly-scoped choice.

### 2. HashiCorp go-plugin / RPC sidecars

**Examples:**
- **Terraform providers** — every cloud, every SaaS. 3000+ providers. Each is a separate Go binary; Terraform spawns it via `exec`, communicates over gRPC on a local socket. Crashes don't kill Terraform.
- **HashiCorp Vault** auth plugins, secret backends — same pattern.
- **Packer plugins**, **Nomad task drivers**, **Boundary plugins** — all use `go-plugin`.

**Mechanism:** host process spawns plugin process; bidirectional gRPC over Unix socket; plugin advertises capabilities via reflection.

**Pros:** real process isolation. Plugin can be any language (just speaks the protocol). Crash isolation. Versionable. Mature, ~10 years of production use.
**Cons:** RPC overhead per call (microseconds, but real). You design the protocol once and live with it. Need a versioning story (Terraform's plugin SDK has had three major rewrites).

**Fit for IntentFrame:** very strong match. You already have this pattern with `macos-appkit-server` (Swift sidecar over UDS). Generalizing it for partner adapters is the most "consistent with what you already built" path.

### 3. WebAssembly plugins

**Examples:**
- **Envoy WASM filters** — Istio service mesh, Solo.io Gloo. Partners ship `.wasm` modules; Envoy loads them into a sandboxed VM with strict CPU/memory limits.
- **Fastly Compute@Edge** — runs partner WASM at the edge. Cloudflare Workers uses V8 isolates (similar idea, different tech).
- **Shopify Functions** — partners customize checkout logic in WASM (Rust, JS, Go).
- **Extism** — open-source WASM-plugin framework with hosts in 15+ languages including Python.
- **Wasmtime / Wasmer** — runtimes.
- **Dylibso Xtp**, **Suborbital** — commercial WASM plugin platforms.

**Mechanism:** partner compiles plugin to WASM; host runtime loads into sandboxed VM with capability-based imports.

**Pros:** real sandboxing — memory-safe, no I/O unless host grants it, deterministic resource limits. Language-agnostic (Rust, Go, JS, Python via Pyodide). Hot-reloadable. Crashes contained.
**Cons:** newer than RPC sidecars; tooling/ergonomics still rough for Python hosts. WASM-Python via Pyodide is heavy. Each plugin call has marshal/unmarshal cost. Limited library ecosystem inside the sandbox.

**Fit for IntentFrame:** good for constraint checkers and AE-style semantic helpers where partner logic needs to run on every intent. Less ideal for adapter execute() where the action does real I/O (defeats the sandbox).

### 4. Webhooks (mutating/validating admission)

**Examples:**
- **Kubernetes admission webhooks** — partner runs an HTTPS service; K8s calls it on every API request, partner returns ALLOW/DENY/MUTATE. Used by Istio, Linkerd, OPA Gatekeeper, every cloud-vendor's policy product.
- **Stripe webhooks** — events pushed to partner's URL.
- **GitHub Apps** — partner runs an HTTPS endpoint; GitHub fires events at it.
- **CNCF Mutating Webhooks**, **Datadog Workflow Automation**, **Slack Events API** — same shape.

**Mechanism:** partner runs an HTTP service somewhere; host POSTs signed JSON; partner returns decision.

**Pros:** language-agnostic; can run anywhere (partner's cloud, their VPC); standard HTTP debugging; well-understood security model (HMAC signatures, mTLS).
**Cons:** network hop per call (10-100ms typical, not microseconds). Partner downtime breaks the host unless fail-open is acceptable (usually unacceptable for security).

**Fit for IntentFrame:** medium. Adding a webhook constraint checker is trivial ("if action_type is X, POST to partner URL for ALLOW/BLOCK"). The latency hit per action is real. Better as a complement than a primary mechanism.

### 5. Process-spawn + stdio JSON-RPC (LSP / MCP pattern)

**Examples:**
- **LSP (Language Server Protocol)** — VSCode, Neovim, Cursor, every editor. Every language extension is a separate process speaking JSON-RPC over stdin/stdout. Pyright, gopls, rust-analyzer, tsserver — all LSPs.
- **MCP (Model Context Protocol)** — Anthropic's standard for LLM tool servers. Each MCP server is a process speaking JSON-RPC; clients (Claude Desktop, Cursor) discover them via config.
- **DAP (Debug Adapter Protocol)** — same pattern for debuggers.
- **GitHub Copilot's chat extension protocol** — same shape.
- **Cursor, Continue.dev, Aider** — all consume MCP for their tools.

**Mechanism:** host spawns subprocess; bidirectional JSON-RPC over stdin/stdout; capabilities exchange via `initialize` handshake; tools/resources/methods declared in manifest.

**Pros:** trivially language-agnostic; subprocess discipline is well-understood; you already have a small surface area in `actor-sdk.md` that maps onto MCP-style protocols. Hot-spawn is fast (~100ms).
**Cons:** stdio framing is fiddly; partner has to handle process lifecycle properly.

**Fit for IntentFrame:** **highest practical fit.** Partners already ship MCP servers for agent tooling. You could literally accept MCP-server manifests as the source of partner action wiring: their MCP server already declares `tools` with JSON schemas; you treat each `tool` as an IntentFrame action, route execution through it, and Guardian validates against the declared schema. This piggy-backs on an ecosystem already growing fast in 2026.

### 6. Filesystem plugin directories (in-process)

**Examples:**
- **Postgres extensions** — `CREATE EXTENSION pg_vector;` loads a `.so`. Used by Supabase, Neon, Crunchy.
- **DuckDB extensions** — `INSTALL httpfs;`. Hot-loadable.
- **Apache Airflow providers** — pip-install + entry-point discovery.
- **pytest plugins** — entry points, ~1000+ on PyPI.
- **Jupyter kernels & extensions** — pip-install + manifest discovery.
- **Django apps**, **Flask extensions**, **Express middleware** — same pattern.
- **Webpack loaders**, **Rollup plugins**, **Vite plugins** — JS world.
- **Jenkins plugins**, **Maven plugins** — JVM world.
- **VSCode extensions** (non-LSP) — JS in extension host.

**Mechanism:** partner installs a package (pip, gem, npm, docker volume mount); host discovers via entry points or directory scan; loads into its own process.

**Pros:** lowest call overhead (in-process). Mature tooling.
**Cons:** partner code runs in your process. Their bugs, your incidents. Their dependencies, your version conflicts. **Violates your separation invariant.** This is the one I'd actively avoid.

**Fit for IntentFrame:** wrong fit. Your whole architecture argument is that partner code does not get trusted in the same process as the Guardian. Doing this would undo the moat.

### 7. eBPF / kernel hooks

**Examples:**
- **Cilium**, **Tetragon**, **Falco**, **Pixie** — kernel-level observability and policy.
- **Bottlerocket** OS, **Talos Linux**.

**Mechanism:** partner ships eBPF program; kernel verifies it; runs in kernel hook points.

**Pros:** ultimate performance; ultimate observability.
**Cons:** Linux-only; complex; not relevant for action-level agent runtime.

**Fit for IntentFrame:** wrong layer. Skip.

## The two real patterns nobody mentions but matter

### 8. Builder-time inclusion (OpenTelemetry Collector model)

**Example:** OpenTelemetry Collector Builder. Partners contribute Go modules; you ship a `manifest.yaml` listing which to include; CI builds a custom binary per deployment. Datadog Agent, Splunk OTel Distribution, ADOT all use this.

**Mechanism:** declare components in YAML, run `ocb build`, get a binary with exactly the plugins compiled in.

**Pros:** no runtime plugin overhead; full type safety; partner code gets reviewed at build time.
**Cons:** every customer effectively gets a custom binary; no hot-reload; build pipeline complexity.

**Fit for IntentFrame:** could work as the *enterprise* tier ("we'll build you a custom IntentFrame distribution including these MCP servers and these action bundles"). Not for OSS distribution.

### 9. Dapr Components (sidecar-with-pluggable-backends)

**Example:** Dapr's pluggable component model. Each component (state store, pub/sub, secret store) is a separate gRPC service. Dapr runtime delegates to whichever the user configured.

**Mechanism:** Dapr defines abstract interfaces (StateStore, PubSub) as gRPC; partners implement them; user configures which backend.

**Pros:** clean interface contracts; language-agnostic.
**Cons:** very specific to Dapr's architecture.

**Fit for IntentFrame:** the abstract-interface-as-gRPC-protocol idea is exactly what your CapabilityAdapter base class would become if you projected it across a process boundary.

## Honest comparison matrix

| Pattern | Trust model | Latency | Language-agnostic | Hot-reload | Real adopters |
|---|---|---|---|---|---|
| OPA/Rego, Cedar, CEL | Sandboxed DSL | <1ms | N/A (DSL) | Yes | K8s, AWS, Netflix |
| HashiCorp go-plugin / gRPC sidecar | Process isolation | 1-5ms | Yes | Spawn/respawn | Terraform, Vault |
| WASM plugins | VM sandbox | 0.1-1ms | Yes | Yes | Envoy, Fastly, Shopify |
| Webhooks | Network isolation | 10-100ms | Yes | Yes | K8s admission, Stripe |
| MCP/LSP stdio sidecar | Process isolation | 1-10ms | Yes | Spawn/respawn | Anthropic, every IDE |
| Filesystem in-process plugin | None (trusted) | <0.01ms | No (host lang) | Restart | Postgres, Airflow |
| Builder-time inclusion | Build-time review | 0ms | Limited | No | OTel Collector |
| eBPF | Kernel verifier | <0.01ms | C-ish | Yes | Cilium, Falco |

## What I'd actually pick for IntentFrame, ranked

Given:
- You're solo, can't operate multi-tenant cloud
- Trust boundary is sacred (architecture.md's separation invariant)
- Partners are AI-native B2B startups, not random pip-installers
- You already have UDS-based service architecture
- MCP is rapidly becoming the agent-ecosystem standard in 2026

**Rank 1 — MCP server as the partner extension format.**

Adopt MCP as the partner contract. Their action implementations ship as MCP servers (which they may already have written for ChatGPT/Claude Desktop/Cursor). IntentFrame's executor gains an MCP client that:
- Reads MCP server's `tools` list at startup or via runtime registration endpoint
- Maps each tool to an IntentFrame `ActionType` (with `Partner_X_SubmitNote`-style namespacing)
- Uses the tool's declared JSON Schema as the Guardian constraint
- Routes `actor.submit()` calls for those actions through MCP `tools/call`

You get the Terraform-provider ecosystem effect for free: every MCP server in the world becomes a candidate IntentFrame action. Your differentiation is that you wrap their tools with policy, semantic intent analysis, audit, and credential isolation — three things the raw MCP tool surface has none of (and a known weakness: the May 2026 MCP CVEs you cited).

**Rank 2 — OPA/Cedar/CEL for constraint expression.**

Pick one policy DSL for the cases where partners need to express constraint logic that goes beyond JSON Schema (cross-field predicates, threshold comparisons, regex). Cedar is the cleanest fit because it's purpose-built for permissions and has good Python bindings. Embed it inside Guardian as one of the `ConstraintChecker` implementations alongside the existing typed ones. Partners write Cedar policies in their action manifest; you evaluate.

**Rank 3 — WASM for sandboxed semantic helpers.**

If a partner needs custom Analysis-Engine-side semantic checks (e.g., "for our CRM, check that the note doesn't violate confidentiality classifications"), let them ship a WASM module that runs in the AE process with no I/O permissions. Extism is the simplest framework. Used by Dylibso production deployments, integrated into FluentBit, Ottoman, others.

**Rank 4 — Builder-time inclusion for enterprise tier.**

For deeply-integrated partners or design partners, build them a custom `intentframe-enterprise-${customer}` container image with their adapters compiled in at build time. This is your "+$30K/year managed deployment in your VPC" upsell.

**Explicitly avoid:**
- Python entry-points / filesystem in-process plugins (breaks separation invariant)
- Webhooks as primary mechanism (latency unacceptable for safety-critical path)
- Dapr-style component model (over-engineered for your scale)
- eBPF (wrong layer)

## The combined picture

```
┌─────────────────────────────────────────────────────────────────┐
│  IntentFrame substrate (your code, your trust boundary)         │
│                                                                 │
│  ActionRegistry  ── runtime POST /actions ── data only          │
│  PolicyRegistry  ── runtime POST /policies ── data only         │
│  Guardian        ── CONSTRAINT_CHECKERS + Cedar evaluator       │
│  AnalysisEngine  ── core prompts + optional WASM helpers        │
│  Executor        ── adapter registry                            │
│       │                                                         │
│       ├── built-in adapters (files, terminal, mail, …)          │
│       │                                                         │
│       ├── macos-appkit-server (your existing Swift sidecar)     │
│       │                                                         │
│       └── MCP client ◄─── partner MCP servers (over UDS/stdio)  │
│                              │                                  │
│                              ├── partner_crm.mcp                │
│                              ├── partner_slack.mcp              │
│                              └── partner_billing.mcp            │
└─────────────────────────────────────────────────────────────────┘
```

That picture is implementable in 2-3 months by a solo founder. Every box has industry precedent. Nothing requires inventing a new protocol. Partners ship MCP servers (which they're already writing) and Cedar policies (~20 lines for most cases) and get full IntentFrame substrate protection.

This is also the pitch that resonates with the agent ecosystem in 2026: **"IntentFrame turns any MCP server into a CISO-reviewable production action."** That sentence does both — claims a position no one else holds, and reuses an ecosystem standard instead of forcing partners onto your protocol.