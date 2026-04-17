"""Unified 12-step inspection pipeline for command_shield.

Order (cheapest → most expensive, each step gates the next):

    1.  Length check vs config.max_command_length
    2.  Normalize + tokenize
    3.  Pattern match (fixed-system catastrophic/needs-review regex)
    4.  Structural decomposition (bashlex AST / shlex fallback)
    5.  Language / role detection
    6.  Scope check vs config.allowed_languages
    7.  Capability classification
    8.  Code extraction (inline -c or caller-supplied file_content)
    9.  Code length check vs config.max_code_length
    10. Deterministic code analysis (Python AST / shell regex)
    11. LLM reviewer (conditional — async only)
    12. Assemble CommandReport

The 3-way verdict (SAFE / NEEDS_REVIEW / CATASTROPHIC) is driven ONLY
by fixed-system checks (patterns at step 3, structural evasion at
step 4).  Config-driven signals (COMMAND_TOO_LARGE, OUT_OF_SCOPE,
CODE_TOO_LARGE, capability:*) are emitted with severity but never
change the verdict.  Caller (Guardian/AE) decides what to do with them.
"""

from __future__ import annotations

import time

from command_shield.config import DEFAULT_CONFIG, ShieldConfig
from command_shield.patterns import match_patterns
from command_shield.structural import decompose, normalize
from command_shield.verdict import CommandReport, Signal, Verdict

# ── Entry points ─────────────────────────────────────────────────────


def inspect_command(
    command: str,
    *,
    file_content: str | None = None,
    file_path: str | None = None,
    config: ShieldConfig | None = None,
) -> CommandReport:
    """Synchronous full inspection (steps 1-10, 12).

    Deterministic, no network, no LLM.  Used by the IntentFrame
    pipeline as the runtime pre-pipeline gate.  The LLM reviewer step
    is skipped — callers who want it invoke `inspect_command_deep`.
    """
    cfg = config or DEFAULT_CONFIG
    return _run(
        command,
        file_content=file_content,
        file_path=file_path,
        config=cfg,
        run_llm=False,
    )


async def inspect_command_deep(
    command: str,
    *,
    file_content: str | None = None,
    file_path: str | None = None,
    config: ShieldConfig | None = None,
) -> CommandReport:
    """Asynchronous deep inspection (steps 1-12).

    Runs the full sync pipeline, then conditionally fires the LLM
    reviewer.  LLM gate: language in scope AND code present AND within
    size caps AND (deterministic findings OR non-trivial capabilities).
    """
    cfg = config or DEFAULT_CONFIG
    # Steps 1-10 + 12 synchronously so we have a complete report even
    # if the LLM gate declines or the LLM is unavailable.
    base = _run(
        command,
        file_content=file_content,
        file_path=file_path,
        config=cfg,
        run_llm=False,
    )

    if not cfg.enable_llm_review:
        return base

    # Late-bound so the sync path never imports the LLM module.
    from command_shield.review.reviewer import review_code

    code = _pick_code(base, file_content)
    if not _should_run_llm(base, code, cfg):
        return base

    language = base.language.language if base.language else None
    reviewer_findings, reviewer_summary, reviewer_ran = await review_code(
        code or "",
        language=language,
        command_context=command[:200],
    )

    return CommandReport(
        verdict=base.verdict,
        command=base.command,
        normalized_command=base.normalized_command,
        signals=base.signals,
        sub_commands=base.sub_commands,
        language=base.language,
        capabilities=base.capabilities,
        code_intel=base.code_intel,
        reviewer_findings=reviewer_findings,
        reviewer_summary=reviewer_summary,
        reviewer_ran=reviewer_ran,
        elapsed_ms=(time.monotonic() - _t0_of(base)) * 1000,
    )


# ── Core orchestrator ───────────────────────────────────────────────


