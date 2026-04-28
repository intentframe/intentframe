"""Shared runner for root-demo intent test suites.

Each per-category test file (``test_normal.py``, ``test_general.py``,
``test_attacks.py``, ...) defines its ``INTENTS`` dict, ``CATEGORY``
string, and a ``SUITE_TITLE``, then calls ``RootIntentSuite(...).main()``.
All execution, evaluation, printing, and verdict logic lives here so test
files stay minimal — just data + one entry call.

Verdict semantics (sourced purely from ``ExecutionResult``, no audit-log
peek):

  - ``expected_decision == "ALLOW"`` PASSes when every submission's
    Guardian decision is ALLOW *and* every submission has ``success=True``.
  - ``expected_decision == "BLOCK"`` PASSes when at least one submission's
    Guardian decision is BLOCK (the agent then sees ``success=False``,
    which is also the expected shape).

Decision is derived from ``result.data["decision"]``: pipeline.py BLOCK
paths populate ``data["decision"] == "BLOCK"`` with ``reason`` / ``layer``
/ optional ``matched_gate``.  Anything else is treated as ALLOW (success
or adapter-side failure with adapter data).

Execution modes (safety-critical):

  - DRY-RUN (recommended default for local dev): supervisor is started
    with ``INTENTFRAME_EXECUTOR_MODE=dry_run`` and optionally
    ``INTENTFRAME_DRY_RUN_CONTEXT=root`` so Guardian sees a root
    privilege posture.  The runner auto-detects dry-run from the
    preflight response's ``data["dry_run"] == True`` and refuses to
    continue if ALLOW results ever come back without that flag — a
    defense-in-depth check against a misconfigured supervisor
    silently shelling commands out on the host.
  - REAL: supervisor is started with the root executor profile
    (``intentframe-gateway-cli --profile root`` or the direct
    ``supervisor.main`` dev loop).  Preflight requires ``whoami``
    to return ``root``; ALLOW fixtures actually run on the host.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

_project_root = Path(__file__).resolve().parents[3]
_tests_dir = Path(__file__).resolve().parents[1]
_root_demo_dir = Path(__file__).resolve().parent
for p in (_project_root, _tests_dir, _root_demo_dir):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from typing import Any, Dict, List, Tuple

from policy_registry.client import PolicyRegistryClient
from resource_registry.client import ResourceRegistryClient
from intentframe_server.client import IntentFrameClient

from root_intent_pipeline import (
    DEFAULT_INTENTFRAME_SOCKET,
    ROOT_USER_ID,
    ensure_root_user_policy,
    register_root_workspace,
)
from root_stub_agent import StubPipelineRootAgent, load_root_intents


_OUTPUT_CAP_CHARS = 600  # Modest cap: full output for short commands
                         # (ls, pfctl, tee), useful first chunk for verbose
                         # ones (dmesg, lsof, ps).


def _print_executor_alert() -> None:
    """Print startup banner.

    If the shell env hints at dry-run we advertise the dry-run launch
    recipe; otherwise we advertise the real-execution recipe.  The
    actual mode is confirmed against the server's preflight response,
    so this banner is purely informational.
    """
    mode_hint = os.environ.get("INTENTFRAME_EXECUTOR_MODE", "").strip().lower()
    print()
    print("#" * 79)
    if mode_hint == "dry_run":
        print("#  MODE HINT: DRY-RUN (shell env INTENTFRAME_EXECUTOR_MODE=dry_run)")
        print("#")
        print("#  Supervisor must have been started with:")
        print("#    INTENTFRAME_EXECUTOR_MODE=dry_run \\")
        print("#    INTENTFRAME_DRY_RUN_CONTEXT=root \\")
        print("#    python -m supervisor.main start")
        print("#")
        print("#  ALLOW results must carry data['dry_run']=True or the runner will")
        print("#  fail closed — it will NOT let real commands pretend to be dry-run.")
    else:
        print("#  ALERT: SUPERVISOR MUST BE RUNNING WITH THE ROOT EXECUTOR PROFILE")
        print("#")
        print("#  ONE-TIME SETUP:")
        print("#    sudo bash intentframe_setup_root_demo.sh")
        print("#")
        print("#  REQUIRED (CHOOSE ONE):")
        print("#    intentframe-gateway-cli --profile root")
        print("#")
        print("#  OR (DEV LOOP, BYPASSES GATEWAY):")
        print("#    INTENTFRAME_PROFILE=root \\")
        print("#    EXECUTOR_CONFIG=jarvis_pa/executor_root.yaml \\")
        print("#    INTENTFRAME_ESCALATION_ARMED=1 \\")
        print("#    python -m supervisor.main start")
        print("#")
        print("#  SAFER ALTERNATIVE — DRY-RUN (no host I/O):")
        print("#    INTENTFRAME_EXECUTOR_MODE=dry_run \\")
        print("#    INTENTFRAME_DRY_RUN_CONTEXT=root \\")
        print("#    python -m supervisor.main start")
        print("#")
        print("#  WRONG CONFIG -> ROOT-ONLY COMMANDS FAIL WITH \"PERMISSION DENIED\"")
    print("#" * 79)


def _result_decision(r: Dict[str, Any]) -> str:
    """Derive Guardian's decision from a single ExecutionResult-shaped dict."""
    data = r.get("data")
    if isinstance(data, dict) and data.get("decision") == "BLOCK":
        return "BLOCK"
    return "ALLOW"


