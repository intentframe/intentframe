"""Unified command-inspection pipeline.

A command is modelled as the root of a graph of code units linked by
:class:`Edge` s (inline / referenced / piped_stdin / dynamic /
interactive).  The pipeline walks the command through cheap → expensive
checks, emits structured signals, and — when configured — resolves
referenced scripts and delegates to :func:`inspect_code` for each
reachable body.

Stages:

    1.  Length check vs ``config.max_command_length``
    2.  Normalize + tokenize
    3.  Pattern match (verdict-bearing)
    4.  Structural decomposition (bashlex / shlex)
    5.  Language / role detection (command-level)
    6.  Scope check vs ``config.allowed_languages``
    7.  Capability classification
    8.  Containment-edge extraction
    9.  Edge walk + per-node ``inspect_code``
    10. LLM reviewer (deep/async only)
    11. Assemble :class:`CommandReport`

Verdict is set ONLY by fixed-system checks at steps 3 and 4.  Every
other finding is advisory context.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from command_shield.config import DEFAULT_CONFIG, ShieldConfig
from command_shield.patterns import match_patterns
from command_shield.structural import decompose, normalize
from command_shield.verdict import (
    CommandReport,
    Edge,
    ResolvedNode,
    Signal,
    Verdict,
)

if TYPE_CHECKING:
    from command_shield.resolve import ResolveSession


# ── Public entry points ──────────────────────────────────────────────


def inspect_command(
    command: str,
    *,
    session: "ResolveSession | None" = None,
    config: ShieldConfig | None = None,
) -> CommandReport:
    """Synchronous command inspection.

    Deterministic.  No LLM, no network.  Use this as the runtime
    pre-execution gate.

    Args:
        command: The shell command string to inspect.
        session: Optional :class:`ResolveSession`.  Required when
            ``config.auto_resolve_local`` is True; ignored otherwise.
        config: Operational bounds — defaults to ``DEFAULT_CONFIG``.
    """
    return _run(command, session=session, config=config or DEFAULT_CONFIG)


async def inspect_command_deep(
    command: str,
    *,
    session: "ResolveSession | None" = None,
    config: ShieldConfig | None = None,
) -> CommandReport:
    """Asynchronous command inspection with optional LLM review.

    Runs the sync pipeline first; then, if the LLM gate fires,
    invokes the reviewer over the first in-scope code body found.
    The gate requires language in scope, code within size caps, and
    either deterministic findings or a non-trivial capability set.
    """
    cfg = config or DEFAULT_CONFIG
    base = _run(command, session=session, config=cfg)

    if not cfg.enable_llm_review:
        return base

    code = _pick_code(base)
    if not _should_run_llm(base, code, cfg):
        return base

    from command_shield.review.reviewer import review_code

    language = base.language.language if base.language else None
    findings, summary, ran = await review_code(
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
        reviewer_findings=findings,
        reviewer_summary=summary,
        reviewer_ran=ran,
        edges=base.edges,
        resolved_nodes=base.resolved_nodes,
        script_path_candidate=base.script_path_candidate,
        script_resolved=base.script_resolved,
        elapsed_ms=(time.monotonic() - _t0_of(base)) * 1000,
    )


# ── Orchestrator ─────────────────────────────────────────────────────


def _run(
    command: str,
    *,
    session: "ResolveSession | None",
    config: ShieldConfig,
) -> CommandReport:
    t0 = time.monotonic()

    if not command or not command.strip():
        return CommandReport(
            verdict=Verdict.SAFE,
            command=command,
            normalized_command="",
            elapsed_ms=(time.monotonic() - t0) * 1000,
        )

    signals: list[Signal] = []

    # Step 1: length gate.
    if len(command) > config.max_command_length:
        signals.append(Signal(
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
            signals=tuple(signals),
            elapsed_ms=(time.monotonic() - t0) * 1000,
        )

    # Step 2: normalize.
    normalized = normalize(command)

    # Step 3: fixed-system patterns (verdict-bearing).
    catastrophic, pattern_signals = _scan_patterns(command, normalized)
    signals.extend(pattern_signals)
    if catastrophic:
        return CommandReport(
            verdict=Verdict.CATASTROPHIC,
            command=command,
            normalized_command=normalized,
            signals=tuple(signals),
            elapsed_ms=(time.monotonic() - t0) * 1000,
        )

    # Step 4: structural decomposition + sub-command / indirection
    # pattern rechecks (also verdict-bearing).
    sub_commands, structural_signals, indirections = decompose(command)
    signals.extend(structural_signals)

    for sub in sub_commands:
        v, sigs = match_patterns(normalize(sub))
        signals.extend(sigs)
        if v is Verdict.CATASTROPHIC:
            return CommandReport(
                verdict=Verdict.CATASTROPHIC,
                command=command,
                normalized_command=normalized,
                signals=tuple(signals),
                sub_commands=tuple(sub_commands),
                elapsed_ms=(time.monotonic() - t0) * 1000,
            )

    for payload in indirections:
        payload_norm = normalize(payload)
        v, sigs = match_patterns(payload_norm)
        signals.extend(sigs)
        if v is Verdict.CATASTROPHIC:
            return CommandReport(
                verdict=Verdict.CATASTROPHIC,
                command=command,
                normalized_command=normalized,
                signals=tuple(signals),
                sub_commands=tuple(sub_commands),
                elapsed_ms=(time.monotonic() - t0) * 1000,
            )
        if payload_norm != payload:
            v2, s2 = match_patterns(payload)
            signals.extend(s2)
            if v2 is Verdict.CATASTROPHIC:
                return CommandReport(
                    verdict=Verdict.CATASTROPHIC,
                    command=command,
                    normalized_command=normalized,
                    signals=tuple(signals),
                    sub_commands=tuple(sub_commands),
                    elapsed_ms=(time.monotonic() - t0) * 1000,
                )

    # Optional ShellCheck — advisory, never catastrophic.
    try:
        from command_shield.external.shellcheck import run_shellcheck
        signals.extend(run_shellcheck(command))
    except Exception:  # noqa: BLE001
        pass

    # Step 5: language / role.
    from command_shield.review.language import detect_language

    language_info = detect_language(command)

    # Step 6: scope.
    in_scope = _language_in_scope(language_info, config)
    if not in_scope:
        signals.append(Signal(
            check="scope",
            signal_id="OUT_OF_SCOPE",
            description=(
                f"Language {language_info.language!r} is not in "
                f"configured allowed_languages; deep code analysis skipped."
            ),
            evidence=(language_info.interpreter or language_info.language or "")[:120],
            severity="info",
        ))

    # Step 7: capabilities.
    from command_shield.classifier import classify_capabilities

    capabilities, capability_signals = classify_capabilities(
        normalized,
        sub_commands=tuple(sub_commands),
        indirections=tuple(indirections),
    )
    signals.extend(capability_signals)

    # Step 8: edges.  Always computed (pure, cheap); signals emitted
    # only when the caller opts in via ``detect_file_path``.
    from command_shield.edges import extract_edges

    edges = extract_edges(
        command,
        indirections=tuple(indirections),
        depth=0,
        max_depth=config.resolve_max_depth,
    )

    script_path_candidate: str | None = next(
        (e.path_arg for e in edges if e.kind == "referenced" and e.path_arg),
        None,
    )

    if config.detect_file_path:
        signals.extend(_edges_to_signals(edges))

    # Step 9: walk edges.  Inline bodies always inspected (no I/O).
    # Referenced bodies inspected only under auto_resolve_local.
    resolved_nodes: list[ResolvedNode] = []
    script_resolved = False

    if in_scope:
        for edge in edges:
            if edge.kind == "inline" and edge.body is not None:
                node, extra = _inspect_inline_edge(edge, config)
                resolved_nodes.append(node)
                signals.extend(extra)
            elif (
                edge.kind == "referenced"
                and edge.resolvable
                and config.auto_resolve_local
            ):
                node, extra = _inspect_referenced_edge(edge, session, config)
                resolved_nodes.append(node)
                signals.extend(extra)
                if node.code_report is not None and node.path is not None:
                    script_resolved = True

    # Step 10: expose the "most informative" resolved node's code_intel
    # at the top level so simple consumers read a single accessor.
    # "Most informative" = the first node that actually produced
    # findings; otherwise fall back to the first node with intel at all.
    top_intel = next(
        (
            n.code_report.code_intel
            for n in resolved_nodes
            if n.code_report is not None
            and n.code_report.code_intel is not None
            and n.code_report.code_intel.findings
        ),
        None,
    )
    if top_intel is None:
        top_intel = next(
            (
                n.code_report.code_intel
                for n in resolved_nodes
                if n.code_report is not None and n.code_report.code_intel is not None
            ),
            None,
        )

    return CommandReport(
        verdict=_final_verdict(signals),
        command=command,
        normalized_command=normalized,
        signals=tuple(signals),
        sub_commands=tuple(sub_commands),
        language=language_info,
        capabilities=capabilities,
        code_intel=top_intel,
        edges=edges,
        resolved_nodes=tuple(resolved_nodes),
        script_path_candidate=script_path_candidate,
        script_resolved=script_resolved,
        elapsed_ms=(time.monotonic() - t0) * 1000,
    )


# ── Helpers ──────────────────────────────────────────────────────────


def _scan_patterns(command: str, normalized: str) -> tuple[bool, list[Signal]]:
    """Match patterns on both normalized and raw strings.

    We run the normalised form first (cheapest) and fall through to
    the raw command string when normalisation changed it, because
    shlex can collapse substrings a regex expects to find verbatim.
    """
    signals: list[Signal] = []
    verdict, first = match_patterns(normalized)
    signals.extend(first)
    if verdict is Verdict.CATASTROPHIC:
        return True, signals

    if normalized != command:
        raw_verdict, raw_signals = match_patterns(command)
        for sig in raw_signals:
            if sig not in signals:
                signals.append(sig)
        if raw_verdict is Verdict.CATASTROPHIC:
            return True, signals

    return False, signals


_VERDICT_BEARING_CHECKS: frozenset[str] = frozenset({
    "pattern", "structural", "indirection", "shellcheck",
})


def _final_verdict(signals: list[Signal]) -> Verdict:
    """SAFE or NEEDS_REVIEW from fixed-system checks only.

    CATASTROPHIC is handled by early-return paths above.  Config-driven
    signals never change the verdict.
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