def _run(
    command: str,
    *,
    file_content: str | None,
    file_path: str | None,
    config: ShieldConfig,
    run_llm: bool,  # reserved — sync path always False
) -> CommandReport:
    del run_llm  # only used by the async wrapper

    t0 = time.monotonic()

    # Empty / whitespace — SAFE, short-circuit.
    if not command or not command.strip():
        return CommandReport(
            verdict=Verdict.SAFE,
            command=command,
            normalized_command="",
            elapsed_ms=(time.monotonic() - t0) * 1000,
        )

    all_signals: list[Signal] = []

    # ── Step 1: Length check ────────────────────────────────────
    if len(command) > config.max_command_length:
        all_signals.append(Signal(
            check="size",
            signal_id="COMMAND_TOO_LARGE",
            description=(
                f"Command length {len(command)} exceeds "
                f"max_command_length {config.max_command_length}; "
                f"deep analysis skipped."
            ),
            evidence=command[:120],
            severity="high",
        ))
        return CommandReport(
            verdict=Verdict.SAFE,
            command=command,
            normalized_command="",
            signals=tuple(all_signals),
            elapsed_ms=(time.monotonic() - t0) * 1000,
        )

    # ── Step 2: Normalize ───────────────────────────────────────
    normalized = normalize(command)

    # ── Step 3: Pattern match (fixed-system, verdict-bearing) ───
    catastrophic, pattern_signals = _scan_patterns(command, normalized)
    all_signals.extend(pattern_signals)
    if catastrophic:
        return CommandReport(
            verdict=Verdict.CATASTROPHIC,
            command=command,
            normalized_command=normalized,
            signals=tuple(all_signals),
            elapsed_ms=(time.monotonic() - t0) * 1000,
        )

    # ── Step 4: Structural decomposition ────────────────────────
    sub_commands, structural_signals, indirections = decompose(command)
    all_signals.extend(structural_signals)

    # Sub-command pattern check (fixed-system, verdict-bearing).
    for sub in sub_commands:
        sub_normalized = normalize(sub)
        sub_verdict, sub_signals = match_patterns(sub_normalized)
        all_signals.extend(sub_signals)
        if sub_verdict is Verdict.CATASTROPHIC:
            return CommandReport(
                verdict=Verdict.CATASTROPHIC,
                command=command,
                normalized_command=normalized,
                signals=tuple(all_signals),
                sub_commands=tuple(sub_commands),
                elapsed_ms=(time.monotonic() - t0) * 1000,
            )

    # Indirection payload re-check (fixed-system, verdict-bearing).
    for payload in indirections:
        payload_norm = normalize(payload)
        pv, ps = match_patterns(payload_norm)
        all_signals.extend(ps)
        if pv is Verdict.CATASTROPHIC:
            return CommandReport(
                verdict=Verdict.CATASTROPHIC,
                command=command,
                normalized_command=normalized,
                signals=tuple(all_signals),
                sub_commands=tuple(sub_commands),
                elapsed_ms=(time.monotonic() - t0) * 1000,
            )
        if payload_norm != payload:
            rv, rs = match_patterns(payload)
            all_signals.extend(rs)
            if rv is Verdict.CATASTROPHIC:
                return CommandReport(
                    verdict=Verdict.CATASTROPHIC,
                    command=command,
                    normalized_command=normalized,
                    signals=tuple(all_signals),
                    sub_commands=tuple(sub_commands),
                    elapsed_ms=(time.monotonic() - t0) * 1000,
                )

    # Optional ShellCheck — purely advisory, never catastrophic.
    try:
        from command_shield.external.shellcheck import run_shellcheck
        all_signals.extend(run_shellcheck(command))
    except Exception:  # noqa: BLE001
        pass

    # ── Step 5: Language / role detection ───────────────────────
    from command_shield.review.language import detect_language, extract_inline_code

    language_info = detect_language(command)

    # ── Step 6: Scope check ─────────────────────────────────────
    in_scope = _language_in_scope(language_info, config)
    if not in_scope:
        all_signals.append(Signal(
            check="scope",
            signal_id="OUT_OF_SCOPE",
            description=(
                f"Language {language_info.language!r} is not in "
                f"configured allowed_languages; deep code analysis skipped."
            ),
            evidence=(language_info.interpreter or language_info.language or "")[:120],
            severity="info",
        ))

    # ── Step 7: Capability classification ───────────────────────
    from command_shield.classifier import classify_capabilities

    capabilities, capability_signals = classify_capabilities(
        normalized,
        sub_commands=tuple(sub_commands),
        indirections=tuple(indirections),
    )
    all_signals.extend(capability_signals)

    # ── Steps 8-10: Code extraction + length + deterministic analysis ─
    code_intel = None
    if in_scope:
        code = file_content
        if code is None:
            code = extract_inline_code(command, language_info)

        if code is not None:
            # Step 9: code length check
            if len(code) > config.max_code_length:
                all_signals.append(Signal(
                    check="size",
                    signal_id="CODE_TOO_LARGE",
                    description=(
                        f"Code length {len(code)} exceeds "
                        f"max_code_length {config.max_code_length}; "
                        f"code analysis skipped."
                    ),
                    evidence=code[:120],
                    severity="high",
                ))
            else:
                # Step 10: deterministic code analysis
                from command_shield.review.code_intel import (
                    analyze_python_code,
                    analyze_shell_code,
                )

                if (language_info.language or "shell") == "python":
                    code_intel = analyze_python_code(code, file_path=file_path)
                else:
                    code_intel = analyze_shell_code(code, file_path=file_path)

    # ── Step 12: Assemble final verdict ─────────────────────────
    # Fixed-system non-catastrophic findings can raise to NEEDS_REVIEW.
    # Config-driven signals never do.
    final = _final_verdict(all_signals)

    return CommandReport(
        verdict=final,
        command=command,
        normalized_command=normalized,
        signals=tuple(all_signals),
        sub_commands=tuple(sub_commands),
        language=language_info,
        capabilities=capabilities,
        code_intel=code_intel,
        elapsed_ms=(time.monotonic() - t0) * 1000,
    )


