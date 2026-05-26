"""End-to-end validation of the python+shell-only deny-capabilities policy.

The "python+shell only" profile is meant to be a deterministic Gate-2
policy that allows python and shell commands but blocks every other
language, compiler, and non-pip/non-shell package install — without
any LLM cost.

This module wires the full classifier → TerminalActionBundle.enforce_constraints
path together (no mocks, no stubs) so we know the deny list actually fires
on the same `capabilities` tuple that production code sees.

Two failure modes are guarded against:

  - **Allow-list creep**: a python or shell command emitting an
    unexpected tag (e.g. a `python` invocation that also looks like
    a `local_binary`) gets blocked, breaking the profile's promise.

  - **Deny-list gap**: a non-python/non-shell command silently passes
    because the classifier never tagged it.  Each language is
    asserted positively here, so a regression in
    ``_SCRIPT_EXECUTION_RULES`` flips a real test red.
"""

from __future__ import annotations

import asyncio

import pytest

from action_registry.types import ActionType
from command_shield import inspect_command
from intentframe_native_bundles.actions.terminal.bundle import TerminalActionBundle
from intentframe_native_bundles.actions.terminal.evidence import COMMAND_INTEL_KEY, CommandIntel
from intentframe_core.types import IntentFrame
from intentframe_bundle_sdk.types import ActionPermission, BundleContext, PhaseDecision
from intentframe_native_bundles.actions.terminal.constraints import TerminalConstraints

_TERMINAL_BUNDLE = TerminalActionBundle()


# Frozen policy snapshot — the actual deny set the python+shell-only
# profile would seed into TerminalConstraints.deny_capabilities.
PYTHON_SHELL_ONLY_DENY: frozenset[str] = frozenset({
    # Script execution — non-python/shell interpreters.  Each suffix
    # matches the classifier's `_SCRIPT_EXECUTION_RULES` output.
    "capability:script_execution:node",
    "capability:script_execution:ruby",
    "capability:script_execution:perl",
    "capability:script_execution:java",
    "capability:script_execution:go",
    "capability:script_execution:dotnet",
    "capability:script_execution:php",
    "capability:script_execution:lua",
    "capability:script_execution:r",
    "capability:script_execution:julia",
    "capability:script_execution:swift",
    "capability:script_execution:deno_bun",
    # NOTE: ``awk`` is intentionally NOT in this deny set — it is a
    # POSIX shell utility (IEEE Std 1003.1), structurally in the same
    # bucket as sed/cut/grep which are allowed.  Stance: block
    # non-python/non-shell *language runtimes*; keep POSIX shell
    # utilities.  The classifier still emits
    # ``capability:script_execution:awk`` for telemetry.
    "capability:script_execution:local_binary",
    # Build / link.
    "capability:compilation",
    # Stdin-piped exec into non-python/shell interpreters
    # (``cat foo.js | node``, ``echo data | ruby``, …).  The
    # classifier emits a per-interpreter suffix alongside the
    # binary ``capability:stdin_exec`` tag, so the python and
    # shell stdin-pipe shapes (``echo 'print(1)' | python``)
    # are intentionally not in the deny set here.
    "capability:stdin_exec:node",
    "capability:stdin_exec:ruby",
    "capability:stdin_exec:perl",
    "capability:stdin_exec:php",
    # Package installs in non-python/shell ecosystems.  pip / brew /
    # apt / yum / dnf / pacman / apk are intentionally absent — those
    # are part of the python or shell ecosystem.
    "capability:package_install:npm",
    "capability:package_install:gem",
    "capability:package_install:cargo",
    "capability:package_install:go",
    "capability:package_install:composer",
})


