# `command_shield`

Deterministic command inspection for `RUN_COMMAND`-style actions.

`command_shield` examines a command string and returns a structured, immutable report describing:

- whether the command is immediately catastrophic,
- whether fixed-system patterns suggest it needs review,
- what deterministic capabilities it exposes,
- what language / interpreter shape it appears to use,
- and, when code is available, what static-analysis findings were observed.

It is intentionally a **fact producer**, not a policy engine:

- `command_shield` decides only the 3-way verdict (`CATASTROPHIC`, `NEEDS_REVIEW`, `SAFE`) from fixed-system checks.
- It does **not** allow or deny commands based on user policy.
- It does **not** know about Guardian, AE, runtime context, session state, or root.
- Consumers decide what to do with the emitted facts.

## Why It Exists

Arbitrary shell commands are the one action class that can hide a lot of behavior inside a single string:

- destructive shell primitives,
- interpreter indirection like `python -c ...`,
- chained / nested subcommands,
- package installs, compilation, listeners, background jobs,
- inline Python or shell code,
- code that touches system paths or spawns processes.

If every caller had to rediscover those mechanics itself, every downstream policy or AI layer would spend time re-parsing command strings instead of reasoning about user intent and authorization.

`command_shield` exists to centralize that mechanical inspection into one standalone module with a small, stable contract:

- **cheap checks run first,**
- **deterministic facts are produced once,**
- **verdict semantics stay stable,**
- **higher layers consume a trusted report instead of raw shell trivia.**

## What It Does

### Core verdict

Every inspection returns a `CommandReport` with:

- `verdict`: one of `Verdict.CATASTROPHIC`, `Verdict.NEEDS_REVIEW`, `Verdict.SAFE`
- `signals`: structured `Signal` objects
- `command` and `normalized_command`
- `sub_commands` discovered during structural decomposition

The verdict is intentionally narrow:

- `CATASTROPHIC` means known fixed-system catastrophic patterns were found.
- `NEEDS_REVIEW` means fixed-system non-catastrophic review-worthy signals were found.
- `SAFE` means no fixed-system review-worthy patterns were found.

Config-driven findings like `COMMAND_TOO_LARGE`, `OUT_OF_SCOPE`, `CODE_TOO_LARGE`, and `capability:*` **do not change the verdict**. They are advisory facts for consumers.

### Extended report fields

As later steps run, `CommandReport` may also include:

- `language`: `LanguageInfo`
- `capabilities`: tuple of capability tags
- `code_intel`: `CodeIntel`
- `reviewer_findings`, `reviewer_summary`, `reviewer_ran` (deep async path only)
- `elapsed_ms`

These fields default cleanly, so callers that only read `verdict` and `signals` keep working unchanged.

## How It Works

All full inspection flows through a single ordered pipeline in `command_shield.pipeline`:

1. `max_command_length` check
2. normalize + tokenize
3. fixed-system pattern match
4. structural decomposition / indirection re-check
5. language / role detection
6. scope check against `allowed_languages`
7. capability classification
8. code extraction
9. `max_code_length` check
10. deterministic code analysis
11. optional LLM reviewer (async path only)
12. assemble `CommandReport`

The ordering is deliberate: cheapest and most certain checks run first, and expensive checks only run when earlier gates allow them to.

### 1. Pattern and structural analysis

The first decisive layer is pattern + structure:

- commands are normalized,
- known catastrophic and review-worthy patterns are matched,
- shell structure is decomposed into subcommands,
- interpreter indirections / payloads are re-scanned.

This is where the verdict comes from.

### 2. Language detection

`command_shield` classifies the command shape using `LanguageInfo`:

- detected language (`python`, `shell`, `javascript`, `ruby`, etc.),
- interpreter (`python3`, `bash`, `node`, ...),
- whether code is inline (`-c`, `-e`, `--eval`),
- whether the command appears to execute a file.

This lets consumers distinguish, for example:

- plain shell utility invocation,
- inline Python,
- Python script execution,
- shell script execution,
- non-Python / non-shell interpreters.

### 3. Capability classification

