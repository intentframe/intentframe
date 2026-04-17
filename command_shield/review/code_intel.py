"""Code content analysis — Python AST and shell regex.

Examines code strings and reports findings about what
the code does.
"""

from __future__ import annotations

import ast
import re

from command_shield.review.types import CodeIntel, ReviewFinding

# ── Dangerous Python imports ─────────────────────────────────────────

_DANGEROUS_PYTHON_IMPORTS: frozenset[str] = frozenset({
    "subprocess",
    "socket",
    "pickle",
    "ctypes",
    "importlib",
    "code",
    "codeop",
    "pty",
    "resource",
    "signal",
    "multiprocessing",
    "webbrowser",
    "antigravity",
    "http.server",
    "xmlrpc.server",
})

# ── Dangerous Python calls ───────────────────────────────────────────

_DANGEROUS_BUILTINS: frozenset[str] = frozenset({
    "eval", "exec", "compile", "__import__",
})

_DANGEROUS_OS_CALLS: frozenset[str] = frozenset({
    "system", "popen", "popen2", "popen3", "popen4",
    "execl", "execle", "execlp", "execlpe",
    "execv", "execve", "execvp", "execvpe",
    "spawnl", "spawnle", "spawnlp", "spawnlpe",
    "spawnv", "spawnve", "spawnvp", "spawnvpe",
})

_SUSPICIOUS_CALLS: dict[str, str] = {
    "os.chmod": "Filesystem permission change",
    "os.chown": "Filesystem ownership change",
    "shutil.rmtree": "Recursive directory deletion",
    "os.remove": "File deletion",
    "os.unlink": "File deletion",
    "os.rename": "File rename/move",
}

# ── Shell regex patterns ─────────────────────────────────────────────

_SHELL_DANGEROUS_PATTERNS: list[tuple[re.Pattern[str], str, str, str]] = [
    (
        re.compile(r"\beval\b"),
        "SHELL_EVAL", "Shell eval detected",
        "eval can execute arbitrary code from variables",
    ),
    (
        re.compile(r"\bsource\b.*https?://"),
        "SHELL_SOURCE_REMOTE", "Remote script sourcing",
        "source/dot command loading code from a URL",
    ),
    (
        re.compile(r"`[^`]*`[^`]*`[^`]*`"),
        "SHELL_NESTED_BACKTICKS", "Nested backtick substitution",
        "Nested backticks can obscure payload intent",
    ),
    (
        re.compile(r"\bchmod\b.*\b[0-7]{3,4}\b"),
        "SHELL_CHMOD_NUMERIC", "Numeric chmod",
        "Filesystem permission change via numeric mode",
    ),
    (
        re.compile(r"\bchown\b"),
        "SHELL_CHOWN", "Ownership change",
        "Filesystem ownership change",
    ),
    (
        re.compile(r">\s*/etc/|>\s*/var/|>\s*/usr/|>\s*/sys/|>\s*/proc/"),
        "SHELL_SYSTEM_REDIRECT", "Redirect to system path",
        "Output redirection targeting a system directory",
    ),
]


# ── Public API ───────────────────────────────────────────────────────

def analyze_python_code(source: str, *, file_path: str | None = None) -> CodeIntel:
    """Analyse Python source code for dangerous imports and calls.

    On SyntaxError the finding is recorded but analysis continues
    without AST walking (the caller decides whether to block).
    """
    findings: list[ReviewFinding] = []
    imports: list[str] = []
    dangerous_calls: list[str] = []

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        findings.append(ReviewFinding(
            source="code_intel",
            finding_id="PYTHON_SYNTAX_ERROR",
            severity="high",
            title="Python syntax error",
            detail=f"Code failed to parse: {exc.msg}",
            evidence=f"line {exc.lineno}: {(exc.text or '')[:120]}",
            confidence=1.0,
        ))
        return CodeIntel(
            language="python", file_path=file_path,
            imports=(), dangerous_calls=(),
            findings=tuple(findings),
        )

    for node in ast.walk(tree):
        # ── Imports ──────────────────────────────────────────────
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
                _check_import(alias.name, findings)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imports.append(module)
            _check_import(module, findings)

        # ── Calls ────────────────────────────────────────────────
        elif isinstance(node, ast.Call):
            call_name = _resolve_call_name(node)
            if call_name:
                _check_call(call_name, node, findings, dangerous_calls)

    return CodeIntel(
        language="python", file_path=file_path,
        imports=tuple(imports),
        dangerous_calls=tuple(dangerous_calls),
        findings=tuple(findings),
    )


