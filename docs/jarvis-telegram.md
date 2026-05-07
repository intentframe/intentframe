# Jarvis Telegram Bridge

> Message your Mac from your phone. Every action still goes through IntentFrame's pipeline before touching anything — regardless of where the request originated.

The Telegram bridge is a small process that lets you talk to [Jarvis](jarvis.md) from a Telegram chat. You type on your phone; the message reaches Jarvis on your Mac; Jarvis reasons, proposes actions through IntentFrame, and the response comes back. Heartbeat alerts surface as `[Alert]`-prefixed messages.

It is structurally a *pure client* of the Jarvis HTTP server — Telegram as the transport, with no policy authority of its own. In the supported product flow, the bridge is **a service managed by the IntentFrame gateway**, not a process the user starts directly. You configure the bot token and your allowed Telegram user ID through the gateway CLI, and the gateway brings the bridge up alongside Jarvis.

For setup, see "How you actually run it" below. For implementation details (lifecycle, error semantics, internal architecture), see [`../jarvis_telegram/README.md`](../jarvis_telegram/README.md) and [`../jarvis_telegram/ARCHITECTURE.md`](../jarvis_telegram/ARCHITECTURE.md).

---

## Why this exists in the repo

The bridge proves a property the rest of the README cannot prove on its own: **the IntentFrame boundary is independent of where the request originated.**

A local terminal client and a remote phone client are *the same thing* from IntentFrame's perspective. Both submit intents through the Actor SDK. Both go through the same Analysis Engine, the same Guardian, the same deterministic gates, the same executor. There is no "remote-input mode" that loosens the rules.

If the boundary holds for a `RUN_COMMAND` typed in your terminal, it holds for the same `RUN_COMMAND` typed into Telegram from a different country. That equivalence is the architectural claim the bridge cashes out.

It is also the *"skin in the game"* artifact that's missing from the main IntentFrame story: the maintainer messages their own Mac from their own phone, every day, through this exact path.

---

## What it actually does

```
┌─────────────────────────────────────────────────────────────────┐
│  YOUR MAC                                                       │
│                                                                 │
│   gateway (intentframe-gateway-cli)                             │
│   manages: vault, supervisor, jarvis, edi, telegram, …          │
│                                                                 │
│  ┌─────────────────────┐     UDS      ┌──────────────────────┐  │
│  │  jarvis-telegram    │─────────────▶│  jarvis-server       │  │
│  │  (managed service)  │  POST /chat  │  (managed service)   │  │
│  │                     │◀─────────────│                      │  │
│  │  Long-poll loop     │              │  GatedJarvis         │  │
│  │  Event listener     │  WS /events  │  JarvisAgent         │  │
│  └────────┬────────────┘              └──────────────────────┘  │
│           │ HTTPS                                               │
└───────────┼─────────────────────────────────────────────────────┘
            │
            ▼
   Telegram Bot API (cloud)
            │
            ▼
   Telegram app (your phone)
```

The bridge:

1. **Long-polls Telegram** for new messages addressed to the bot. No webhooks, no public URL, no inbound ports. The connection is outbound-only HTTPS.
2. **Authorises by user ID.** Only the configured Telegram user ID — passed in via `JARVIS_TELEGRAM_ALLOWED_USER_ID`, which the gateway injects from `~/.intentframe/gateway.yaml` — is allowed. Every other user is silently ignored and logged.
3. **Forwards messages to Jarvis** via `POST /chat` over a Unix domain socket — the same socket the gateway-managed Jarvis service listens on.
4. **Edits a "Thinking…" placeholder** with Jarvis's response. Long responses are chunked at Telegram's 4,096-character limit; continuation chunks are prefixed `(continued…)`. Responses over the bridge's max-response cap (16K default) are truncated.
5. **Forwards heartbeat alerts** as `[Alert]`-prefixed messages by subscribing to the server's `/events` WebSocket.