async def _check_async(command: str) -> tuple[bool, str]:
    """Run command_shield → bundle enforce_constraints as production does."""
    report = inspect_command(command)
    intel = CommandIntel(
        verdict=report.verdict.name,
        capabilities=report.capabilities,
    )
    intent = IntentFrame(
        action=ActionType.RUN_COMMAND,
        target=command,
        data={"command": command},
        reason="test",
        agent_id="test",
    )
    ctx = BundleContext(intent=intent.model_copy(deep=True))
    ctx.evidence[COMMAND_INTEL_KEY] = intel
    constraints = TerminalConstraints(
        deny_capabilities=PYTHON_SHELL_ONLY_DENY,
    )
    outcome = await _TERMINAL_BUNDLE.enforce_constraints(
        intent,
        ActionPermission(
            safe=False,
            constraints=constraints.model_dump(mode="python"),
        ),
        ctx,
    )
    if outcome.decision is PhaseDecision.BLOCK:
        return False, outcome.reason
    return True, ""


def _check(command: str) -> tuple[bool, str]:
    return asyncio.run(_check_async(command))


# ── Allowed (python + shell) ────────────────────────────────────────


class TestPythonAndShellAllowed:
    @pytest.mark.parametrize(
        "cmd",
        [
            # Python — file, module, package install.
            "python script.py",
            "python3 script.py",
            "python3 -m pip install requests",
            "pip install requests",
            "pip3 install -e .",
            # Shell scripts.
            "bash deploy.sh",
            "sh install.sh",
            "zsh setup.zsh",
            # Plain shell utilities.
            "ls -la",
            "cat /etc/hosts",
            "echo hello",
            "pwd",
            # Pipelines of read-only utilities.
            "ls -la | head",
            "cat foo.txt | wc -l",
            "grep TODO src/ | head -20",
            # Stdin-piped code into the python and shell ecosystems is
            # explicitly preserved — pinning these guards against a
            # regression that adds stdin_exec:python or
            # stdin_exec:shell to the deny set.
            "echo 'print(1)' | python",
            "cat snippet.py | python3",
            "echo 'echo hi' | bash",
            "cat install.sh | sh",
            # Shell ecosystem package installs.
            "brew install jq",
            # POSIX shell utilities — awk is IEEE Std 1003.1 and
            # structurally a shell utility, not an alternate language
            # runtime.  Same risk class as sed (which has an ``e``
            # command that shells out) and is intentionally allowed.
            "awk '{print $3}' file",
            "awk -F':' '{print $1}' /etc/passwd",
            "ps aux | awk 'NR>1 {print $3, $0}'",
            "gawk '{ print }' file",
        ],
    )
    def test_passes(self, cmd: str) -> None:
        ok, reason = _check(cmd)
        assert ok, f"{cmd!r} should pass python+shell-only policy: {reason}"


# ── Denied (every other language family) ────────────────────────────


