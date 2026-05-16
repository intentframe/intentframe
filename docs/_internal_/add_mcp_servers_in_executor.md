I pulled the actual numbers. The MCP ecosystem in 2026 is much bigger than you might be assuming, and the answer changes depending on what "integration" means.

## The raw ecosystem in 2026

- **4,923 servers tracked** on BenchGecko
- **3,000+ servers** on MCP.Directory
- **2,002+ servers** on MCP Marketplace
- **775+ verified servers** on MCPList.ai
- **500+ in the official community registry**
- **~70 considered "production-ready"** for real workflows
- **7 official reference servers** from Anthropic (Filesystem, Fetch, Git, Memory, Sequential Thinking, Time, Everything)
- **25+ remote HTTP-hosted servers** as of April 2026 (no local install needed): Supabase, GitHub, Notion, Stripe, Figma, Sentry, Neon, Atlassian, HubSpot, Linear, Slack, Vercel, Cloudflare, Ahrefs, Semrush, PayPal, and more

This is no longer a "should I bet on the ecosystem" question. The ecosystem is here, dense, and growing.

## How fast can your Executor onboard them?

It splits into a one-time cost and a per-server cost.

**One-time cost (paid once, not per integration):**
- Build the MCP client transport into your Executor (stdio + HTTP/SSE).
- Build the schema importer that reads `tools/list` from an MCP server and generates IntentFrame intent types from the tool schemas.
- Build the tier classifier (auto-tag tools as low/medium/critical based on heuristics — reads vs writes, money keywords, file-system writes, network destinations).
- Estimated effort: **1–3 days** of focused work for someone who knows your codebase. Not 1 hour. But you pay this once.

**Per-server cost after the plumbing exists:**

| Tier | Examples | Per-server time | Throughput per hour |
|---|---|---|---|
| **Low-stakes** (reads, public data, idempotent) | Filesystem (read-only mode), Fetch, Time, Memory, Sequential Thinking, DuckDuckGo, Context7, Bright Data SERP, Tavily | ~5–10 min: install, auto-generate intents, default policy | **6–12 per hour** |
| **Medium-stakes** (writes to user systems, internal APIs, small money) | GitHub, Linear, Notion, Atlassian (Jira/Confluence), Slack, HubSpot, Playwright, Mem0, Tableau, Sentry, Terraform | ~15–30 min: install, generate intents, review policy stub, light hand-tuning | **2–4 per hour** |
| **Critical-stakes** (payments, identity, irreversible) | Stripe, PayPal, Plaid (when MCP available), QuickBooks, AWS write APIs, anything money-moving | Hours to a day each: hand-author the policy + critical-tier AE body + sign + certify | **<1 per hour** — should not be batched |

## So the realistic 1-hour answer

Once the plumbing is in place, **you can onboard roughly 6–12 low-stakes MCP servers per focused hour, or 2–4 medium-stakes ones, or 0–1 critical-stakes ones (with human review).**

If you commit one focused person-day (8 hours) post-plumbing to a "ship the obvious adapter library" sprint, a realistic outcome:
- Day 1 morning: official 7 reference servers wired (Filesystem, Fetch, Git, Memory, Sequential Thinking, Time, Everything).
- Day 1 afternoon: GitHub, Linear, Notion, Slack, Atlassian, Playwright, HubSpot, Sentry — 8 medium-stakes integrations.
- Day 2: Stripe (critical, hand-authored policy + AE body). One critical integration done properly.

End of two days: **~15 MCP-backed action surfaces live, including one money-moving one done right.** That's a credible "we cover the indie operator's tool stack out of the box" launch story.

## The really important point — match against your actual customer

Recall the 20 indie-operator workflows we identified earlier. Map them against existing MCP servers:

| Indie-operator workflow | MCP server(s) that already exist |
|---|---|
| 1. Inbox triage + reply drafting | Gmail MCP (community), Outlook MCP, IMAP MCP |
| 2. Multi-platform social posting | Twitter/X MCP, LinkedIn MCP, multiple community social MCPs |
| 3. Lead enrichment | **HubSpot MCP, Bright Data MCP, Apollo MCP** |
| 4. Sales follow-up | **HubSpot MCP, Pipedrive MCP**, Email MCPs |
| 5. Invoice monitoring | **Stripe MCP**, QuickBooks MCP |
| 6. Vendor tracking | QuickBooks MCP |
| 7. Content drafting + WordPress publish | **WordPress MCP**, Notion MCP, Fetch MCP |
| 8. Customer support tier-1 | Zendesk MCP, Intercom MCP |
| 9. Client onboarding (multi-step) | **Email + Calendar + Stripe + CRM MCPs in sequence** |
| 10. Meeting summaries | Fetch / transcript + LLM — generic |
| 11. Calendar coordination | **Google Calendar MCP, Cal.com MCP** |
| 12. Build-in-public content | Twitter/X MCP, LinkedIn MCP |
| 13. MRR / financial reporting | **Stripe MCP, Plaid MCP (where available)** |
| 14. Bug triage + GitHub PR review | **Official GitHub MCP** (28.8K stars) |
| 15. Competitor / market intel | **Bright Data MCP**, Playwright MCP, Tavily |
| 16. CRM updating | **HubSpot MCP, Salesforce MCP, Attio MCP** |
| 17. Content summarization at scale | **Fetch MCP** (official), Playwright |
| 18. Cross-platform messaging triage | **Slack MCP** (official-hosted), WhatsApp community, Telegram community |
| 19. Outbound prospect outreach | Apollo MCP, Email MCPs |
| 20. Status report generation | **Linear MCP + GitHub MCP + Stripe MCP + Notion MCP** (composition) |

