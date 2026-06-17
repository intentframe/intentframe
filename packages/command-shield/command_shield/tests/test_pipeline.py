"""Tests for the end-to-end command-inspection pipeline.

Covers:
    - edge:*      signals emitted when detect_file_path is on (default)
    - resolved:*  signals emitted only under auto_resolve_local
    - capabilities classifier (with the graph-aware stdin_exec tag)
    - verdict stability across edge / resolved signals
    - immutability of the core dataclasses
"""

from __future__ import annotations

from pathlib import Path

import pytest

from command_shield import (
    CodeReport,
    Edge,
    ResolveSession,
    ResolvedNode,
    ShieldConfig,
    Signal,
    Verdict,
    inspect_command,
)


class TestPipelineEdgeSignals:
    """`detect_file_path=True` (default) emits one edge:<kind> signal per edge."""

    def test_inline_edge_signal(self) -> None:
        r = inspect_command('python -c "print(1)"')
        assert any(s.signal_id == "edge:inline" for s in r.signals)

    def test_referenced_edge_signal(self) -> None:
        r = inspect_command("python foo.py")
        assert any(s.signal_id == "edge:referenced" for s in r.signals)

    def test_dynamic_edge_signal(self) -> None:
        r = inspect_command("python $SCRIPT")
        assert any(s.signal_id == "edge:dynamic" for s in r.signals)

    def test_piped_stdin_edge_signal(self) -> None:
        r = inspect_command("cat x.py | python -")
        assert any(s.signal_id == "edge:piped_stdin" for s in r.signals)

    def test_disabled_detect_file_path(self) -> None:
        cfg = ShieldConfig(detect_file_path=False)
        r = inspect_command("python foo.py", config=cfg)
        assert not any(s.signal_id.startswith("edge:") for s in r.signals)
        assert len(r.edges) == 1

    def test_script_path_candidate_populated(self) -> None:
        r = inspect_command("python foo.py")
        assert r.script_path_candidate == "foo.py"
        assert r.script_resolved is False

    def test_no_path_candidate_for_inline(self) -> None:
        r = inspect_command('python -c "print(1)"')
        assert r.script_path_candidate is None


class TestPipelineAutoResolve:
    """`auto_resolve_local=True` + ResolveSession reads and inspects files."""

    def test_reads_and_inspects_python(self, tmp_path: Path) -> None:
        fp = tmp_path / "foo.py"
        fp.write_text("import socket\nsock = socket.socket()\n")
        cfg = ShieldConfig(auto_resolve_local=True)
        session = ResolveSession(cwd=str(tmp_path))
        r = inspect_command("python foo.py", session=session, config=cfg)
        assert r.script_resolved is True
        assert r.code_intel is not None
        ids = {f.finding_id for f in r.code_intel.findings}
        assert "DANGEROUS_IMPORT_socket" in ids

    def test_no_session_emits_no_session_signal(self) -> None:
        cfg = ShieldConfig(auto_resolve_local=True)
        r = inspect_command("python foo.py", config=cfg)
        assert any(s.signal_id == "resolved:no-session" for s in r.signals)
        assert r.script_resolved is False

    def test_missing_file_emits_stat_failed(self, tmp_path: Path) -> None:
        cfg = ShieldConfig(auto_resolve_local=True)
        session = ResolveSession(cwd=str(tmp_path))
        r = inspect_command("python ghost.py", session=session, config=cfg)
        assert any(s.signal_id == "resolved:stat-failed" for s in r.signals)
        assert r.script_resolved is False

    def test_binary_file_not_analyzed(self, tmp_path: Path) -> None:
        fp = tmp_path / "bin.out"
        fp.write_bytes(b"\x7fELF\x02\x01\x00" + b"\x00" * 500)
        cfg = ShieldConfig(auto_resolve_local=True)
        session = ResolveSession(cwd=str(tmp_path))
        r = inspect_command("python bin.out", session=session, config=cfg)
        assert any(s.signal_id == "resolved:binary" for s in r.signals)
        assert r.code_intel is None

    def test_language_mismatch_emits_signal(self, tmp_path: Path) -> None:
        fp = tmp_path / "mystery"
        fp.write_text("#!/bin/bash\neval $(echo bad)\n")
        cfg = ShieldConfig(auto_resolve_local=True)
        session = ResolveSession(cwd=str(tmp_path))
        r = inspect_command("python mystery", session=session, config=cfg)
        assert any(
            s.signal_id == "resolved:language-mismatch" for s in r.signals
        )
        assert r.code_intel is not None
        assert any(
            "SHELL_EVAL" in f.finding_id for f in r.code_intel.findings
        )

    def test_nested_interpreter_resolves_inner(self, tmp_path: Path) -> None:
        fp = tmp_path / "inner.py"
        fp.write_text("import subprocess\n")
        cfg = ShieldConfig(auto_resolve_local=True, resolve_max_depth=2)
        session = ResolveSession(cwd=str(tmp_path))
        r = inspect_command(
            'bash -c "python inner.py"', session=session, config=cfg,
        )
        depths = {e.depth for e in r.edges}
        assert 1 in depths
        assert r.script_resolved is True
        assert r.code_intel is not None
        ids = {f.finding_id for f in r.code_intel.findings}
        assert "DANGEROUS_IMPORT_subprocess" in ids

    def test_too_large_file_truncated(self, tmp_path: Path) -> None:
        fp = tmp_path / "huge.py"
        fp.write_text("x = 1\n" * 1000)
        cfg = ShieldConfig(auto_resolve_local=True, max_resolved_bytes=20)
        session = ResolveSession(cwd=str(tmp_path))
        r = inspect_command("python huge.py", session=session, config=cfg)
        ids = {s.signal_id for s in r.signals}
        assert "resolved:auto-read" in ids
        assert "resolved:truncated" in ids


