# Jarvis Write-File Policy And Per-Agent Python Env

> Tighten `WRITE_FILE` around actual execution risk, not just file mutation in general, and move Jarvis toward an explicit per-agent Python environment instead of ambient system or executor Python.

---

## Goal

Keep Jarvis broadly useful without giving it unnecessary power to create new execution surfaces.

The main idea is:

- do **not** over-restrict ordinary file writing,
- do **not** treat every non-Python file as equally dangerous,
- do treat executable, auto-loaded, persistence-bearing, or runtime-shaping files as higher risk,
- use `command_shield.inspect_code(...)` as a deterministic payload-inspection helper,
- and eventually give each agent a dedicated Python environment inside the sandbox.

---

## The Tension

Jarvis is practically a shell + Python agent today.

That means there is a mismatch if we let it freely:

- write arbitrary executable code in runtimes it cannot safely reason about,
- create startup or persistence files,
- change build/deploy/workflow behavior,
- or install dependencies into ambient Python state.

But the opposite extreme is also wrong:

- blocking every non-Python write would prevent many legitimate tasks,
- many safe writes are docs, JSON, YAML, TOML, config, notes, or passive data,
- and some non-Python files are operationally harmless while some Python files are not.

So the policy should be based on **execution risk + destination sensitivity + payload inspection**, not extension alone.

---

## Core Decision

Do **not** make the default rule:

> "Jarvis may only write Python files."

Instead, make the default rule:

> "Jarvis may write ordinary passive files freely, but executable or auto-loaded writes require stronger checks."

This keeps capabilities broad where they are low-risk and narrow where they materially increase control over the system.

---

## Where `command_shield.inspect_code(...)` Fits

`inspect_code(...)` is a good fit for `WRITE_FILE` payload triage when we already have content in memory.

It can help answer:

- does this payload look like code,
- what language does it appear to be,
- does it look binary,
- what deterministic findings exist if it is Python or shell,
- what structured signals should downstream policy or AI consume.

It should **not** be the final authority for "safe to write".

It is a fact producer, not policy.

For `WRITE_FILE`, it should feed a later decision layer that also considers:

- target path sensitivity,
- overwrite vs create,
- whether the file is executable or auto-loaded,
- whether the current action/task justifies creating this kind of file,
- and whether the language/runtime is one Jarvis is expected to operate in.

---

## Proposed Write-File Policy Shape

### 1. Passive files: generally allow

These should usually remain low-friction:

- `*.md`
- `*.txt`
- `*.json`
- `*.yaml`, `*.yml`
- `*.toml`
- `*.csv`
- ordinary app/local config files that are not auto-executed

These may still need path-based checks, but they should not automatically be treated as high-risk just because they are writes.

### 2. Python and shell: allow, but inspect

Jarvis should usually be allowed to write:

- `*.py`
- `*.sh`
- shell snippets in known-safe project/workspace paths

But the payload should be inspected and the result should surface to policy and Guardian:

- language
- binary/unknown detection
- code findings
- signals

### 3. Other executable or runtime-shaping files: review by default

These should normally require stronger review, not silent allow:

- `*.js`, `*.mjs`, `*.cjs`, `*.ts`
- `*.rb`, `*.pl`
- launchd plists
- CI/workflow files
- Dockerfiles / Compose files
- Makefiles
- editor automation / hooks
- shell startup files

The reason is not that these languages are bad. The reason is that these files can create new execution surfaces that Jarvis is not primarily scoped to manage today.

### 4. Sensitive destinations: block or escalate regardless of extension

Certain paths should be high-risk even when the file is plain text:

- `~/.ssh/*`
- `.env` and credential stores
- `~/.gitconfig`, git hooks
- `.github/workflows/*`
- `~/Library/LaunchAgents/*`
- `/Library/LaunchDaemons/*`
- shell startup files like `.zshrc`, `.bashrc`
- runtime or product internals such as `~/.intentframe/*`

This is path risk, not just content risk.

---

## Recommended Decision Matrix

For `WRITE_FILE(target_path, content)`:

1. classify the target path:
   - passive path
   - executable/runtime path
   - sensitive/persistence path
