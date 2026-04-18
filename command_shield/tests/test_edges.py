"""Tests for extract_edges — the containment-edge extractor."""

from __future__ import annotations

import pytest

from command_shield.edges import extract_edges


class TestEdgeInline:
    """`python -c "..."`, `bash --eval '...'` — body is in-band."""

    def test_python_c_inline(self) -> None:
        edges = extract_edges('python -c "print(1)"')
        assert len(edges) == 1
        e = edges[0]
        assert e.kind == "inline"
        assert e.language == "python"
        assert e.body == "print(1)"
        assert e.resolvable is True

    def test_bash_c_inline(self) -> None:
        edges = extract_edges('bash -c "rm -rf /tmp/x"')
        assert len(edges) == 1
        assert edges[0].kind == "inline"
        assert edges[0].language == "shell"

    def test_node_eval_inline(self) -> None:
        edges = extract_edges('node --eval "console.log(1)"')
        assert len(edges) == 1
        assert edges[0].kind == "inline"
        assert edges[0].language == "javascript"


class TestEdgeReferenced:
    """`python foo.py` — body is at a literal file path."""

    def test_python_script(self) -> None:
        edges = extract_edges("python foo.py")
        assert len(edges) == 1
        e = edges[0]
        assert e.kind == "referenced"
        assert e.path_arg == "foo.py"
        assert e.resolvable is True

    def test_script_with_flags_before(self) -> None:
        edges = extract_edges("python -u -B foo.py")
        assert len(edges) == 1
        assert edges[0].path_arg == "foo.py"

    def test_source_verb(self) -> None:
        edges = extract_edges("source .env")
        assert len(edges) == 1
        assert edges[0].kind == "referenced"
        assert edges[0].language == "shell"
        assert edges[0].sub_kind == "source"

    def test_dot_source_verb(self) -> None:
        edges = extract_edges(". /etc/profile")
        assert len(edges) == 1
        assert edges[0].kind == "referenced"
        assert edges[0].sub_kind == "source"

    def test_absolute_path_interpreter(self) -> None:
        edges = extract_edges("/usr/bin/python3 /opt/foo.py")
        assert len(edges) == 1
        assert edges[0].kind == "referenced"
        assert edges[0].language == "python"


class TestEdgeDynamic:
    """Non-literal script paths — shell resolves at exec time."""

    @pytest.mark.parametrize("cmd, reason", [
        ("python $SCRIPT", "variable-expansion"),
        ("python ${SCRIPT}", "variable-expansion"),
        ("python $(gen)", "command-substitution"),
        ("python `gen`", "backtick-substitution"),
        ("python <(gen)", "process-substitution"),
        ("python *.py", "glob"),
        ("python ?.py", "glob"),
        ("python [abc].py", "glob"),
    ])
    def test_dynamic_markers(self, cmd: str, reason: str) -> None:
        edges = extract_edges(cmd)
        assert len(edges) == 1
        assert edges[0].kind == "dynamic"
        assert edges[0].unresolvable_reason == reason
        assert edges[0].resolvable is False


class TestEdgeInteractive:
    """REPL / stdin forms — no resolvable body."""

    def test_bare_interpreter(self) -> None:
        edges = extract_edges("python")
        assert len(edges) == 1
        assert edges[0].kind == "interactive"
        assert edges[0].unresolvable_reason == "no-body"

    def test_module_invocation(self) -> None:
        edges = extract_edges("python -m http.server")
        assert len(edges) == 1
        assert edges[0].kind == "interactive"

    def test_dash_stdin_marker(self) -> None:
        edges = extract_edges("python -")
        assert len(edges) == 1
        assert edges[0].kind == "interactive"
        assert edges[0].unresolvable_reason == "stdin-marker"


class TestEdgePipedStdin:
    """`cat foo.py | python -` — body streams from a producer."""

    def test_pipe_to_python(self) -> None:
        edges = extract_edges("cat foo.py | python -")
        kinds = [e.kind for e in edges]
        assert "piped_stdin" in kinds
        piped = [e for e in edges if e.kind == "piped_stdin"][0]
        assert piped.resolvable is False
        assert piped.language == "python"

    def test_pipe_to_bash_no_dash(self) -> None:
        edges = extract_edges("echo hello | bash")
        kinds = [e.kind for e in edges]
        assert "piped_stdin" in kinds


class TestEdgeDepthAndNesting:
    """Indirection payloads are walked up to max_depth."""

    def test_depth_zero_only_by_default(self) -> None:
        edges = extract_edges("python foo.py")
        assert all(e.depth == 0 for e in edges)

    def test_indirection_walked_at_depth_one(self) -> None:
        edges = extract_edges(
            'bash -c "python foo.py"',
            indirections=("python foo.py",),
            max_depth=2,
        )
        depths = {e.depth for e in edges}
        assert 0 in depths
        assert 1 in depths

    def test_depth_bound_respected(self) -> None:
        edges = extract_edges(
            'bash -c "python foo.py"',
            indirections=("python foo.py",),
            max_depth=0,
        )
        assert all(e.depth == 0 for e in edges)


class TestEdgeRobustness:
    """Edge extractor must never raise."""

    def test_empty_command(self) -> None:
        assert extract_edges("") == ()
        assert extract_edges("   ") == ()

    def test_unclosed_quotes(self) -> None:
        edges = extract_edges('python "foo.py')
        assert isinstance(edges, tuple)

    def test_non_interpreter_command(self) -> None:
        assert extract_edges("ls -la") == ()
        assert extract_edges("git status") == ()