def _result_is_dry_run(r: Dict[str, Any]) -> bool:
    """Return True iff this ExecutionResult-shaped dict was produced by DryRunExecutor."""
    data = r.get("data")
    return isinstance(data, dict) and data.get("dry_run") is True


def _print_adapter_output(data: Dict[str, Any]) -> None:
    """Render the adapter's output as a left-bar block, capped to a modest size."""
    if not data:
        return
    output = data.get("content") or data.get("stdout") or ""
    if not output:
        return
    output = str(output)
    full_len = len(output)
    truncated = full_len > _OUTPUT_CAP_CHARS
    body = output[:_OUTPUT_CAP_CHARS]

    print(f"        ┌─ Adapter Output {'─' * 56}")
    for line in body.splitlines() or [body]:
        print(f"        │ {line}")
    if truncated:
        print(
            f"        └─ truncated at {_OUTPUT_CAP_CHARS} chars "
            f"(full={full_len:,} chars)"
        )
    else:
        print(f"        └─ ({full_len:,} chars)")


class RootIntentSuite:
    """Per-category root-demo runner.

    Owns ``intents``, ``category``, and ``suite_title`` for one run; all
    intent-aware printers/evaluators read from ``self`` so test files only
    declare their data and call ``main()``.
    """

    def __init__(
        self,
        category: str,
        intents: Dict[int, Dict[str, Any]],
        suite_title: str,
    ) -> None:
        self.category = category
        self.intents = intents
        self.suite_title = suite_title
        # Set by the preflight from the server's actual response so
        # evaluation never trusts the client's env alone.  ``True`` only
        # when the executor returned ``data["dry_run"] is True``.
        self._dry_run_mode: bool = False

    # ── Public entry point ───────────────────────────────────────────

    def main(self) -> None:
        invalid_args = [a for a in sys.argv[1:] if not a.isdigit()]
        if invalid_args:
            print(f"Invalid intent argument(s): {invalid_args}")
            sys.exit(2)

        intent_nums = [int(a) for a in sys.argv[1:]]
        if not intent_nums:
            intent_nums = list(self.intents.keys())

        unknown = [n for n in intent_nums if n not in self.intents]
        if unknown:
            print(f"Unknown intent number(s): {unknown}")
            sys.exit(2)

        _print_executor_alert()

        print("\n" + "=" * 79)
        print(f"  {self.suite_title}")
        print("=" * 79)
        print(f"  Running intents: {intent_nums} (single Actor session)")
        print("=" * 79)

        passed = asyncio.run(self._run(intent_nums))
        if not passed:
            sys.exit(1)

    # ── Per-intent header / verdict ──────────────────────────────────

    def _print_intent_header(self, intent_num: int) -> None:
        meta = self.intents[intent_num]
        print("\n" + "=" * 79)
        print(f"  {self.category.upper()} {intent_num}: {meta['name']}")
        print("=" * 79)
        print(f"  Action:   {meta['action']}")
        print(f"  Target:   {meta['target']}")
        print(f"  Expected: {meta['expected_decision']}")
        print(f"  User:     {ROOT_USER_ID}")
        print("=" * 79)

    def _evaluate(self, entry: Dict[str, Any]) -> Tuple[bool, str, str]:
        n = entry["intent_num"]
        expected = self.intents[n]["expected_decision"]
        decisions = [_result_decision(r) for r in entry["results"]]
        actual = "BLOCK" if "BLOCK" in decisions else "ALLOW"
        successes = sum(1 for r in entry["results"] if r["success"])
        total = entry["submits"]
        if expected == "ALLOW":
            passed = actual == "ALLOW" and successes == total
        else:  # BLOCK
            passed = actual == "BLOCK"

        # Dry-run safety contract: once preflight identified the server
        # as dry-run, every subsequent ALLOW result MUST also be tagged
        # ``dry_run=True``.  If the server silently switched back to a
        # real executor mid-run we fail closed rather than let a
        # "passing" green result mask real host execution.
        suffix = ""
        if self._dry_run_mode:
            untagged = [
                i for i, r in enumerate(entry["results"])
                if _result_decision(r) == "ALLOW" and not _result_is_dry_run(r)
            ]
            if untagged:
                passed = False
                suffix = (
                    f"  [SAFETY] ALLOW result(s) {untagged} missing dry_run flag — "
                    "refusing to treat real execution as dry-run"
                )

        icon = "✅" if passed else "❌"
        label = "PASS" if passed else "FAIL"
        return (
            passed,
            actual,
            f"{icon} {label}  expected={expected}  actual={actual}{suffix}",
        )

    def _print_intent_verdict(self, entry: Dict[str, Any]) -> None:
        n = entry["intent_num"]
        _, actual, status = self._evaluate(entry)
        print(f"    [{n}] {status}")

        last = entry["results"][-1]
        data = last.get("data") if isinstance(last.get("data"), dict) else {}
        if actual == "BLOCK":
            meta = []
            if data.get("layer"):
                meta.append(f"layer={data['layer']}")
            if data.get("matched_gate"):
                meta.append(f"gate={data['matched_gate']}")
            if meta:
                print(f"        {'  '.join(meta)}")
            if data.get("reason"):
                print(f"        Reason: {str(data['reason'])[:120]}")
        else:  # ALLOW
            if last.get("success"):
                _print_adapter_output(data)
            else:
                err = (last.get("error") or "")[:120]
                print(f"        Adapter error: {err}")

    # ── Action grouping ──────────────────────────────────────────────

    def _group_by_action(self, intent_nums: List[int]) -> List[Tuple[str, List[int]]]:
        groups: Dict[str, List[int]] = {}
        for n in intent_nums:
            action = self.intents[n]["action"]
            groups.setdefault(action, []).append(n)
        return list(groups.items())

    @staticmethod
    def _print_group_banner(action: str, nums: List[int]) -> None:
        print()
        print("#" * 79)
        print(f"#  ACTION GROUP: {action}   —   intents {nums}")
        print("#" * 79)

    async def _run_root_preflight(
        self,
        agent: StubPipelineRootAgent,
        server_client: IntentFrameClient,
    ) -> bool:
        """Probe the server with ``whoami`` and classify the execution mode.

        Two healthy outcomes:

          * ``data["dry_run"] is True``  → dry-run mode; we set
            ``self._dry_run_mode = True`` and skip the real root check.
            Evaluation will later enforce that *every* ALLOW result
            also carries ``dry_run=True`` (defense-in-depth against a
            misconfigured supervisor silently running commands).
          * ``stdout == "root"``         → real mode; proceed.

        Anything else fails the run.
        """
        print()
        print("#" * 79)
        print("#  PREFLIGHT: VERIFY RUN_COMMAND ESCALATION")
        print("#" * 79)
        server_client.clear_audit_log()
        result = await agent.submit(
            {
                "action": "RUN_COMMAND",
                "data": {"command": "whoami"},
                "reason": (
                    "Preflight check: verify root-demo RUN_COMMAND execution "
                    "is actually running as UID 0 before evaluating fixtures "
                    "(or confirm dry-run mode and skip host execution)."
                ),
            }
        )

        data = result.data if isinstance(result.data, dict) else {}
        output = str(data.get("content") or data.get("stdout") or "").strip()

        # Dry-run branch: the server is talking to DryRunExecutor.  We
        # trust the server's ``dry_run`` flag rather than the client's
        # env because only the server actually knows which executor is
        # wired into its runtime.
        if result.success and data.get("dry_run") is True:
            self._dry_run_mode = True
            print("    ✅ PASS  dry-run executor active (data['dry_run']=True)")
            print(f"        synthetic output: {output!r}")
            print("        NOTE: no commands will actually execute on the host.")
            return True

        # Real-execution branch: require uid=0 observable via whoami.
        if result.success and output == "root":
            self._dry_run_mode = False
            print("    ✅ PASS  whoami returned 'root' (real executor, running as root)")
            return True

        print("    ❌ FAIL  root-demo preflight did not confirm a supported mode")
        if output:
            print(f"        whoami output: {output!r}")
        if result.error:
            print(f"        error: {result.error}")
        print("        Start the supervisor with either:")
        print("          • the root executor profile (real execution), OR")
        print("          • INTENTFRAME_EXECUTOR_MODE=dry_run INTENTFRAME_DRY_RUN_CONTEXT=root")
        return False

    # ── Summary ──────────────────────────────────────────────────────

    def _print_summary(self, per_intent: List[Dict[str, Any]]) -> None:
        mode_tag = "DRY-RUN" if self._dry_run_mode else "REAL"
        print("\n")
        print("=" * 79)
        print(
            f"  {self.category.upper()} INTENT TEST SUMMARY "
            f"[mode={mode_tag}] "
            "(expected_decision vs actual from ExecutionResult)"
        )
        print("=" * 79)

        grouped = self._group_by_action([e["intent_num"] for e in per_intent])
        by_num = {e["intent_num"]: e for e in per_intent}

        for action, nums in grouped:
            print(f"\n  --- {action} ---")
            for n in nums:
                entry = by_num[n]
                name = self.intents.get(n, {}).get("name", "Unknown")
                _, actual, status = self._evaluate(entry)
                print(f"  [{n}] {name:<42} {status}")
                last = entry["results"][-1]
                data = last.get("data") if isinstance(last.get("data"), dict) else {}
                if actual == "BLOCK" and data.get("reason"):
                    print(f"      └─ {str(data['reason'])[:70]}")
        print("=" * 79)

    # ── Async run loop ───────────────────────────────────────────────

    async def _run(self, intent_nums: List[int]) -> bool:
        policy_client = PolicyRegistryClient()
        resource_client = ResourceRegistryClient()
        server_client = IntentFrameClient(socket_path=DEFAULT_INTENTFRAME_SOCKET)

        try:
            ensure_root_user_policy(policy_client)
            register_root_workspace(resource_client)

            agent = StubPipelineRootAgent()
            await agent.open(ROOT_USER_ID, DEFAULT_INTENTFRAME_SOCKET)
            try:
                if not await self._run_root_preflight(agent, server_client):
                    return False

                t0 = time.monotonic()
                per_intent: List[Dict[str, Any]] = []
                all_passed = True
                for action, nums in self._group_by_action(intent_nums):
                    self._print_group_banner(action, nums)
                    for n in nums:
                        self._print_intent_header(n)
                        server_client.clear_audit_log()

                        submissions = load_root_intents(self.category, n)
                        results = [await agent.submit(req) for req in submissions]

                        entry: Dict[str, Any] = {
                            "intent_num": n,
                            "submits": len(submissions),
                            "results": [
                                {
                                    "success": r.success,
                                    "error": (r.error or "")[:300],
                                    "data": r.data,
                                }
                                for r in results
                            ],
                        }
                        per_intent.append(entry)
                        passed, _, _ = self._evaluate(entry)
                        all_passed = all_passed and passed
                        self._print_intent_verdict(entry)
                duration = time.monotonic() - t0
            finally:
                await agent.close()

            self._print_summary(per_intent)
            print(f"\n  Session duration: {duration:.2f}s")
            return all_passed
        finally:
            policy_client.close()
            resource_client.close()
            server_client.close()
