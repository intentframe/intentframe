## 1. How deterministically do we know Sent, Drafts, etc.?

**The short answer: it's a three-tier system, and tier 1 works for all major providers today.**

**Tier 1 — RFC 6154 special-use flags (deterministic)**
The server includes flags like `\Drafts`, `\Sent`, `\Trash` in its `LIST` response. This is unambiguous — the server is explicitly telling you "this folder is for drafts." Support:

| Provider | RFC 6154 support | Notes |
|---|---|---|
| **Gmail** | Yes, always on | All LIST responses include flags automatically |
| **Outlook/Office365** | Yes | Returns flags in LIST |
| **Dovecot** (most self-hosted) | Yes, configurable | Admin sets `special_use = \Drafts` per mailbox |
| **Fastmail** | Yes | Full RFC 6154 |
| **Yahoo** | Yes | Via their backend (Dovecot-based) |

The RFC says "MAY include" — but in practice, every major provider today does. It's been 15 years since the RFC was published and it's become a de facto requirement because Thunderbird, Apple Mail, and Outlook all depend on it.

**Tier 2 — INBOX (IMAP spec guarantee)**
`INBOX` is the *only* folder name guaranteed by the base IMAP spec (RFC 3501). It always exists and always means inbox. Everything else is provider-specific naming.

**Tier 3 — Name-based guessing (fragile, last resort)**
Guessing from names like "Sent", "Drafts", "Trash" is unreliable because:
- Names are **locale-dependent** — Gmail in Spanish: `[Gmail]/Enviados` (Sent), `[Gmail]/Borradores` (Drafts)
- Names are **provider-specific** — Gmail: `[Gmail]/Sent Mail`, Outlook: `Sent Items`, generic: `Sent`
- Self-hosted servers can name folders anything

**Our approach** (what we just refactored to): use flags from the server via `LIST`. The only hardcoded name is `INBOX`. If a server doesn't return a flag for a role, we return `None` and the caller can decide what to do (error, prompt user, etc.). No guessing.

---

## 2. Do providers expose categories like Gmail's Primary/Social/Promotions/Updates/Forums?

**No — not through standard IMAP.** These are proprietary classifications, not IMAP folders.

**Gmail:**
- Categories (Primary, Social, Promotions, Updates, Forums) are **not IMAP folders or labels**. They're an automatic ML-based classification layer that exists only in Gmail's UI.
- They are **not in the LIST response** and have no RFC 6154 flags.
- **Workaround via `X-GM-RAW`**: Gmail's proprietary IMAP search extension lets you query by category:
  ```
  UID SEARCH X-GM-RAW "category:promotions"
  UID SEARCH X-GM-RAW "category:social"
  UID SEARCH X-GM-RAW "category:primary"
  ```
  This returns UIDs of messages in that category — but it's Gmail-only and search-based, not folder-based.
- The **Gmail REST API** exposes them as system labels (`CATEGORY_SOCIAL`, `CATEGORY_PROMOTIONS`, etc.) — more reliable but requires OAuth + API access, not IMAP.

**Outlook:**
- "Focused Inbox" (important vs. other) is **not accessible via IMAP at all**. It's a client-side / Exchange-only feature.
- Outlook's "Categories" (color tags) are also **Exchange-only** — IMAP accounts in Outlook cannot use categories.

**Other providers:**
- No standard IMAP mechanism for email categorization/triage exists. It's all proprietary.

**Bottom line:** If you want Gmail categories, you'd need either:
1. Gmail's `X-GM-RAW` IMAP extension (Gmail-only, search-based)
2. Gmail REST API (proper support but different protocol entirely)

For a provider-agnostic IMAP service like ours, categories aren't available through the standard protocol. We could add Gmail-specific category support as an optional feature using `X-GM-RAW`, but it wouldn't work for Outlook or other providers.

---