**Match rate: roughly 18 of 20 workflows have at least one mature MCP server today.** The remaining gaps (WhatsApp at scale, some niche social platforms) have community-built MCPs of varying quality.

This is the key insight you should internalize:

**The MCP ecosystem has effectively pre-built the adapter library you would otherwise have had to write.** When you adopt MCP-as-backend in your Executor, you go from "adapter tax = N person-years" to "adapter coverage on day one = 90% of indie-operator workflows." That's not following the crowd. That's recognizing that the crowd built the warehouse you would otherwise have had to build yourself, and your job is to put your policy boundary in front of it.

## Concrete launch implication

Two weeks of focused work, roughly:
- Days 1–3: Build MCP-client capability into the Executor (one-time plumbing).
- Days 4–6: Onboard the 7 official reference servers + GitHub + Linear + Notion + Slack + HubSpot + Atlassian (medium-stakes, auto-onboarded with light review).
- Days 7–10: Hand-author critical-tier integration for Stripe (with full policy + AE body + signing flow). This becomes your template for future critical-tier servers.
- Days 11–14: Schema importer + tier classifier + "drop in any MCP server" wizard, so a user can install a new MCP server in their menu bar and IntentFrame auto-generates the low/medium tier intent surface with one confirmation.

End state: **launch with ~15 working integrations and a one-click "install any MCP server" capability.** That's a credible product story for the indie-operator wedge, not a roadmap promise.

## The architectural framing that matters

To restate the previous turn precisely: this works because **the agent never sees MCP**. The agent submits intents to IntentFrame; Guardian validates; Executor, holding credentials and acting as MCP *client*, invokes the MCP server. The MCP server runs in its own process with its own credentials (often the same machine, sometimes hosted). The agent's process never touches the MCP transport, never holds the credentials, and cannot bypass.

You inherit the ecosystem. You do not inherit MCP's "trust the server" model — your Executor sits between policy and the MCP server, and the Executor decides whether to invoke at all.

That's why I think this is unusually clean. Most "follow the crowd" tradeoffs require sacrificing something architectural. This one doesn't.

Three deployment models — and the answer affects your threat model directly.

## The three places MCP servers actually run

**1. Local stdio (most historical, most common for filesystem/dev tools)**

- Server is a subprocess spawned by the MCP client (in our case, the Executor).
- Communicates over stdin/stdout — no network at all.
- Runs entirely on the user's machine.
- Credentials live as env vars or config files on that machine.
- Examples: official Filesystem, Fetch, Git, Memory, Time, Sequential Thinking. Most community-built servers also follow this pattern.

**2. Local HTTP / SSE (less common, used during development or by some standalone tools)**