2. inspect the payload:
   - text vs binary-like
   - language inferred from path / shebang / content
   - deterministic findings if language is in scope
3. combine both:
   - passive path + passive content -> allow
   - ordinary code path + Python/shell payload -> inspect + allow/review
   - unsupported executable language -> review
   - persistence/sensitive path -> block or require explicit higher-trust route

The key is:

- path alone is insufficient,
- extension alone is insufficient,
- code findings alone are insufficient,
- but together they form a useful risk model.

---

## Suggested `inspect_code(...)` Interpretation For Writes

`CodeReport` can drive policy roughly like this:

- `language == "binary"` -> not a normal text/code write; treat as higher risk or reject from normal write path
- `language == "unknown"` -> ambiguous; review instead of assuming safe
- `signals` includes `CODE_TOO_LARGE` -> reduced confidence; review
- `signals` includes `resolved:unsupported-language` -> inspection depth limited; review if executable path
- `code_intel.findings` non-empty -> surface to Guardian / policy / audit

This is especially useful for:

- generated Python scripts,
- generated shell scripts,
- notebook cell export,
- small helper tools created during a task,
- policy decisions like "writing Python into `scripts/` is acceptable, but writing shell init into home dotfiles is not."

---

## Why Not Extension-Only Blocking

An extension-only rule would create bad incentives and blind spots:

- safe YAML/TOML/JSON writes would be treated too harshly,
- risky plain-text files like `.bashrc` or `.env` might slip through if they are not on a denylist,
- Python files could still be dangerous while non-Python files could be benign,
- future agent capabilities would be artificially constrained by today's runtime assumptions.

We want to reduce **unsafe effects**, not just reduce the number of file types.

---

## Per-Agent Python Environment

Longer term, Jarvis should not rely on ambient system Python or the executor's own venv for task execution.

Instead, each agent (or task/session) should get a dedicated Python environment with:

- an explicit filesystem location,
- explicit sandbox write permission,
- explicit interpreter path,
- isolated package state,
- lifecycle control and cleanup.

### Why this is better

- no dependency pollution across agents,
- no accidental coupling to executor internals,
- safer package installation story,
- easier auditability,
- clearer policy boundaries for Python execution,
- easier future support for "this agent can use Python, but only inside its own env."

### Current state (implemented)