def _pick_code(report: CommandReport) -> str | None:
    """Return the code body the LLM should review, or None.

    Prefers a resolved node whose inspector already found something;
    otherwise falls back to the first inline body we have.
    """
    for node in report.resolved_nodes:
        if (
            node.code_report is not None
            and node.code_report.code_intel is not None
            and node.code_report.code_intel.findings
            and node.edge.body is not None
        ):
            return node.edge.body
    for node in report.resolved_nodes:
        if node.edge.body is not None:
            return node.edge.body
    return None


def _should_run_llm(
    report: CommandReport, code: str | None, config: ShieldConfig
) -> bool:
    if not config.enable_llm_review:
        return False
    if report.language is None:
        return False
    if not _language_in_scope(report.language, config):
        return False
    if not code:
        return False
    if len(code) > config.max_code_length:
        return False
    has_findings = bool(report.code_intel and report.code_intel.findings)
    has_nontrivial_caps = any(
        cap != "capability:spawns_process" for cap in report.capabilities
    )
    return has_findings or has_nontrivial_caps


def _t0_of(report: CommandReport) -> float:
    return time.monotonic() - (report.elapsed_ms / 1000.0)


# ── Edge → signal / walker helpers ──────────────────────────────────


def _edges_to_signals(edges: tuple[Edge, ...]) -> list[Signal]:
    """Translate each :class:`Edge` into an ``edge:<kind>`` signal."""
    out: list[Signal] = []
    for e in edges:
        if e.kind == "inline":
            desc = f"Inline {e.language or 'code'} payload embedded in command"
            sev = "info"
        elif e.kind == "referenced":
            desc = f"Command references {e.language or 'a'} script path: {e.path_arg!r}"
            sev = "info"
        elif e.kind == "piped_stdin":
            desc = f"Command pipes into {e.language or 'an'} interpreter (stdin exec)"
            sev = "medium"
        elif e.kind == "dynamic":
            desc = (
                f"Script path is non-literal ({e.unresolvable_reason}); "
                f"cannot be resolved statically"
            )
            sev = "medium"
        elif e.kind == "interactive":
            desc = f"Interpreter {e.language or ''} invoked without a body"
            sev = "info"
        else:
            desc = f"Edge {e.kind}"
            sev = "info"

        evidence = (
            e.body[:120] if e.body
            else (e.path_arg or e.unresolvable_reason or e.kind)[:120]
        )
        out.append(Signal(
            check="edge",
            signal_id=f"edge:{e.kind}",
            description=desc,
            evidence=evidence,
            severity=sev,
        ))
    return out