- Server runs as a long-lived process on the user's machine, listening on `localhost:port`.
- Same trust boundary as stdio (everything is on the user's device) but communicates via HTTP rather than pipe.
- Used when a server wants to be shared across multiple clients or needs to survive client restarts.

**3. Remote HTTP / SSE (the big 2026 shift)**

- Server runs on the **vendor's** infrastructure.
- Authentication via OAuth, with the executor (or whatever MCP client) holding a short-lived token.
- As of April 2026, the following vendors run hosted MCP endpoints: **Stripe, GitHub, Notion, Linear, Slack, Atlassian, HubSpot, Vercel, Cloudflare, Ahrefs, Semrush, PayPal, Sentry, Neon, Supabase, Figma** — and the list is growing fast.
- This is the trend everyone is moving toward because zero local installation = much easier adoption.

## Rough breakdown of where today's popular servers live

| Category | Where it runs | Examples |
|---|---|---|
| Filesystem / Git / system tools | **Local stdio** | Official Filesystem, Git, Fetch, Memory, Time |
| Dev environment integration | **Local stdio** | Playwright, E2B Sandboxes (hybrid), Terraform |
| Web scraping / search | Mixed | Bright Data (remote), Tavily (remote), DuckDuckGo (local) |
| SaaS tools (the long-tail of business apps) | **Increasingly remote** | GitHub, Stripe, Notion, Linear, Slack, HubSpot, Atlassian, PayPal — all hosted by vendor |
| Memory / knowledge tools | Mixed | Mem0 (remote), local Memory server (stdio) |
| Databases | Mixed | Supabase (remote), Neon (remote), local Postgres servers (stdio) |

If you sample the top 25 most-installed servers in 2026:
- Roughly **40% are local stdio**
- Roughly **5–10% are local HTTP**
- Roughly **50–55% are remote HTTP**, and that share is growing every month

## What this means for IntentFrame's trust boundary

Both models are compatible with your architecture, but with different threat surfaces. Your Executor needs to handle them explicitly.

**For local stdio / local HTTP servers (running on user's machine):**

- Executor spawns or connects to the server process locally.
- Credentials live on the user's machine (env vars, keychain, config files held by the server).
- **No third-party data exposure beyond whatever the MCP server itself calls.** A local Gmail MCP server still talks to Gmail's API — but the *content* of the request only leaves the user's machine when it has to (to reach Gmail). It doesn't pass through any other vendor's infrastructure.
- Risk surface: a malicious or buggy MCP server installed on the user's machine could have whatever capabilities its subprocess has. **The Executor must sandbox each MCP server subprocess** with the minimum privileges it needs (Seatbelt profile per server, no extra FS or network reach beyond declared capabilities).

**For remote HTTP servers (vendor-hosted):**

- Executor holds an OAuth token, makes authenticated HTTPS calls to the vendor.
- **The request's payload — including the data fields of the user's intent — flows to the vendor's server.** If the user is sending an email through a hosted Gmail MCP, the email contents traverse the vendor's MCP infrastructure, not just Google's.
- Vendor sees: the OAuth scope, the tool call, the arguments, the response.
- Risk surface: vendor breach exposes OAuth tokens or in-flight data. You're adding a transitive vendor trust dependency on top of the underlying service trust dependency (which existed anyway).

## Implications for the indie operator's privacy posture

This is important and you should think about it explicitly, because your customer cares.

**Local stdio servers:**
- Strongly aligned with the "your data stays on your Mac" story.
- If the user already trusts Gmail with their email, they're not adding any new trust party by using a local Gmail MCP server.
- This is the privacy-maximal default.

**Remote MCP servers:**
- The user is now trusting *two* parties: the underlying service (Gmail, Stripe, GitHub) and the MCP host.
- If the MCP host is the same company as the service (Stripe hosts Stripe's MCP, GitHub hosts GitHub's MCP), the trust delta is approximately zero.
- If the MCP host is a third party reselling access (some community-hosted gateways), trust delta is non-zero and should be disclosed.

For your indie-operator wedge, the cleanest privacy story is:
- **Default to local stdio when both are available.**
- **Permit remote only when hosted by the same vendor whose service is being accessed** (i.e., Stripe-hosted MCP for Stripe is fine; some-startup-hosted-MCP-for-Stripe is not).
- **Allow other hosted MCP only with explicit user consent** and a clear "your data will flow through X" warning.

## What the Executor needs to support

For the Executor to be honest about all three modes:

1. **Transport abstraction** — it should be able to speak stdio, local HTTP/SSE, and remote HTTPS/SSE behind one interface.
2. **Per-server sandbox profile** — for local subprocesses, apply a Seatbelt profile that grants only the capabilities the server declares it needs. A "PDF reader MCP" should have no network reach. A "Fetch" server has narrow network reach.
3. **Per-server credential vault** — OAuth tokens and API keys for each server live in IntentFrame's vault, scoped to the server. The agent process and other servers don't see them.
4. **Per-server "data exposure" classification** in policy — the Executor should know whether a given intent, when routed to a given server, will cause user data to leave the device. That classification should be a visible field at policy-decision time. "This action will send `data.body` to remote MCP server `gmail.com`" is information the policy and the user deserve.
5. **Audit chain records the transport** — every record should note whether the action ran via local subprocess, local HTTP, or remote vendor, with the vendor identity if remote. This is essential for the "what did my agents do today" story.

## The short answer

- The official reference servers and most filesystem/dev/system tools: **local stdio on the user's Mac.**
- The popular SaaS integrations (Stripe, GitHub, Notion, Linear, Slack, etc.): **increasingly remote, hosted by the vendor.**
- Your Executor should support both, treat them as different from a privacy-disclosure perspective, sandbox local ones, scope-limit remote credentials, and surface the difference in audit and policy.

For the indie operator: the practical experience is that they install IntentFrame, click "Connect Gmail" and OAuth flows through to the vendor's hosted MCP; click "Connect filesystem" and a local subprocess gets spawned with a sandbox profile. Both work. Both gate through your policy boundary. Neither exposes credentials to the agent process. The privacy posture differs and your UI should make that clear.