"""Operational configuration for command_shield.

ShieldConfig represents command_shield's own analysis bounds — not
user policy.  Caller-supplied overrides narrow (or widen) the envelope
within which the shield performs deep analysis.  Out-of-bound inputs
are reported as signals, never as blocking decisions.  Guardian owns
policy; command_shield owns facts.
"""

from __future__ import annotations

from dataclasses import dataclass


_DEFAULT_LANGUAGES: frozenset[str] = frozenset({"python", "shell"})


@dataclass(frozen=True)
class ShieldConfig:
    """Operational limits and scope for command_shield.

    Attributes:
        max_command_length: Commands longer than this emit a
            COMMAND_TOO_LARGE signal and skip all downstream analysis.
            Oversized input cannot be trusted by any tokenizer and
            wastes every downstream step.
        max_code_length: Code bodies (inline -c payloads or resolved
            file content) larger than this emit a CODE_TOO_LARGE signal
            and skip deterministic + LLM code analysis.  Oversized code
            floods AST + LLM.
        allowed_languages: Languages for which command_shield performs
            deep code analysis.  Commands / files in other languages
            receive an OUT_OF_SCOPE / resolved:unsupported-language
            signal but still pass through capability classification.
        enable_llm_review: When False, the LLM reviewer step is
            unconditionally skipped even in the deep variant.  Caller
            can disable the LLM entirely without changing which entry
            point they call.
        detect_file_path: When True, the command pipeline extracts
            containment edges (inline / referenced / piped-stdin /
            dynamic / interactive / compiled) and emits one signal
            per edge.  Cheap, default on — signals only, no I/O.
        auto_resolve_local: When True (requires `detect_file_path` and
            a caller-supplied `ResolveSession`), the pipeline attempts
            to read the files referenced by resolvable edges and run
            the code inspector on their contents.  Default off so the
            module stays pure by default — callers opt in explicitly.
        max_resolved_bytes: Hard cap per file when auto-resolving.
            Files larger than this emit a `resolved:too-large` signal
            and are not read.
        resolve_max_depth: Maximum edge-walk depth.  A value of 1 means
            only the outermost command's edges are followed; 2 allows
            one level of nested-interpreter indirection (`bash -c
            "python foo.py"`) to resolve `foo.py` as well.
        sniff_language_from_content: When True (default), resolved
            files whose extension/shebang are inconclusive fall back
            to lightweight content sniffing.  Turn off in strict
            environments where heuristic decisions are undesirable.
    """

    max_command_length: int = 10_000
    max_code_length: int = 50_000
    allowed_languages: frozenset[str] = _DEFAULT_LANGUAGES
    enable_llm_review: bool = True
    detect_file_path: bool = True
    auto_resolve_local: bool = False
    max_resolved_bytes: int = 1_000_000
    resolve_max_depth: int = 2
    sniff_language_from_content: bool = True


DEFAULT_CONFIG: ShieldConfig = ShieldConfig()