# ── Helpers ──────────────────────────────────────────────────────────


def _scan_patterns(
    command: str, normalized: str
) -> tuple[bool, list[Signal]]:
    """Match patterns on both normalized and raw.

    Returns (hit_catastrophic, signals).  Signals include every match
    found across both passes, deduplicated.  We explicitly look at the
    original string too since shlex normalisation can reshape the
    substring boundaries that a regex expects.
    """
    signals: list[Signal] = []
    verdict, first = match_patterns(normalized)
    signals.extend(first)
    if verdict is Verdict.CATASTROPHIC:
        return True, signals

    if normalized != command:
        orig_verdict, orig_signals = match_patterns(command)
        for sig in orig_signals:
            if sig not in signals:
                signals.append(sig)
        if orig_verdict is Verdict.CATASTROPHIC:
            return True, signals

    return False, signals


_VERDICT_BEARING_CHECKS: frozenset[str] = frozenset({
    "pattern",
    "structural",
    "indirection",
    "shellcheck",
})


def _final_verdict(signals: list[Signal]) -> Verdict:
    """Compute SAFE vs NEEDS_REVIEW from fixed-system signals only.

    CATASTROPHIC is handled by early-return paths above, never here.
    Config-driven signals (size, scope, capability) never change the
    verdict — they are advisory context for Guardian/AE.
    """
    for s in signals:
        if s.check in _VERDICT_BEARING_CHECKS:
            return Verdict.NEEDS_REVIEW
    return Verdict.SAFE


def _language_in_scope(language_info, config: ShieldConfig) -> bool:
    lang = (language_info.language or "").lower() if language_info else ""
    if not lang:
        return False
    return lang in {x.lower() for x in config.allowed_languages}


def _pick_code(report: CommandReport, file_content: str | None) -> str | None:
    """Resolve the code blob the LLM would analyse, for gate purposes."""
    if file_content is not None:
        return file_content
    if report.language is None:
        return None
    # Late-bound helper to avoid importing review.language for sync callers.
    from command_shield.review.language import extract_inline_code

    return extract_inline_code(report.command, report.language)


def _should_run_llm(
    report: CommandReport, code: str | None, config: ShieldConfig
) -> bool:
    """LLM reviewer gate (step 11).

    Conditions: language in scope AND code present AND within size cap
    AND (deterministic findings OR non-trivial capabilities).
    """
    if not config.enable_llm_review:
        return False
    if report.language is None:
        return False
    if not _language_in_scope(report.language, config):
        return False
    if code is None:
        return False
    if len(code) > config.max_code_length:
        return False

    has_det_findings = bool(report.code_intel and report.code_intel.findings)
    has_nontrivial_caps = any(
        cap != "capability:spawns_process" for cap in report.capabilities
    )
    return has_det_findings or has_nontrivial_caps


def _t0_of(report: CommandReport) -> float:
    """Reconstruct the start time from the sync report's elapsed_ms."""
    return time.monotonic() - (report.elapsed_ms / 1000.0)
