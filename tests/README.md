# IntentFrame Tests

Three test files verify the terminal command security pipeline — the deterministic layers
that protect against dangerous commands **regardless of LLM behavior**.

None of these tests call OpenAI. They are fast, free, and fully deterministic.

---

## Test Files

### `command_shield/tests/` — Standalone Command Classification Engine

Module-local tests for the `command_shield` package — no pipeline, no mocks, no runtime.
Covers patterns, normalization, AST decomposition, language sniffing, edge extraction,
file resolution, code inspection, and full `inspect_command` pipeline integration.

These tests are not limited to toy strings.  They include realistic command families such as:

- destructive shell commands (`sudo rm -rf /`, `mkfs`, `dd`, `wipefs`),
- macOS admin / persistence commands (`diskutil`, `security`, `launchctl`, `tmutil`, `csrutil`),
- exfiltration and download-and-exec patterns (`curl ... | bash`, reverse shells, credential reads),
- git footguns (`git reset --hard`, `git clean -fd`, force-push),
- benign day-to-day commands (`git status`, `git diff`, `npm install`, `pip install`).

Path-bearing behavior is also covered: relative paths, absolute paths, home-directory paths,
literal referenced scripts, `source .env`, allow-roots enforcement, symlink handling, and
dynamic path forms like `$SCRIPT`, `$(gen)`, and globs.  What the tests do **not** try to prove
is broad codebase understanding; they validate command inspection and focused code/script analysis.

| File | What It Covers |
|---|---|
| `test_patterns.py` | Catastrophic, macOS, persistence, exfiltration, credential, git, shell wrapper patterns; safe commands; pattern data integrity; direct `match_patterns` calls |
| `test_structural.py` | `normalize`, `decompose`, parse failure robustness |
| `test_quick_check.py` | `quick_check()`: catastrophic block, safe pass, obfuscated catch |
| `test_env.py` | `clean_env()`: PATH included, secrets (`AWS_SECRET_ACCESS_KEY`, `OPENAI_API_KEY`) stripped |
| `test_edges.py` | `extract_edges()`: inline, referenced, dynamic, interactive, piped_stdin edge kinds; depth; nesting; robustness |
| `test_resolve.py` | `resolve_script()`: file reading, `ResolveSession` interactions, symlinks, unsafe paths, allow-roots, truncation |
| `test_language_sniff.py` | `language_from_extension`, `language_from_shebang`, `language_from_content`, `sniff_language`, `detect_binary` |
| `test_code_inspector.py` | `inspect_code()`: language detection, signals (unsupported, oversize, binary), Python/shell findings |
| `test_pipeline.py` | End-to-end `inspect_command()`: edge/resolved signals, capabilities (`capability:stdin_exec`), verdict stability, dataclass immutability |

**Total:** 9 test files, 246 test cases.

Run them with:

```bash
uv run pytest command_shield/tests/ -v
```

---

### `test_pipeline_shield.py` — Runtime Integration (command_shield inside `process_intent`)

Tests how `command_shield` integrates with `IntentFrameRuntime.process_intent()`.
Uses **mocked** Analysis Engine, Guardian, and Executor to verify routing behavior.

| Test Class | What It Covers |
|---|---|
| `TestCatastrophicRejection` | CATASTROPHIC commands are rejected **before** Analysis Engine runs. Asserts `analyze.assert_not_called()`, `validate.assert_not_called()`, `execute.assert_not_called()`. Checks audit log records the block with `decision_path=command_shield`. |
| `TestSafeFlow` | SAFE commands flow through the full pipeline. Analysis Engine called, signals are empty, non-RUN_COMMAND intents bypass shield entirely. |
| `TestNeedsReviewFlow` | NEEDS_REVIEW commands (e.g. `echo $(curl ...)`) reach the AI with `terminal_command_signals` attached. Signals are `Signal` objects with `.check` and `.signal_id`. Guardian still called. |
| `TestPipelineEdgeCases` | Empty commands reach the pipeline (not treated as catastrophic). Commands in `intent.data['command']` are checked. Request counter increments for both blocked and allowed intents. |

**Total:** 4 test classes, 14 test cases.

---

### `test_terminal_blocklist.py` — Defense-in-Depth Across All Layers

Tests that **each component independently catches dangerous commands** — if any single
layer is bypassed or compromised, the others still block.