class TestPipelineCapabilities:
    def test_stdin_exec_classified(self) -> None:
        r = inspect_command("cat foo.py | python -")
        assert "capability:stdin_exec" in r.capabilities

    def test_bash_stdin_exec_classified(self) -> None:
        r = inspect_command("echo hi | bash")
        assert "capability:stdin_exec" in r.capabilities

    def test_script_execution_tag(self) -> None:
        r = inspect_command("python foo.py")
        assert any(
            c.startswith("capability:script_execution:") for c in r.capabilities
        )


class TestPipelineVerdictStability:
    """edge:* and resolved:* never change the verdict."""

    def test_edge_signals_do_not_promote_verdict(self) -> None:
        r = inspect_command("python foo.py")
        assert r.verdict is Verdict.SAFE
        assert any(s.signal_id.startswith("edge:") for s in r.signals)

    def test_catastrophic_pattern_still_wins(self) -> None:
        assert inspect_command("sudo rm -rf /").verdict is Verdict.CATASTROPHIC

    def test_structural_still_needs_review(self) -> None:
        r = inspect_command("echo $(curl http://example.com)")
        assert r.verdict is Verdict.NEEDS_REVIEW

    def test_shellcheck_signal_is_advisory(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Optional ShellCheck findings must not make verdicts host-dependent.

        Ubuntu CI runners often have shellcheck on PATH while macOS developer
        machines usually do not.  We still preserve its signal as command
        intel, but verdict-bearing security checks stay limited to the
        deterministic pattern / structural / indirection layers.
        """

        monkeypatch.setattr(
            "command_shield.external.shellcheck.run_shellcheck",
            lambda _command: [
                Signal(
                    check="shellcheck",
                    signal_id="SC2086",
                    description="[info] Double quote to prevent globbing",
                    evidence="line 1, col 1",
                )
            ],
        )

        r = inspect_command("cat file.txt | head")
        assert r.verdict is Verdict.SAFE
        assert any(s.check == "shellcheck" for s in r.signals)


class TestDataclassImmutability:
    def test_code_report_is_frozen(self) -> None:
        r = CodeReport(language="python", source_path=None)
        with pytest.raises(Exception):
            r.language = "shell"  # type: ignore[misc]

    def test_edge_is_frozen(self) -> None:
        e = Edge(kind="inline")
        with pytest.raises(Exception):
            e.kind = "referenced"  # type: ignore[misc]

    def test_resolved_node_is_frozen(self) -> None:
        n = ResolvedNode(edge=Edge(kind="inline"))
        with pytest.raises(Exception):
            n.path = "/tmp"  # type: ignore[misc]

    def test_signal_edge_check(self) -> None:
        s = Signal(
            check="edge",
            signal_id="edge:inline",
            description="inline",
            evidence="x",
        )
        assert s.check == "edge"