Step 7 emits deterministic capability tags describing what the command can do, not whether it is allowed.

Current capability families:

- package install:
  - `capability:package_install:pip`
  - `capability:package_install:npm`
  - `capability:package_install:brew`
  - `capability:package_install:apt`
  - `capability:package_install:yum`
  - `capability:package_install:dnf`
  - `capability:package_install:pacman`
  - `capability:package_install:apk`
  - `capability:package_install:gem`
  - `capability:package_install:cargo`
  - `capability:package_install:go`
  - `capability:package_install:composer`
- script execution:
  - `capability:script_execution:python`
  - `capability:script_execution:node`
  - `capability:script_execution:ruby`
  - `capability:script_execution:perl`
  - `capability:script_execution:shell`
  - `capability:script_execution:local_binary`
- `capability:compilation`
- `capability:network_bind`
- `capability:background_exec`
- `capability:download_and_exec`
- `capability:binary_download`
- `capability:process_signal`
- `capability:spawns_process`

These tags are intended for policy consumers. A caller can match exact tags or do prefix matching such as:

- `capability:package_install:*`
- `capability:script_execution:*`

### 4. Deterministic code analysis

When code content is available, `command_shield` performs static analysis:

- Python via AST walk
- shell via regex heuristics

Code is available when:

- the caller passes `file_content=...`, or
- the command contains inline code such as `python -c "..."` or `bash -c "..."`.

Important: `command_shield` itself is not session-aware. If a consumer wants analysis of a file written earlier in the session, it must resolve that file content and pass it in as `file_content`.

#### Python findings

Examples of Python findings emitted on `CodeIntel.findings`:

- `DANGEROUS_IMPORT_subprocess`
- `DANGEROUS_IMPORT_socket`
- `DANGEROUS_IMPORT_flask`
- `DANGEROUS_CALL_eval`
- `DANGEROUS_CALL_exec`
- `DANGEROUS_CALL_os_system`
- `DANGEROUS_CALL_os_kill`
- `DANGEROUS_CALL_signal_signal`
- `NETWORK_SERVER_BIND`
- `FILE_SYSTEM_ESCAPE_OPEN`
- `REFERENCES_INTENTFRAME`
- `PYTHON_SYNTAX_ERROR`

#### Shell findings

Examples of shell findings:

- `SHELL_EVAL`
- `SHELL_SOURCE_REMOTE`
- `SHELL_NESTED_BACKTICKS`
- `SHELL_CHMOD_NUMERIC`
- `SHELL_CHOWN`
- `SHELL_SYSTEM_REDIRECT`
- `SHELL_LONG_PIPE_CHAIN`
- `REFERENCES_INTENTFRAME`

These findings are structured, severity-bearing facts. They still do not make policy decisions.

## Public API

`command_shield` intentionally exposes a small surface:

### `inspect_command(...) -> CommandReport`

Synchronous, deterministic full inspection.

Uses steps 1-10 and 12. No LLM, no network, no policy decisions.

This is the primary entry point for runtime / policy / pre-execution callers.

### `inspect_command_deep(...) -> CommandReport`

Asynchronous deep inspection.

Runs the same sync pipeline first, then conditionally runs the LLM reviewer when:

- LLM review is enabled,
- the language is in scope,
- code is available,
- code size is within bounds,
- and deterministic findings or non-trivial capabilities justify the extra step.

If the LLM is unavailable or declined by the gate, the caller still gets the full deterministic report.

### `quick_check(...) -> CommandReport`

Fast executor-floor check.

This is a deliberately small subset of the full pipeline:

- size check,
- normalize,
- pattern match,
- inline interpreter indirection re-check.

It returns only the catastrophic / safe floor needed by an executor adapter right before subprocess launch.

### Backward-compatible aliases

- `analyze(...)` is a compatibility alias for `inspect_command(...)`
- `review_command(...)` is a compatibility adapter that returns `CommandReview`

## Configuration

`ShieldConfig` controls operational analysis bounds, not user policy:

