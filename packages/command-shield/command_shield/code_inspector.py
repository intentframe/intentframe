"""Leaf-level code inspection.

This module owns the *code*-level sub-pipeline — the part that
doesn't care whether its input came from an inline ``-c`` payload, a
resolved script file, a stdin-delivered snippet, or a notebook cell.
It is also the public entry point callers use when they already have
a code body in hand and want it inspected directly
(:func:`inspect_code`, :func:`inspect_code_deep`).

Stages, in order:

    1. Size check              vs ``config.max_code_length``
    2. Language selection      (explicit > extension > shebang > content)
    3. Binary guard            magic bytes / NUL density
    4. Dispatcher              python → AST, shell → regex
    5. Optional LLM review     deep path only, same gate as the command pipeline

No shell parsing, no edge walking, no I/O.
"""

from __future__ import annotations

import time

from command_shield.config import DEFAULT_CONFIG, ShieldConfig
from command_shield.language_sniff import detect_binary, sniff_language
from command_shield.verdict import CodeReport, Signal


def inspect_code(
    code: str,
    *,
    language: str | None = None,
    source_path: str | None = None,
    config: ShieldConfig | None = None,
) -> CodeReport:
    """Synchronous code-only inspection.  No LLM.

    Args:
        code: Raw source text to analyse.
        language: When provided, overrides sniffing.  Must be one of
            ``"python"`` / ``"shell"`` / ``"javascript"`` / etc.  When
            None, language is sniffed from ``source_path``'s extension,
            then shebang, then content heuristics (if
            ``config.sniff_language_from_content`` is True).
        source_path: File path the content came from, if any.  Used
            for extension-based sniffing and threaded through findings.
        config: :class:`ShieldConfig` — defaults to ``DEFAULT_CONFIG``.

    Never raises.
    """
    cfg = config or DEFAULT_CONFIG
    return _run(code, language=language, source_path=source_path, config=cfg, run_llm=False)


async def inspect_code_deep(
    code: str,
    *,
    language: str | None = None,
    source_path: str | None = None,
    config: ShieldConfig | None = None,
) -> CodeReport:
    """Asynchronous code inspection that may run the LLM reviewer.

    LLM gate matches the command pipeline: language in scope AND
    within size caps AND deterministic findings present.
    """
    cfg = config or DEFAULT_CONFIG
    base = _run(code, language=language, source_path=source_path, config=cfg, run_llm=False)

    if not cfg.enable_llm_review:
        return base

    from command_shield.review.reviewer import review_code as _llm_review

    if not _should_run_llm(base, code, cfg):
        return base

    findings, summary, ran = await _llm_review(
        code or "",
        language=base.language,
        command_context=(source_path or "")[:200],
    )
    return CodeReport(
        language=base.language,
        source_path=base.source_path,
        code_intel=base.code_intel,
        signals=base.signals,
        reviewer_findings=findings,
        reviewer_summary=summary,
        reviewer_ran=ran,
        elapsed_ms=base.elapsed_ms,
    )


# ── Internals ────────────────────────────────────────────────────────


def _pick_language(
    code: str,
    *,
    language: str | None,
    source_path: str | None,
    config: ShieldConfig,
) -> str:
    if language:
        return language
    return sniff_language(
        code or "",
        path=source_path,
        use_content=config.sniff_language_from_content,
    )


def _run(
    code: str,
    *,
    language: str | None,
    source_path: str | None,
    config: ShieldConfig,
    run_llm: bool,
) -> CodeReport:
    del run_llm  # the async wrapper owns the reviewer invocation
    t0 = time.monotonic()
    signals: list[Signal] = []

    # Empty or None → trivial report.
    if not code:
        return CodeReport(
            language=language,
            source_path=source_path,
            code_intel=None,
            signals=(),
            elapsed_ms=(time.monotonic() - t0) * 1000.0,
        )

    # Stage 1: size.
    if len(code) > config.max_code_length:
        signals.append(Signal(
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
        return CodeReport(
            language=language,
            source_path=source_path,
            code_intel=None,
            signals=tuple(signals),
            elapsed_ms=(time.monotonic() - t0) * 1000.0,
        )

    # Stage 2: binary guard before language selection.
    if detect_binary(code.encode("utf-8", errors="replace")):
        signals.append(Signal(
            check="resolved",
            signal_id="resolved:binary",
            description="Content looks like a binary artefact; code analysis skipped.",
            evidence=(source_path or "")[:120],
            severity="info",
        ))
        return CodeReport(
            language="binary",
            source_path=source_path,
            code_intel=None,
            signals=tuple(signals),
            elapsed_ms=(time.monotonic() - t0) * 1000.0,
        )

    # Stage 3: language.
    chosen = _pick_language(code, language=language, source_path=source_path, config=config)

    # Stage 4: dispatch.  Out-of-scope → signal only, no analyser.
    allowed = {x.lower() for x in config.allowed_languages}
    if chosen.lower() not in allowed:
        signals.append(Signal(
            check="resolved",
            signal_id="resolved:unsupported-language",
            description=(
                f"Code language {chosen!r} is not in configured "
                f"allowed_languages; code analysis skipped."
            ),
            evidence=(source_path or "")[:120],
            severity="info",
        ))
        return CodeReport(
            language=chosen,
            source_path=source_path,
            code_intel=None,
            signals=tuple(signals),
            elapsed_ms=(time.monotonic() - t0) * 1000.0,
        )

    code_intel = _dispatch_analyzer(chosen, code, source_path)
    return CodeReport(
        language=chosen,
        source_path=source_path,
        code_intel=code_intel,
        signals=tuple(signals),
        elapsed_ms=(time.monotonic() - t0) * 1000.0,
    )


def _dispatch_analyzer(language: str, code: str, source_path: str | None):
    """Pick the analyzer for *language* and run it.

    Imports are late-bound so callers who only want `inspect_code`
    never pay the cost of loading bashlex (via pipeline) or the LLM
    reviewer.
    """
    from command_shield.review.code_intel import analyze_python_code, analyze_shell_code

    if language == "python":
        return analyze_python_code(code, file_path=source_path)
    if language == "shell":
        return analyze_shell_code(code, file_path=source_path)
    return None


def _should_run_llm(report: CodeReport, code: str | None, config: ShieldConfig) -> bool:
    """Mirror of pipeline LLM gate, applied to a CodeReport."""
    if not config.enable_llm_review:
        return False
    if not code:
        return False
    if len(code) > config.max_code_length:
        return False
    if report.language is None:
        return False
    allowed = {x.lower() for x in config.allowed_languages}
    if report.language.lower() not in allowed:
        return False
    return bool(report.code_intel and report.code_intel.findings)


__all__ = ["inspect_code", "inspect_code_deep"]