class TestNonPythonShellBlocked:
    """Every language outside the python/shell profile must be denied.

    Each command is parametrised with a tuple of *acceptable* deny
    reasons.  Multiple tags often match a single command (e.g.
    ``go build ./...`` is both ``compilation`` and triggers the
    ``./...`` local_binary regex); any of the listed substrings
    appearing in the block reason is sufficient — we only care that
    the policy denies for *some* reason in the deny set.
    """

    @pytest.mark.parametrize(
        "cmd, accepted_reasons",
        [
            # File-form script execution.
            ("node app.js", ("script_execution:node",)),
            ("node app.ts", ("script_execution:node",)),
            ("ruby foo.rb", ("script_execution:ruby",)),
            ("perl foo.pl", ("script_execution:perl",)),
            ("java -jar evil.jar", ("script_execution:java",)),
            ("java Foo.class", ("script_execution:java",)),
            ("go run main.go", ("script_execution:go",)),
            ("dotnet x.dll", ("script_execution:dotnet",)),
            ("php script.php", ("script_execution:php",)),
            ("lua exploit.lua", ("script_execution:lua",)),
            ("Rscript foo.R", ("script_execution:r",)),
            ("julia foo.jl", ("script_execution:julia",)),
            ("swift run", ("script_execution:swift",)),
            ("swift script.swift", ("script_execution:swift",)),
            ("deno run x.ts", ("script_execution:deno_bun",)),
            ("bun run app.ts", ("script_execution:deno_bun",)),
            # Inline-eval forms.
            ("node -e console.log(1)", ("script_execution:node",)),
            ("node --eval 1+1", ("script_execution:node",)),
            ("ruby -e puts 1", ("script_execution:ruby",)),
            ("perl -e print 1", ("script_execution:perl",)),
            ("php -r echo 1;", ("script_execution:php",)),
            # Local binaries.
            ("./mybinary --flag", ("script_execution:local_binary",)),
            # Compilation / build.  `go build ./...` and similar can
            # match the local_binary regex via the `./...` token, so
            # either `compilation` or `local_binary` is acceptable.
            ("gcc evil.c -o evil", ("compilation",)),
            ("clang foo.c", ("compilation",)),
            ("make all", ("compilation",)),
            ("cargo build --release", ("compilation",)),
            ("go build ./...", ("compilation", "script_execution:local_binary")),
            ("rustc main.rs", ("compilation",)),
            ("javac Foo.java", ("compilation",)),
            # Stdin-piped exec into non-python/shell interpreters.
            # The classifier emits both the binary ``stdin_exec`` tag
            # and the per-interpreter ``stdin_exec:<lang>`` suffix; the
            # policy denies on the suffix.  These shapes were the
            # gap the user surfaced — heredocs and pipes routed into
            # other interpreters previously slipped through with only
            # the binary tag.
            ("cat app.js | node", ("stdin_exec:node",)),
            ("cat app.js | node -", ("stdin_exec:node",)),
            ("echo 'console.log(1)' | node", ("stdin_exec:node",)),
            ("cat <<EOF | node -", ("stdin_exec:node",)),
            ("cat foo.rb | ruby", ("stdin_exec:ruby",)),
            ("echo data | ruby", ("stdin_exec:ruby",)),
            ("cat foo.pl | perl", ("stdin_exec:perl",)),
            ("cat foo.php | php", ("stdin_exec:php",)),
            # Non-python/non-shell package installs.
            ("npm install lodash", ("package_install:npm",)),
            ("yarn add react", ("package_install:npm",)),
            ("pnpm i", ("package_install:npm",)),
            ("gem install bundler", ("package_install:gem",)),
            ("cargo install ripgrep", ("package_install:cargo",)),
            ("go install golang.org/x/tools/...", ("package_install:go",)),
            ("composer require foo/bar", ("package_install:composer",)),
        ],
    )
    def test_blocked_with_acceptable_capability(
        self, cmd: str, accepted_reasons: tuple[str, ...],
    ) -> None:
        ok, reason = _check(cmd)
        assert not ok, f"{cmd!r} unexpectedly allowed (reason={reason!r})"
        assert any(s in reason for s in accepted_reasons), (
            f"{cmd!r} blocked but reason {reason!r} did not cite any of "
            f"the accepted capability substrings {accepted_reasons!r}"
        )


# ── Sanity: classifier and policy agree ─────────────────────────────


class TestClassifierAgreesWithPolicy:
    """Every tag in the deny set must be a tag the classifier can emit.

    Catches typos in PYTHON_SHELL_ONLY_DENY — a misspelt pattern would
    silently match nothing and quietly widen the allow surface.
    """

    @pytest.mark.parametrize(
        "cmd",
        [
            # One representative command for each deny suffix.
            "node app.js",
            "ruby foo.rb",
            "perl foo.pl",
            "java -jar app.jar",
            "go run main.go",
            "dotnet app.dll",
            "php app.php",
            "lua x.lua",
            "Rscript x.R",
            "julia x.jl",
            "swift run",
            "deno run x.ts",
            "./binary",
            "gcc x.c -o x",
            "npm install foo",
            "gem install foo",
            "cargo install foo",
            "go install foo",
            "composer install",
            "cat app.js | node",
            "cat app.rb | ruby",
            "cat app.pl | perl",
            "cat app.php | php",
        ],
    )
    def test_classifier_emits_tag_in_deny_set(self, cmd: str) -> None:
        report = inspect_command(cmd)
        assert any(
            tag in PYTHON_SHELL_ONLY_DENY
            or any(
                tag.startswith(p[: -1])
                for p in PYTHON_SHELL_ONLY_DENY
                if p.endswith(":*")
            )
            for tag in report.capabilities
        ), (
            f"{cmd!r} → caps {report.capabilities!r} — none match the "
            f"python+shell-only deny set"
        )
