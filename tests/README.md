# IntentFrame Tests

Three test files verify the terminal command security pipeline — the deterministic layers
that protect against dangerous commands **regardless of LLM behavior**.

None of these tests call OpenAI. They are fast, free, and fully deterministic.

---

## Test Files

### `test_command_shield.py` — Standalone Command Classification Engine

Tests the `command_shield` module **in isolation** — no pipeline, no mocks, no runtime.
Pure pattern matching, normalization, AST decomposition, and signal detection.

| Test Class | What It Covers |
|---|---|
| `TestCatastrophicPatterns` | Core destroyers: `sudo`, `rm -rf /`, fork bomb, `chmod 777`, `dd`, `mkfs`, `shutdown`, device writes |
| `TestMacOSPatterns` | macOS-specific: `diskutil` (erase/partition/wipe), keychain access, `tmutil`, `dscl`, `csrutil`, `nvram`, TCC database |
| `TestPersistencePatterns` | Attacker persistence: `launchctl load/unload`, `cp`/`mv` to LaunchDaemons/LaunchAgents |
| `TestExfiltrationPatterns` | Remote code execution: `curl\|bash`, `wget\|sh`, `base64\|sh`, reverse shells (`/dev/tcp`), `ssh` remote rm |
| `TestCredentialAccessPatterns` | Credential theft: reads of `~/.ssh/id_rsa`, `~/.aws/credentials`, `.env`, `~/.kube/config`, and exfil via `curl`/`scp` |
| `TestGitPatterns` | Destructive git: `reset --hard`, `clean -fd`, `push --force`, `push -f`, `stash clear` |
| `TestShellWrapperPatterns` | Wrapped destruction: `bash -c 'rm ...'`, `find -exec rm`, `xargs rm`, `find / -delete` |
| `TestNormalization` | Deobfuscation: strips empty quotes (`su""do` → `sudo`), mixed quotes, preserves safe commands |
| `TestStructuralDecomposition` | Chained commands: `&&`, `;`, pipes — catches `sudo` hidden after safe prefix |
| `TestEvasionSignals` | NEEDS_REVIEW triggers: `$(...)`, backticks, `${VAR}` — flagged for AI review |
| `TestInterpreterIndirection` | Hidden execution via interpreters: `python3 -c`, `bash -c`, `osascript`, `perl -e`, `node --eval` |
| `TestQuickCheck` | Executor's fast-path subset: catches catastrophic, passes safe, catches obfuscated |
| `TestSafeCommands` | False-positive checks: `echo`, `ls`, `pwd`, `git status`, `npm install`, `rm` in safe dirs |
| `TestParseFailure` | Edge cases: malformed commands, empty string, whitespace-only |
| `TestAdversarialBypasses` | Evasion attacks: empty-quote sudo, `$(echo sudo)`, base64 pipe, `curl\|bash` |
| `TestCleanEnv` | Environment sanitization: PATH included, secrets (`AWS_SECRET_ACCESS_KEY`, `OPENAI_API_KEY`) stripped |
| `TestPatternDataIntegrity` | Data integrity: 50+ compiled patterns, 5 JSON files loaded, every pattern has required fields |

**Total:** 17 test classes, ~70 test cases (including parametrized expansions).

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
| `TestPolicyRegistryFloor` | Layer 1 — Policy Registry | System blocked patterns (`sudo`, `rm -rf /`, etc.) are always merged into user policy. Users can append but never remove system patterns. No duplicates. Allowed commands preserved alongside blocklist. |
| `TestAnalysisEngineCatastrophic` | Layer 2 — Analysis Engine | `_try_catastrophic_report()` returns deterministic `CRITICAL`/`IRREVERSIBLE` reports for known patterns **without calling AI**. Safe commands return `None` (fall through to AI). Non-RUN_COMMAND skipped. |
| `TestTerminalCheckerBlocklist` | Layer 3 — Guardian | `TerminalChecker.check()` enforces blocklist (substring match) and allowlist (glob match). Blocklist beats allowlist. Empty blocklist allows all. Custom user patterns work. |
| `TestTerminalCheckerSummarize` | Layer 3 — Guardian | Human-readable constraint summaries for Guardian prompts. |
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
│  Layer 1: Policy Registry floor                  │ ← test_terminal_blocklist.py
│  System patterns always merged, can't be removed │
└────────────────────┬────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────┐
│  Layer 2: Analysis Engine (deterministic path)   │ ← test_terminal_blocklist.py
│  Own catastrophic recognition, no AI needed      │
└────────────────────┬────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────┐
│  Layer 3: Guardian — TerminalChecker             │ ← test_terminal_blocklist.py
│  Blocklist/allowlist constraint enforcement      │
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

## Running

```bash
# All tests
uv run pytest tests/ -v

# Individual files
uv run pytest tests/test_command_shield.py -v
uv run pytest tests/test_pipeline_shield.py -v
uv run pytest tests/test_terminal_blocklist.py -v
```