That's the whole bridge. ~500 lines of Python. The deliberate smallness is the point — the bridge has no policy authority, no credential access, no agent state. Everything that matters happens on the other side of the UDS.

---

## How you actually run it

The Telegram bridge is brought up automatically by the gateway when two credentials are present at startup: the bot token and the allowed Telegram user ID. The supported flow runs entirely through the gateway CLI:

```bash
uv run intentframe-gateway-cli
```

Inside the REPL:

```text
vault set telegram bot_token              # paste the token from @BotFather
env set telegram.allowed_user_id 12345678 # your numeric Telegram user ID (from @userinfobot)
```

The gateway picks both up on next start and launches the bridge as a managed service. From that point on, messaging the bot in Telegram goes:

```
Telegram app → Telegram cloud → bridge (managed service)
             → POST /chat (UDS) → Jarvis (managed service)
             → IntentFrame pipeline → executor → real world
```

You can manage the bridge through the gateway like any other service:

| REPL command | What it does |
|---|---|
| `start telegram` | Start the bridge (if it's not already running) |
| `stop telegram` | Stop the bridge |
| `restart telegram` | Restart the bridge |
| `status` | Show service health, including telegram |
| `logs telegram [lines]` | Tail the bridge log |

If you're working on the bridge itself, you can also run `jarvis-telegram` standalone against an already-running gateway-managed Jarvis server. That's a development entry point — not the user-facing path. The full standalone story is in [`../jarvis_telegram/README.md`](../jarvis_telegram/README.md).

---

## Where the trust boundaries are

This is the property to verify when evaluating the bridge.

| Boundary | What is trusted | What is *not* trusted |
|---|---|---|
| **Telegram cloud → bridge** | The bot token (issued by BotFather) is the only credential touching the network. The bridge filters by `allowed_user_id`. | Telegram itself is not a security layer — assume the cloud sees every message and every reply. Don't put secrets in chat. |
| **Bridge → Jarvis server** | Local UDS only. The bridge calls `POST /chat` and subscribes to `/events`. | The bridge has no policy authority, no credential access, no ability to bypass the gate. |
| **Jarvis server → IntentFrame** | Same as any other Jarvis client. Every intent goes through the pipeline. | The origin of the request (terminal, CLI, Telegram, future client) is not part of the trust evaluation. |
| **IntentFrame → real world** | The executor, kernel-enforced sandbox, audit chain. | Same boundary as for any other client. |

A compromised bot token gets an attacker the ability to *send messages to your Jarvis*, which has the same authority as you typing in your local terminal — bounded by your IntentFrame policy. It does not get them credentials, files outside policy, or any action the Guardian would block from the keyboard. The bridge does not widen the boundary; it just opens a new origin for requests that pass through it.

That property holds because the bridge has no special path. There is no "from-Telegram" exemption in the runtime. There never will be.

---

## What the bridge is *not*

- **Not multi-user.** Single user by design. `allowed_user_id` is exactly one ID; everything else is ignored.
- **Not multi-tenant.** No per-user sessions. The bridge consumes the same single Jarvis instance the local CLI does. The server's `GatedJarvis` enforces single-client-at-a-time, so if you're chatting in your terminal and also message from Telegram, the second one gets a "Jarvis is busy talking to {client}" reply.
- **Not authenticated beyond user-ID allowlist.** No two-factor, no per-message signing. The trust model is *"only my Telegram account, on my phone, can send messages to my bot."* If your Telegram account is compromised, an attacker can chat with your Jarvis as you. The IntentFrame boundary still applies, but they get keyboard-equivalent authority.
- **Not a secure channel for secrets.** Telegram's cloud sees every message. Don't paste API keys into the chat.
- **Not a production deployment story.** It is a personal-use bridge for a single-user assistant. A production multi-user equivalent would need per-user sessions, per-user policies, and a different gate model.

---

## What the bridge *is* evidence for

| Claim | Evidence |
|---|---|
| The IntentFrame boundary is origin-independent. | Every action submitted via the bridge goes through the same pipeline as any other Jarvis client. |
| The runtime can host a real client surface, not just a benchmark harness. | Telegram is a real consumer protocol with its own quirks (rate limits, message-edit semantics, chunk limits). The bridge handles them and the boundary holds underneath. |
| The HTTP server is a usable extension surface. | The bridge is not special-cased in the server; it is one of an open-ended set of clients the `/chat` and `/events` endpoints can serve. |

| Claim it is *not* evidence for | Why |
|---|---|
| Multi-user safety. | Single user only; the gate is mutual-exclusion, not isolation. |
| Network-attack resistance. | The bridge does not defend Telegram itself, only the IntentFrame boundary downstream of it. |
| Production hardening. | Personal-project alpha; correctly scoped, deliberately small. |

---

## Outbound traffic profile

When the bridge is running, two outbound flows exist that the rest of IntentFrame does not have:

| Direction | Endpoint | Frequency | Payload |
|---|---|---|---|
| Outbound HTTPS | `api.telegram.org` | Continuous (long polling, ~30s timeouts) + per-reply | Bot API requests, user messages, bot replies |
| Inbound (cloud-mediated) | None — Telegram delivers via the long-poll response, not an inbound connection | n/a | n/a |

There is no public URL, no listener on any port. The bridge initiates the connection, Telegram replies. From a network-policy perspective, the bridge is "an HTTPS client to `api.telegram.org`."

The full outbound traffic catalog for the platform is in [`privacy.md`](privacy.md).

---

## Quick answers

| Question | Answer |
|---|---|
| Does Telegram see what Jarvis does? | Telegram sees the chat — your messages and the text Jarvis replies with. It does not see tool calls, intents, or audit-trail details. |
| Can the bridge bypass IntentFrame policy? | No. The bridge has no policy authority. Every request goes through the same pipeline as a local CLI request. |
| What if my Telegram account is compromised? | An attacker can chat with your Jarvis as you. They get keyboard-equivalent authority — bounded by your IntentFrame policy, not unbounded. |
| Can I expose Jarvis to multiple people via Telegram? | Not safely — the bridge is single-user and Jarvis itself is single-tenant. A multi-user variant would need a different design. |
| Why no streaming? | The bridge uses `POST /chat` (final text only). Streaming + Telegram message-edit semantics is non-trivial; tool-call visibility is on the wishlist. |
| Why Markdown isn't formatted? | Telegram's `MarkdownV2` requires aggressive escaping that's still being worked through; replies are sent as plain text today. |
| How do I set it up? | Through the gateway CLI: `vault set telegram bot_token` + `env set telegram.allowed_user_id <ID>`. See [How you actually run it](#how-you-actually-run-it) above. |

---

## Related documents

- [`../intentframe_cli/README.md`](../intentframe_cli/README.md) — How to set credentials and manage the bridge through the gateway REPL
- [`../intentframe_gateway/README.md`](../intentframe_gateway/README.md) — How the gateway manages Telegram alongside Jarvis, vault, EDI, and the supervisor
- [`../jarvis_telegram/README.md`](../jarvis_telegram/README.md) — Implementation reference: standalone usage, env vars, message lifecycle, error semantics
- [`../jarvis_telegram/ARCHITECTURE.md`](../jarvis_telegram/ARCHITECTURE.md) — Engineer-facing diagram, module structure, lifecycle internals
- [jarvis.md](jarvis.md) — The agent the bridge talks to
- [`../jarvis_pa/jarvis/server/README.md`](../jarvis_pa/jarvis/server/README.md) — The HTTP API the bridge consumes
- [`../jarvis_pa/jarvis/gated_jarvis.md`](../jarvis_pa/jarvis/gated_jarvis.md) — The single-client concurrency gate the bridge interacts with
- [architecture.md](architecture.md) — How a Telegram-originated intent flows through IntentFrame
- [privacy.md](privacy.md) — Outbound traffic catalog (including Telegram Bot API)