def analyze_shell_code(source: str, *, file_path: str | None = None) -> CodeIntel:
    """Analyse shell source code via regex heuristics.

    Lighter analysis than Python — the existing Gate 0 (108 patterns)
    already catches the most dangerous shell constructs.  This focuses
    on patterns that inline code snippets might introduce.
    """
    findings: list[ReviewFinding] = []
    dangerous_calls: list[str] = []

    for pattern, finding_id, title, detail in _SHELL_DANGEROUS_PATTERNS:
        match = pattern.search(source)
        if match:
            dangerous_calls.append(finding_id)
            findings.append(ReviewFinding(
                source="code_intel",
                finding_id=finding_id,
                severity="high" if finding_id.startswith("SHELL_EVAL") else "medium",
                title=title,
                detail=detail,
                evidence=match.group()[:120],
                confidence=0.85,
            ))

    pipe_count = source.count("|")
    if pipe_count > 5:
        findings.append(ReviewFinding(
            source="code_intel",
            finding_id="SHELL_LONG_PIPE_CHAIN",
            severity="medium",
            title="Long pipe chain",
            detail=f"Pipe chain with {pipe_count} stages may obscure intent",
            evidence=source[:120],
            confidence=0.7,
        ))

    return CodeIntel(
        language="shell", file_path=file_path,
        imports=(),
        dangerous_calls=tuple(dangerous_calls),
        findings=tuple(findings),
    )


# ── Internal helpers ─────────────────────────────────────────────────

def _check_import(module: str, findings: list[ReviewFinding]) -> None:
    top_level = module.split(".")[0]
    full_match = module in _DANGEROUS_PYTHON_IMPORTS
    top_match = top_level in _DANGEROUS_PYTHON_IMPORTS

    if full_match or top_match:
        findings.append(ReviewFinding(
            source="code_intel",
            finding_id=f"DANGEROUS_IMPORT_{top_level}",
            severity="critical",
            title=f"Dangerous import: {module}",
            detail=f"Module '{module}' provides capabilities that may be unsafe",
            evidence=f"import {module}",
            confidence=1.0,
        ))


def _resolve_call_name(node: ast.Call) -> str | None:
    """Best-effort resolution of a call-node to a dotted name."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts: list[str] = [func.attr]
        current = func.value
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _check_call(
    call_name: str,
    node: ast.Call,
    findings: list[ReviewFinding],
    dangerous_calls: list[str],
) -> None:
    # Dangerous builtins
    if call_name in _DANGEROUS_BUILTINS:
        dangerous_calls.append(call_name)
        findings.append(ReviewFinding(
            source="code_intel",
            finding_id=f"DANGEROUS_CALL_{call_name}",
            severity="critical",
            title=f"Dangerous call: {call_name}()",
            detail=f"Built-in '{call_name}()' can execute arbitrary code",
            evidence=f"{call_name}() at line {node.lineno}",
            confidence=1.0,
        ))
        return

    # os.* dangerous calls
    if call_name.startswith("os."):
        method = call_name.split(".")[-1]
        if method in _DANGEROUS_OS_CALLS:
            dangerous_calls.append(call_name)
            findings.append(ReviewFinding(
                source="code_intel",
                finding_id=f"DANGEROUS_CALL_{call_name.replace('.', '_')}",
                severity="critical",
                title=f"Dangerous call: {call_name}()",
                detail=f"os.{method}() can execute commands or spawn processes",
                evidence=f"{call_name}() at line {node.lineno}",
                confidence=1.0,
            ))
            return

    # Suspicious but not necessarily critical
    if call_name in _SUSPICIOUS_CALLS:
        dangerous_calls.append(call_name)
        findings.append(ReviewFinding(
            source="code_intel",
            finding_id=f"SUSPICIOUS_CALL_{call_name.replace('.', '_')}",
            severity="high",
            title=f"Suspicious call: {call_name}()",
            detail=_SUSPICIOUS_CALLS[call_name],
            evidence=f"{call_name}() at line {node.lineno}",
            confidence=0.9,
        ))