| Test Class | Layer | What It Covers |
|---|---|---|
| `TestTerminalBundleSystemFloor` | Layer 1 — Terminal bundle | `SYSTEM_TERMINAL_BLOCKED_PATTERNS` enforced by `TerminalActionBundle.enforce_constraints`. Users can append but never remove system patterns. No duplicates. Allowed commands preserved alongside blocklist. |
| `TestTerminalCatastrophicPatterns` | Layer 2 — Analysis Engine | `try_catastrophic_report()` returns deterministic `CRITICAL`/`IRREVERSIBLE` reports for known patterns **without calling AI**. Safe commands return `None` (fall through to AI). Non-RUN_COMMAND skipped. |
| `TestTerminalBundleBlocklist` | Layer 3 — Terminal bundle | `enforce_constraints` enforces blocklist (substring match) and allowlist (glob match). Blocklist beats allowlist. Empty blocklist allows all (subject to system floor). Custom user patterns work. |
| `TestTerminalBundleDescribe` | Layer 3 — Terminal bundle | Human-readable constraint summaries for Guardian prompts via `describe_constraints`. |
| `TestTerminalBundleCapabilities` | Layer 3 — Terminal bundle | `deny_capabilities` / `allow_capabilities` enforcement using `CommandIntel` from command_shield. |
| `TestAdapterCommandShieldFloor` | Layer 4 — Executor | `TerminalAdapter` calls `command_shield.quick_check()` as a non-negotiable last resort. Blocks catastrophic commands. Returns well-formed `ExecutionResult`. Allows safe commands and safe `rm` paths. 50+ patterns loaded. |
| `TestComponentIndependence` | All layers | Walks `sudo` through **every layer** independently and proves each one blocks it. Verifies all layers know the original 6 blocked patterns. |
| `TestEdgeCases` | Layer 4 | Empty command, missing command key, wrong action type, pattern hidden in middle of chained command, `TerminalConstraints` model is frozen (immutable). |

**Total:** 7 test classes, ~40 test cases.

---

## Architecture: What Each Layer Does

```
Intent arrives
    │
    ▼
┌─────────────────────────────────────────────────┐
│  Layer 0: command_shield (Runtime pre-gate)      │ ← test_pipeline_shield.py
│  CATASTROPHIC → reject immediately               │
│  NEEDS_REVIEW → forward signals to AI            │
│  SAFE → continue                                 │
└────────────────────┬────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────┐
│  Layer 1: Terminal bundle system floor           │ ← test_terminal_blocklist.py
│  SYSTEM_TERMINAL_BLOCKED_PATTERNS at enforce time│
└────────────────────┬────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────┐
│  Layer 2: Analysis Engine (deterministic path)   │ ← test_terminal_blocklist.py
│  Own catastrophic recognition, no AI needed      │
└────────────────────┬────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────┐
│  Layer 3: Terminal bundle — enforce_constraints  │ ← test_terminal_blocklist.py
│  Blocklist/allowlist/capability enforcement      │
└────────────────────┬────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────┐
│  Layer 4: Executor — Adapter quick_check()       │ ← test_terminal_blocklist.py
│  Non-negotiable last resort before shell exec    │
└─────────────────────────────────────────────────┘
```

## What's NOT Covered

These tests cover **deterministic terminal command security only**. The following are
out of scope for this test suite:

- **AI Analysis Engine semantic analysis** (LLM-dependent, tested via `demo/tests/`)
- **AI Guardian policy decisions** (LLM-dependent)
- **Non-command actions** (email, file, calendar — rely more on AI path)
- **Prompt injection via `reason`/`data` fields** (no tests for adversarial agent-controlled fields in AI prompts)
- **Actor SDK** (client-side, not a security boundary)
- **Onboarding Engine** (handshake guardrail generation)

For manual onboarding experiments, use the standalone script:

```bash
.venv/bin/python tests/test_onboarding_jarvis_policy.py --fs-mode vfs
.venv/bin/python tests/test_onboarding_jarvis_policy.py --fs-mode host
.venv/bin/python tests/test_onboarding_jarvis_policy.py --fs-mode none
.venv/bin/python tests/test_onboarding_jarvis_policy.py --fs-mode both
```

That harness does **not** start the full gateway/runtime stack. It builds
Jarvis capabilities plus the gateway bootstrap policy in-process and
runs only `AIOnboardingEngine.onboard()`. See
[`docs/vfs-vs-host-tools.md`](../docs/vfs-vs-host-tools.md) for why the
filesystem family split matters when reading those outputs.

## Running

```bash
# All workspace-level tests
uv run pytest tests/ -v

# command_shield module tests (standalone, no runtime)
uv run pytest command_shield/tests/ -v

# Runtime integration tests
uv run pytest tests/test_pipeline_shield.py -v
uv run pytest tests/test_terminal_blocklist.py -v
```