def _inspect_inline_edge(
    edge: Edge, config: ShieldConfig
) -> tuple[ResolvedNode, list[Signal]]:
    """Run :func:`inspect_code` on an inline edge's in-band body."""
    from command_shield.code_inspector import inspect_code

    report = inspect_code(
        edge.body or "",
        language=edge.language,
        source_path=None,
        config=config,
    )
    return ResolvedNode(
        edge=edge,
        path=None,
        language=report.language,
        code_report=report,
        skipped_reason=None,
    ), list(report.signals)


def _inspect_referenced_edge(
    edge: Edge,
    session: "ResolveSession | None",
    config: ShieldConfig,
) -> tuple[ResolvedNode, list[Signal]]:
    """Resolve *edge* via :func:`resolve_script` and inspect the body."""
    from command_shield.code_inspector import inspect_code
    from command_shield.language_sniff import detect_binary, sniff_language
    from command_shield.resolve import ResolveFailure, resolve_script

    extra: list[Signal] = []
    result = resolve_script(edge, session, max_bytes=config.max_resolved_bytes)

    if isinstance(result, ResolveFailure):
        sev = "medium" if result.reason == "outside-allow-roots" else "info"
        extra.append(Signal(
            check="resolved",
            signal_id=f"resolved:{result.reason}",
            description=f"Could not resolve script ({result.reason})",
            evidence=(result.detail or edge.path_arg or "")[:120],
            severity=sev,
        ))
        return ResolvedNode(
            edge=edge, path=None, language=None,
            code_report=None, skipped_reason=result.reason,
        ), extra

    extra.append(Signal(
        check="resolved",
        signal_id="resolved:auto-read",
        description=f"Auto-read local script: {result.path}",
        evidence=result.path[:200],
        severity="info",
    ))
    if result.truncated:
        extra.append(Signal(
            check="resolved",
            signal_id="resolved:truncated",
            description=(
                f"Script exceeded max_resolved_bytes "
                f"({config.max_resolved_bytes}); analysis ran on a prefix."
            ),
            evidence=result.path[:200],
            severity="info",
        ))

    if detect_binary(result.content):
        extra.append(Signal(
            check="resolved",
            signal_id="resolved:binary",
            description="Resolved file is binary; code analysis skipped.",
            evidence=result.path[:200],
            severity="info",
        ))
        return ResolvedNode(
            edge=edge, path=result.path, language="binary",
            code_report=None, skipped_reason="binary",
        ), extra

    text = result.content.decode("utf-8", errors="replace")
    sniffed = sniff_language(
        text,
        path=result.path,
        use_content=config.sniff_language_from_content,
    )
    chosen = edge.language if sniffed == "unknown" and edge.language else sniffed

    if edge.language and chosen and chosen != "unknown" and chosen != edge.language:
        extra.append(Signal(
            check="resolved",
            signal_id="resolved:language-mismatch",
            description=(
                f"Command implies {edge.language}; "
                f"resolved file sniffs as {chosen}"
            ),
            evidence=result.path[:200],
            severity="medium",
        ))

    report = inspect_code(
        text,
        language=chosen if chosen != "unknown" else None,
        source_path=result.path,
        config=config,
    )
    extra.extend(report.signals)

    return ResolvedNode(
        edge=edge,
        path=result.path,
        language=report.language,
        code_report=report,
        skipped_reason=None,
    ), extra


__all__ = ["inspect_command", "inspect_command_deep"]