The executor now has a dedicated venv at `~/.intentframe-venvs/executor` (sibling of `~/.intentframe/`, not nested under it — the latter is in `NON_NEGOTIABLE_DENY_ACCESS` and would make `exec` of the venv's `python3` fail in the sandbox). Provisioned by `intentframe_setup.sh` via `uv venv --seed`. The path is configurable via `--executor-venv` (setup flag), `INTENTFRAME_EXECUTOR_VENV` (env var), or `sandbox.executor_venv_path` (runtime). The macOS sandbox engine explicitly exposes that venv to sandboxed `RUN_COMMAND` via env overrides:

- `PATH` is prepended with `<venv>/bin` on top of the system-derived `PATH` from `/etc/paths`.
- `VIRTUAL_ENV` is set to the venv path.
- `PYTHONNOUSERSITE=1` is set to block `pip install --user` escapes.
- `PYTHONHOME` is never set (venvs break if it is).

This means in the normal case `python`, `python3`, `pip`, and `uv pip install` all resolve to the executor venv. `<repo>/.venv` (the gateway's venv) and `~/Library/Python/...` (user site) are structurally protected from pollution. The config knobs are `sandbox.executor_venv_path` (absolute path, `None` = auto-resolve) and `sandbox.executor_venv_required` (default `True` → fail-closed at startup if the venv is missing).

Path resolution is identity-aware: it uses `SUDO_USER` if present, else the current uid's HOME, so the design works whether the executor runs as a regular user or as root. Bare root with no `SUDO_USER` fails loud rather than silently picking `/var/root/`.

The planner also cross-checks the resolved venv path against `NON_NEGOTIABLE_DENY_ACCESS` at startup: a venv path nested under any deny-access subpath is rejected (returns `None`), which triggers fail-closed when `executor_venv_required=True`. This catches the "default path inside the deny perimeter" footgun deterministically at startup rather than at first `RUN_COMMAND`. `intentframe_setup.sh` mirrors the same guardrail.

Uninstall is handled by `intentframe_uninstall.sh` — it removes `~/.intentframe-venvs/` and `~/.intentframe/` (interactive confirm unless `--yes`), and optionally the signing cert (`--remove-cert`) and keychain vault entries (`--remove-keychain-vault`). TCC grants remain a manual cleanup step (macOS doesn't expose a programmatic API).

### Unchanged constraints

- `command_shield/env.py` whitelist still drops `VIRTUAL_ENV` and friends from the parent env. The venv exposure is an **explicit override** added by the sandbox engine, not inheritance from whatever was activated in the parent shell.
- `_system_path()` still replaces `PATH` with `/etc/paths`-derived values. The venv prepend sits **on top** of that, so regular binaries (`git`, `rg`, `grep`, etc.) still resolve normally.
- Absolute-interpreter bypasses (`/usr/bin/python3 foo.py`) are not blocked by this design — they're a `command_shield.inspect_code(...)` concern, handled by a separate layer.

### Per-agent: next

Now that the plumbing is "plan carries an absolute venv path, engine adds env overrides", per-agent venvs are a substitution, not new plumbing:

- agent session lifecycle manager creates `~/.intentframe-venvs/agent-<id>`,
- planner pulls venv path from agent context instead of `SandboxConfig.executor_venv_path`,
- add an explicit `install_package` tool separate from `RUN_COMMAND`.

---

## Phase 7a — Revised Scope

**Status (shipped, narrowed):** the floor-parity track landed in full.  The
AE / DG tracks shipped in a deliberately narrower shape than the original
5-point plan — the security-sensitive rewrites below happened mid-flight
and are the final stance.

- **Floor parity for `WRITE_FILE` / `DELETE_FILE`** via `resource_registry/floor.py` (`DENY_WRITE_PREFIXES`, identity-aware `~` expansion, canonical `realpath` check) enforced by `LocalVirtualFileSystem.write_file` and the new `LocalVirtualFileSystem.delete_file`.  `DELETE_FILE` in the files adapter now delegates to the VFS instead of calling `unlink` directly, so both ops share the floor.  Covered by `tests/test_vfs_floor.py` including a subset-symmetry test against `NON_NEGOTIABLE_DENY_WRITE`.

- **`FileIntel` as AI context, not as a routing input.**  `FileIntel` is a real core type in `intentframe_core/types.py`, computed once in `intentframe_server/pipeline.py` by `_build_file_intel` on every `WRITE_FILE` with a string payload.  It is forwarded to `AIAnalysisEngine.analyze` (where it renders the `WRITE_FILE — PAYLOAD SIGNALS` block inside the AE trusted context) and to `AIGuardian.validate` (where it is passed to deterministic checkers only — not to the Guardian LLM prompt, by design: Guardian reads the `AnalysisReport`, not raw deterministic intel).  `DefaultPromptStrategy` also accepts `file_intel` on its Protocol but **does not consult it for prompt-id selection** — see next bullet.

- **`DeterministicGuardian` — sensitive-path BLOCK, no content-based ALLOW.**  DG makes exactly one deterministic decision about `WRITE_FILE`: it **BLOCKs** when the virtual destination matches `is_sensitive_write_path` (shell startup files, credential stores, `sudoers`, persistence plists, Python runtime hooks — the virtual-path peer of `DENY_WRITE_PREFIXES`).  Every other `WRITE_FILE` falls through `UNDECIDED` to AE + AIGuardian.  `matched_gate="write_file_sensitive_path"`.  Tests in `tests/test_deterministic_guardian.py::TestWriteFileSensitivePathBlock`.

  The earlier plan of a passive-write `ALLOW` fast-path (keyed on extension + text payload + FileIntel "non-code" signal) **was reverted before shipping**.  Rationale: agent-provided extensions and `command_shield`'s payload classification are heuristics, not trustworthy evidence under an adversarial agent.  Any `ALLOW` fast-path built on them widens the attack surface for false-negative classification bugs.  Mutating writes that are not on the sensitive-path deny list always pay the LLM round-trip; the only deterministic shortcuts DG offers for mutating actions are hard BLOCKs.

- **`critical_write_file` AE lane, flat routing.**  `intentframe_components/prompt/library/analysis.py` defines a `critical_write_file` prompt id with its own full-body fork (`_CRITICAL_WRITE_FILE`), and `DefaultPromptStrategy.select_ae_prompt_id` routes every `WRITE_FILE` onto it unconditionally.  Tests in `tests/test_prompt_strategy.py::TestWriteFileAERouting` and `tests/test_prompt_library.py::TestAECriticalWriteFileBody`.

  The original plan of splitting `critical_write_file_code` (positively-classified code payload) vs `critical_write_file` (opaque / destination-sensitive) was **deferred, not rejected**.  When authored, `critical_write_file_code` will be a full-body fork of `_CRITICAL_WRITE_FILE` — not an additive overlay.  The future split is kept alive as `@pytest.mark.xfail(strict=False, ...)` tests in `test_prompt_strategy.py`.

- **Heuristics package scope reduced.**  `intentframe_components/heuristics/file_payload.py` now exports only `SENSITIVE_WRITE_PATH_FRAGMENTS` + `is_sensitive_write_path` (consumed by DG alone).  The earlier `is_code_file_payload` / `is_critical_file_payload` / `CODE_LANGUAGES` / `PASSIVE_WRITE_EXTENSIONS` predicates were removed — no caller consumed them after DG stopped short-circuiting on payload shape and the strategy stopped routing on payload shape.

- **Retraction.**  The stale "Phase 7a shipped" claim in `TODO/root-demo-policy-driven-sandbox.md` has been rewritten to match this narrower shape.

**Net effect on the LLM surface:** `WRITE_FILE` AE prompts now use the `critical_write_file` full-body fork (`_CRITICAL_WRITE_FILE`) plus the `WRITE_FILE — PAYLOAD SIGNALS` trusted-context block.  Guardian prompts are unchanged.  Routing is flat for WRITE_FILE; payload-aware sub-lanes (`critical_write_file_code`) exist only as xfailed placeholder tests in `test_prompt_strategy.py`.

---

The original 7a sketch (`FileIntel` plumbing + tri-class destination classifier + DG branch + critical WRITE_FILE AE lane) over-reaches. It duplicates policy vocabulary the system already has, and it fights the core design stance: **path policy is the semantic authorization; the sandbox is the floor; nothing in between**.

### What we actually discovered

`RUN_COMMAND` is fully covered by the macOS Seatbelt profile (`executor/sandbox/planner.py`, `executor/sandbox/platforms/macos.py`). The profile honors `NON_NEGOTIABLE_DENY_WRITE` (`executor/sandbox/templates.py:76-84`) so a shell command that tries to write `~/Library/LaunchAgents/com.evil.plist` is denied at the kernel regardless of policy.

`WRITE_FILE` does **not** go through that profile. It lands in `executor/platforms/macos/virtual_filesystem.py:160-176`, which does a plain `real_path.write_text(content)` after a mount-writability check. The non-negotiable deny list is never consulted. The policy-level `FileConstraints` is a pure `fnmatch` allow-list with no deny vocabulary (`policy_registry/constraints/file.py:8-19`, `intentframe_components/guardian/checkers/file.py:39-48`).

Net effect: `WRITE_FILE` to a launchd plist, a shell rc file, `~/.ssh/authorized_keys`, `/etc/sudoers.d/*`, `.github/workflows/*`, etc. is only prevented by whatever the user's `allowed_paths` happens to exclude. A broad allow like `allowed_paths: ["~/*"]` or the root-demo `allowed_paths: ["/*"]` allows all of them.

The equivalent `RUN_COMMAND` would be denied by the sandbox floor. This is the actual gap Phase 7a should close.

### The revised stance

- The `allowed_paths` policy is the semantic authorization — if the user granted `~`, Jarvis can do passive work under `~`.
- A non-negotiable floor exists for things that change the execution surface of the machine, regardless of policy breadth. Today that floor is RUN_COMMAND-only; it needs to be symmetric.
- Payload inspection / AE escalation is optional defense-in-depth on top of that floor, not the primary gate.

### Required — sandbox-floor parity for WRITE_FILE

Apply the same non-negotiable deny list to the file-tool path that the shell sandbox already enforces.

Concrete changes:

1. Promote `NON_NEGOTIABLE_DENY_WRITE` (or a parallel list with the same semantics) to a shared module the VFS can import without pulling in the sandbox engine — `executor/sandbox/templates.py` already works as the home since `executor/sandbox/planner.py` is the only consumer today.
2. Extend the list to cover the persistence/auto-load/secret-bearing categories the root-demo hardening already names (`TODO/root-demo-policy-driven-sandbox.md:262`): shell rc files (`.zshrc`, `.bashrc`, `.zprofile`, `.bash_profile`, `.zshenv`, `.profile`), `~/.ssh`, `~/.gnupg`, `~/.gitconfig`, git hooks (`.git/hooks/*`), `.github/workflows`, `/etc` sensitive files (`sudoers`, `sudoers.d`, `sshd_config`, `pam.d`), kext paths, `~/Library/Keychains`, `~/Library/Messages`, `~/Library/Mail`.
3. Teach `LocalVirtualFileSystem.write_file` / `delete_file` / (future) `APPEND_ROW` to resolve the virtual path, canonicalize, and reject any target that is under a deny-list prefix — raising `VirtualFileSystemError` with a `matched_gate`-style reason string. Same fail-closed posture as the sandbox.
4. Mirror the identity-aware `~` expansion from `executor/sandbox/venv.py` so the floor list resolves against the right home under both normal-user and `sudo root` executor processes (the same footgun `SandboxConfig.working_directory` has today).
5. Add tests in `tests/test_sandbox.py` (or a new `tests/test_vfs_floor.py`) that attempt WRITE_FILE + DELETE_FILE against every deny-list entry and assert they fail — plus symmetry tests proving the shell sandbox and the VFS reject the same set.
6. Retract the `Phase 7a shipped` line in `TODO/root-demo-policy-driven-sandbox.md:261` and replace it with what actually shipped once (1)–(5) land.

After this, `allowed_paths: ["/*"]` + unrestricted sandbox becomes a coherently-opted-into configuration: the user granted broad filesystem access, and the only things still non-negotiable are the platform-level footguns that would self-disable the machine or create new execution surfaces.

### Optional — "Escalate AE only" defense-in-depth

> **Status:** partially landed, deferred for content split.  The `critical_write_file` full-body fork and the `file_intel` → AE trusted-context plumbing are in; the payload-aware sub-lane (`critical_write_file_code`) is deferred.  See the "Phase 7a — Revised Scope" block above.  The text below is kept as the design reference for the eventual two-lane split.

Once the floor is symmetric, the remaining risk is prompt-injection-driven writes that land in the allowed zone but create execution surfaces the user didn't consciously authorize (e.g. a PDF convinces Jarvis to drop `~/.config/zsh/helper.zsh` into an auto-load directory that isn't on the floor list, or writes a passive-looking `.py` into a `sys.path`-adjacent location).

This can be handled entirely on the AE side, as **detection and elevated reasoning**, without adding a policy gate:

- Add a single new AE prompt id — `critical_write_file` — alongside the existing `critical_generic` / `critical_network_mutation` / `critical_network_probe` ids in `intentframe_components/prompt/library/analysis.py`. Body focuses on: "this write may create an execution surface or land at an auto-load-adjacent path; describe concretely what will execute, when, and under whose authority, and whether the stated intent matches the payload".
- In `DefaultPromptStrategy.select_ae_prompt_id` (`intentframe_components/prompt/strategy.py:159-182`), add a branch **before** `standard` that routes WRITE_FILE to `critical_write_file` when either:
  - the payload looks like code (a cheap `command_shield.inspect_code(...)` call on `intent.data["content"]` yields `language != "unknown"` and non-empty findings, or `language == "binary"`), **or**
  - the destination is auto-load-adjacent by path heuristic (ends in `.plist` and sits under any `LaunchAgents`/`LaunchDaemons`, lives under a Python `site-packages`/`.pth` path, lives under a shell auto-load dir like `.zshrc.d`, `.bashrc.d`, `.config/fish/conf.d`, sits under `.github/workflows`, etc.) but is **not** on the non-negotiable floor.
- No `WriteIntel` plumbing is required for the first cut. The strategy can call `inspect_code(...)` inline on the intent's content; it's synchronous and already bounded by `ShieldConfig.max_code_length`. If we later decide to share the payload findings with Guardian too, lift it into a bounded `FileIntel` on `intentframe_core/types.py` and populate it in `intentframe_server/pipeline.py` next to `CommandIntel`.
- WRITE_FILE stays out of `CRITICAL_ACTIONS` — the Guardian lane stays on `standard`. This keeps the AE escalation a pure "spend more LLM on this one request" move and avoids cascading prompt changes.
- The AE result is advisory: AE can flag `scope_mismatch=True`, raise `risk_factors`, or fill `hidden_behaviors` with findings. Guardian still decides. If we later want Guardian to see the same payload signal, add `critical_write_file` to the Guardian precedence table the same way.

This route is optional because a correctly-populated floor list already covers the named persistence / auto-load / secrets categories. AE escalation exists for the long tail — paths we didn't enumerate, payloads the user didn't anticipate, and injection-driven writes that stay inside `allowed_paths` but feel off.

### Optional — passive-file fast-path for WRITE_FILE

> **Status: deliberately NOT shipping.**  An earlier cut of Phase 7a prototyped exactly this branch (`matched_gate="write_file_passive"`, extension + text-payload + non-auto-load destination + clean `FileIntel`) and it was removed before release.  The core objection: every condition below is a heuristic over agent-controlled inputs (extension of the target path, language sniffed from the payload, code-intel findings on a string the agent chose).  An `ALLOW` fast-path built on those is fragile — one classifier gap lets a malicious payload through DG entirely.  DG's only deterministic shortcuts for mutating actions are now hard BLOCKs (`write_file_sensitive_path`).  The cost/latency argument is real, but it does not justify a content-based `ALLOW`.  Keeping the section for design history; do not re-ship without re-opening this tradeoff.

Mirror the existing `_PRE_AE_SAFE_READS` fast-path from `DeterministicGuardian` for writes whose extension and payload are demonstrably passive. This is a **cost/latency optimization**, not a safety lever — it does not relax any deny rule, it just avoids paying an LLM round-trip for writes we can prove are boring.

Today every WRITE_FILE that clears `FileChecker` falls through DG `UNDECIDED` → full AE + full AIGuardian. For Jarvis workloads the vast majority of writes are markdown notes, JSON/YAML config, TOML updates, CSV exports — one LLM round-trip each, ~2-4s of latency, and zero policy value.

Proposed DG ALLOW criteria — **every** condition must hold (fail-closed to UNDECIDED otherwise):

1. `permission.safe == True` (same precondition the passive-read fast-path already uses at `intentframe_components/guardian/deterministic.py:214`).
2. Destination **extension** is in a tight passive allow-set: `.md`, `.txt`, `.json`, `.yaml`, `.yml`, `.toml`, `.csv`, `.log`, `.ini`, `.env.example`, `.lock` (lockfile text, not secrets). Conservative by design — add more only with explicit review.
3. Destination is **not** on the non-negotiable floor list (belt-and-braces — the VFS will reject it too once floor parity ships, but DG checks earlier and cheaper).
4. Destination is **not** auto-load-adjacent by the same heuristic the AE escalation uses (`.github/workflows/**`, Python `site-packages`/`.pth`, `.zshrc.d`/`.bashrc.d`/`.config/fish/conf.d`, `.vscode/**`, `.cursor/rules/**`). Passive extension at a non-passive destination is still non-passive.
5. **Payload is text**, not code or binary:
   - no NUL byte in the first N bytes (cheap binary sniff)
   - no ELF/Mach-O/PE/Zip magic header
   - does not start with `#!` (shebang)
   - no HTML `<script>` tag (for `.html`, belt-and-braces against active content — or drop `.html` from the allow-set if that feels too subtle)
6. Payload length is under `ShieldConfig.max_code_length` (same cap the shield uses for inline `-c` payloads; prevents a giant paste being waved through without AE).
7. Policy constraint (`FileChecker` path match) already passed — this fast-path runs *after* the constraint check, not before.

All checks are pure, synchronous, string-level. No `inspect_code(...)` call — that's the AE escalation's job. The fast-path should be cheaper than the `_PRE_AE_SAFE_READS` branch already is.

New audit value: `matched_gate="passive_write"`. Mirrors `matched_gate="passive_read"` so audit dashboards get a symmetric vocabulary.

Implementation location: `intentframe_components/guardian/deterministic.py` — new branch in `_decide_inner` after the existing passive-read ALLOW (step 4 in the docstring) and before the RUN_COMMAND read-only ALLOW (step 5). The passive-read frozenset `_PRE_AE_SAFE_READS` stays as-is; add a parallel `_PASSIVE_WRITE_EXTENSIONS: frozenset[str]` and `_AUTO_LOAD_ADJACENT_PATTERNS: tuple[str, ...]` next to it.

Interaction with the other two optional tracks:

- **Fast-path vs floor**: floor always wins. If the destination is on the floor, VFS rejects at I/O time regardless of what DG said. The fast-path's rule (3) is a fast path for the common case, not a bypass.
- **Fast-path vs AE escalation**: mutually exclusive by construction. The auto-load-adjacent heuristic is the *exclusion* criterion for the fast-path (rule 4) and the *inclusion* criterion for AE escalation. If both matched somehow, DG should fail-closed to UNDECIDED so AE runs — never ALLOW when the escalation would have fired.
- **Fast-path vs `_PRE_AE_SAFE_READS`**: separate frozensets. `_PRE_AE_SAFE_READS` is keyed on *action*, this is keyed on action + *extension* + *payload shape*. Don't try to unify — reads and writes have different risk shapes.

Deferred aspects:

- We could eventually ALLOW Python/shell writes into pre-approved paths (e.g. a workspace `scripts/`) via a positive `inspect_code(...)` clean bill. Don't ship this in the first cut — it widens the fast-path to code writes, which is exactly the category AE escalation is supposed to *raise*, not *lower*.
- Conditional fast-path based on payload class (e.g. "passive extension with no findings and no suspicious signals"). Nice-to-have; not worth the complexity until we see it matter in traces.

Why this is worth doing:

- Cuts tail latency on the normal Jarvis flow (write note → next action) by an AE + Guardian round-trip.
- Trivial to review — DG gains ~40 lines of pure logic plus a test matrix. No new types, no pipeline plumbing, no new prompts.
- Symmetric with an existing, well-tested pattern (passive-read ALLOW). If reviewers understand one, they understand the other.
- Cheap to kill: delete the branch, WRITE_FILE goes back to the current `UNDECIDED → AE → Guardian` path. No compatibility debt.

### Order of work

Historical plan; current state is tracked in "Phase 7a — Revised Scope" above.

1. Sandbox-floor parity for WRITE_FILE + DELETE_FILE (`executor/platforms/macos/virtual_filesystem.py` + tests). ✅ shipped.
2. Expand the floor list to the root-demo hardening set; share it between sandbox templates and VFS. ✅ shipped (`resource_registry/floor.py`).
3. Retract / restate the `TODO/root-demo-policy-driven-sandbox.md:261` checklist entry. ✅ done.
4. ~~Passive-write fast-path in `DeterministicGuardian`~~ — **reverted** before shipping, see the "Optional — passive-file fast-path for WRITE_FILE" block for rationale.  Replaced with the hard-BLOCK `write_file_sensitive_path` gate.
5. `critical_write_file` AE lane + strategy branch — ✅ partially shipped (flat routing, empty overlay body).  The payload-aware sub-lane split (`critical_write_file_code`) is deferred until per-lane overlay bodies exist; tracked as xfailed tests in `tests/test_prompt_strategy.py`.
6. Structured `FileIntel` on the pipeline — ✅ shipped (computed once in `_build_file_intel`, forwarded to AE + Guardian deterministic checkers; Guardian LLM prompt intentionally does not see it).

---

## Future Shape

### Near-term

- ~~ship sandbox-floor parity for WRITE_FILE / DELETE_FILE~~ ✅ shipped.
- ~~share the deny list between `executor/sandbox/templates.py` and the VFS~~ ✅ shipped via `resource_registry/floor.py`.
- ~~passive-write fast-path in `DeterministicGuardian`~~ reverted by design — see "Optional — passive-file fast-path for WRITE_FILE".
- `critical_write_file` full-body fork (`_CRITICAL_WRITE_FILE`) is shipped.  Content covers destination-payload cross-check, payload-signals consumption, and consumer-awareness.
- fix `SandboxConfig.working_directory` to use the same identity-aware expansion as the executor venv (currently `os.path.expanduser` in `terminal.py` resolves against whatever HOME the executor process has — wrong under bare root).

### Mid-term

- split the WRITE_FILE AE lane into `critical_write_file_code` (positively-classified code payload) vs `critical_write_file` (opaque / destination-sensitive / non-code).  `critical_write_file_code` will be a full-body fork of `_CRITICAL_WRITE_FILE`.  Routing hooks exist as xfailed tests in `tests/test_prompt_strategy.py::TestWriteFileAERouting`; flipping them green requires the new prompt id in the library plus a `file_intel`-driven branch in `DefaultPromptStrategy.select_ae_prompt_id`.
- if a second consumer of `FileIntel` besides AE emerges (e.g. a future `FileChecker` that gates on payload size / language), feed the same intel into Guardian through the deterministic constraint-check path — the Guardian LLM prompt continues to read only the `AnalysisReport`, never raw deterministic intel, to preserve the "AE understands, Guardian decides" invariant.
- `command_shield.inspect_code(...)` should flag absolute-interpreter invocations (`/usr/bin/python3 …`) and absolute-shebang scripts as signals, since those bypass the executor-venv PATH steering.

### Longer-term

- provision a per-agent Python environment (plumbing already in place: swap the venv path on the plan)
- constrain Python package installs and execution to that environment
- add an explicit `install_package` tool so free-form `pip install` in `RUN_COMMAND` can be deprecated
- make "agent can write Python here and run it there" an explicit, inspectable policy decision

---

## Open Questions

1. Which paths belong on the shared non-negotiable deny list beyond the root-demo hardening set — specifically: do we add `~/.config/zsh/**`, `~/.config/fish/conf.d/**`, Python `site-packages`/`.pth` paths, editor auto-load dirs (`.vscode/tasks.json`, `.cursor/rules/**`)? Each added path narrows the "inside allow-list but still blocked" surface.
2. Should the floor list be a single flat tuple or a `{category: paths}` map so audit messages can say `matched_gate="floor:shell_rc"` instead of a generic `floor`? The sandbox side would need a matching update.
3. What should the `critical_write_file` overlay body actually say?  Today it's empty and the LLM sees the standard body; the whole value of the lane is latent until an overlay is authored.  The natural payload-aware split (`critical_write_file_code` vs `critical_write_file`) unlocks two distinct framings — "what will this code DO when run" vs "this is an opaque artefact at a destination we care about".
4. Does `is_sensitive_write_path` eventually subsume the VFS floor (one list, two enforcement points) or stay a virtual-path peer of the real-path floor (cheaper DG-side pre-check; VFS remains the source of truth)?  Today it is the latter.
5. What's the lifecycle of a per-agent env: per request, per chat, per workspace, or per long-lived agent identity?
6. Do we ever block writes outright based on `inspect_code` findings, or is the escalation always "elevate AE scrutiny" and let AE's scope/hidden-behavior reasoning drive BLOCK? Current stance is the latter — floor blocks, DG blocks sensitive paths, AE reasons, Guardian decides.

---

## Summary

The right policy is not:

> "Jarvis may only write Python files."

The right policy is:

> "Jarvis may write broadly, but writes that create execution surfaces or touch sensitive paths must go through stronger inspection and policy."

And the long-term clean execution model is:

> "If Jarvis is a Python-capable agent, give it its own explicit Python environment instead of letting Python capability leak in from ambient runtime state."