```python
from command_shield import ShieldConfig

config = ShieldConfig(
    max_command_length=10_000,
    max_code_length=50_000,
    allowed_languages=frozenset({"python", "shell"}),
    enable_llm_review=True,
)
```

Meaning of each field:

- `max_command_length`: oversized commands emit `COMMAND_TOO_LARGE` and skip deeper analysis.
- `max_code_length`: oversized code emits `CODE_TOO_LARGE` and skips code analysis.
- `allowed_languages`: only these languages get deep code analysis.
- `enable_llm_review`: disables the deep reviewer even on the async path.

Again: this is **inspection scope**, not authorization policy.

## Consumer Usage

### 1. Runtime / policy caller

If you are a policy layer, analysis engine, or runtime gateway, call the sync API and consume the returned facts:

```python
from command_shield import inspect_command

report = inspect_command(command, file_content=file_content, file_path=file_path)

if report.is_catastrophic:
    # hard stop
    ...

# otherwise read facts
capabilities = report.capabilities
signals = report.signals
code_findings = report.code_intel.findings if report.code_intel else ()
```

Typical consumer behavior:

- block immediately on `CATASTROPHIC`,
- use `capabilities` for deterministic policy,
- use `code_intel.findings` for deterministic policy or AI context,
- use `signals` as the stable cross-cutting summary.

### 2. Executor caller

If you are about to spawn a subprocess and want a last-resort floor:

```python
from command_shield import quick_check

report = quick_check(command)
if report.is_catastrophic:
    raise RuntimeError("blocked catastrophic command")
```

This should be used as a final floor, not as a replacement for full inspection.

### 3. Deep inspection caller

If you explicitly want the optional reviewer path:

```python
from command_shield import inspect_command_deep

report = await inspect_command_deep(
    command,
    file_content=file_content,
    file_path=file_path,
)

if report.reviewer_ran:
    ...
```

This is useful for offline triage or explicit deep-review flows. Many consumers only need the sync path.

### 4. Policy examples

`command_shield` does not implement policy, but it is designed to make policy easy.

Examples of deterministic policy questions consumers can ask:

- Does this command install packages?
  - match `capability:package_install:*`
- Allow `pip` but deny `apt`?
  - allow `capability:package_install:pip`
  - deny `capability:package_install:apt`
- Allow Python scripts but deny Node scripts?
  - allow `capability:script_execution:python`
  - deny `capability:script_execution:node`
- Deny all listeners?
  - deny `capability:network_bind`
- Deny any code touching system paths?
  - deny `FILE_SYSTEM_ESCAPE_OPEN`
- Flag any code that references runtime internals?
  - deny `REFERENCES_INTENTFRAME`

## Design Principles

### Deterministic first

Known dangerous command structures should be classified without spending LLM tokens.

### Facts, not policy

`command_shield` answers:

- what is this command structurally,
- what did it match,
- what capabilities does it expose,
- what static-analysis findings exist.

It does not answer:

- should this user be allowed to do it,
- is root acceptable here,
- does the current task justify the behavior,
- what does session history imply.

Those are consumer responsibilities.

### Stable contract

The most important contract is small and durable:

- `CommandReport.verdict`
- `CommandReport.signals`
- `CommandReport.sub_commands`

Everything else is additive.

### Standalone module

`command_shield` deliberately does not import:

- `intentframe_components`
- `policy_registry`
- `executor`

That keeps it reusable as a pure inspection library.

## What `command_shield` Does Not Do

- It does not apply user policy.
- It does not know execution privilege or root context.
- It does not track session write history on its own.
- It does not prove code is safe.
- It does not replace downstream semantic analysis.
- It does not mutate commands.

It is a deterministic inspection module whose job is to turn a raw command string into structured facts.

## Recommended Consumer Pattern

For most consumers, the intended pattern is:

1. call `inspect_command(...)`
2. hard-block `CATASTROPHIC`
3. consume `capabilities`, `signals`, and `code_intel`
4. apply policy
5. only call deeper AI reasoning when deterministic gates do not already decide the outcome

That keeps mechanical inspection centralized in one place and reserves expensive semantic reasoning for the cases where it is actually needed.
