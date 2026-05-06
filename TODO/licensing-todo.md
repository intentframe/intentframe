# Mixed licensing — action checklist

> **Status: DEFERRED.** Repo is currently single-license AGPL-3.0-only, which is a coherent,
> defensible state. Revisit before any of: SDK published to PyPI/npm, design-partner integration,
> public launch, or external agent developers building on IntentFrame. Until then, do **not** add
> Apache-2.0 headers or `intentframe_actor/LICENSE` — a half-done split is worse than no split.

This document tracks the **in-repo mixed-license** plan: **Apache-2.0** for the public Actor SDK surface, **AGPL-3.0** for runtime / Guardian / Analysis Engine and the rest of the monorepo root.

**Strategy:** implement **directory-level licenses + SPDX headers** now (quick path). Before going public (or heavy investor/design-partner exposure), plan a **`packages/`** layout with explicit publish boundaries.

---

## Principles

1. **Root `LICENSE`** = AGPL-3.0 for everything not covered by a subdirectory `LICENSE`.
2. **`actor-sdk/`** (or the actual SDK directory name in this repo) gets its own **`LICENSE`** = Apache-2.0 full text.
3. **SPDX** on every source file so scanners and legal review stay unambiguous.
4. **No AGPL code imported into the Apache region.** The SDK may use stdlib, permissive third-party deps, and code under an explicit Apache-2.0 subtree only. Shared types/helpers used by both sides must live under Apache-2.0 or be reached only across the IPC/runtime boundary—not as Python/TS imports from AGPL trees.
5. **Protocol artifacts** (`.proto`, OpenAPI, JSON Schema, etc.) should live in a **dedicated Apache-2.0** tree (e.g. `protocol/`) so third-party clients in any language can implement against them without AGPL encumbrance.

---

## Phase 1 — do now (Option 1)

- [ ] Add **`actor-sdk/LICENSE`** with the full **Apache-2.0** license text (adjust path if the SDK folder name differs).
- [ ] **Audit** all imports and build inputs for the SDK; fix any dependency on AGPL-only modules (extract, duplicate minimally, or move shared bits under Apache-2.0).
- [ ] Add **SPDX file headers**:
  - SDK / Apache region: `# SPDX-License-Identifier: Apache-2.0` (and equivalent for other languages).
  - AGPL region: `# SPDX-License-Identifier: AGPL-3.0-only`.
  - Use a single copyright line consistent with the project (e.g. `Copyright 2026 IntentFrame`).
- [ ] Add root **`NOTICE`** describing: root AGPL; SDK (and later protocol) Apache-2.0; that per-file SPDX is authoritative.
- [ ] Update root **`README.md`** with a **Licensing** section that points to `LICENSE`, `NOTICE`, and `actor-sdk/LICENSE`.
- [ ] If the SDK is published (**PyPI**, **npm**, etc.), set package **metadata license** to **Apache-2.0**, and ensure the published artifact contains **only** the SDK (not AGPL sources).

### Optional tooling (later)

- **reuse** (FSFE) — SPDX validation, NOTICE generation.
- **Pre-commit** — require SPDX on new files in touched paths.
- **pip-licenses** / **license-checker** — ensure SDK deps stay permissive.

---

## Phase 2 — before public launch (Option 3)

- [ ] Restructure toward **`packages/`** (or equivalent) with clear boundaries: e.g. `actor-sdk-python`, `actor-sdk-typescript`, `runtime`, `guardian`, `analysis-engine`, **`protocol`** (Apache-2.0).
- [ ] **`protocol/`** (or `packages/protocol`) with its own **`LICENSE`** (Apache-2.0) and SPDX on schema/proto/OpenAPI files.
- [ ] Confirm **CI/publish** only ships Apache-2.0 artifacts for SDK and protocol packages.
- [ ] **Website** (`intentframe.com` or equivalent): short, accurate **licensing** copy aligned with the repo.
- [ ] Tighten **`CLA.md` clause 4** to explicitly mention possible permissive sub-licenses (Apache-2.0 SDK), so contributor expectations match the broad grant already in clause 2.

---

## Ongoing

- [ ] New files in each region get the correct **SPDX** header from day one.
- [ ] **Never** add imports from AGPL areas into Apache-licensed packages.
- [ ] New SDK languages: add **`packages/actor-sdk-<lang>/`** (or consistent naming) under **Apache-2.0**.

---

## Reference layout (target mental model)

```text
intentframe/
├── LICENSE                 # AGPL-3.0 (default for repo)
├── NOTICE                  # Explains mixed licensing
├── README.md               # Licensing section
├── actor-sdk/              # or packages/actor-sdk-* after restructure
│   ├── LICENSE             # Apache-2.0
│   └── ...
├── protocol/               # Apache-2.0 (schemas, .proto, OpenAPI)
│   ├── LICENSE
│   └── ...
└── ...                     # runtime, guardian, analysis-engine → AGPL via root
```

---

## Caveats

- GitHub’s repo **license badge** reflects the **root** `LICENSE` (often AGPL here); the **NOTICE** and **per-directory LICENSE** files clarify the SDK.
- Some scanners only read the root file; **SPDX per file** reduces false positives for the SDK.

When this checklist is complete for Phase 1, you can archive or trim this doc and rely on `NOTICE` + README as the user-facing source of truth.
