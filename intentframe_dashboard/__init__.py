"""
IntentFrame Dashboard — The product entry point.

The Dashboard is the user-facing control plane for IntentFrame.
It manages the full lifecycle: scan agent packages, register users,
configure workspaces, launch agent programs, and retrieve audit trails.

The dashboard never imports or executes agent code directly.
It launches programs as subprocesses with the right environment;
agents are responsible for connecting to IntentFrame via Actor SDK.

Requires the IntentFrame services to be running (via supervisor).

Usage (programmatic):
    from intentframe_dashboard import IntentFrameDashboard

    with IntentFrameDashboard(agent_dir="external_agents") as dashboard:
        dashboard.register_user("finance_001", ...)
        dashboard.register_workspace("invoice_processing", ...)
        dashboard.install("invoice_bot")
        result = dashboard.run("Process invoices", agent="invoice_bot", ...)

Usage (config-driven):
    from intentframe_dashboard import run_config

    run_config(config="demo/config/dashboard.yaml", agent_dir="external_agents")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from policy_registry.client import PolicyRegistryClient
from policy_registry.models import ActionPermission, SemanticIntentLimit, UserPolicy
from intentframe_native_kit.resource_registry.client import ResourceRegistryClient
from intentframe_native_kit.resource_registry.models import ResourceMount

from intentframe_server.client import IntentFrameClient

from intentframe_dashboard.manifest import AgentManifest
from intentframe_dashboard.loader import scan_agents
from intentframe_dashboard.runner import Runner, RunResult
from intentframe_dashboard.venv_manager import VenvManager
from intentframe_dashboard.config import (
    DashboardConfig,
    load_config,
)
INTENTFRAME_SOCKET = "~/.intentframe/run/intentframe.sock"


class IntentFrameDashboard:
    """
    Central control plane for IntentFrame.

    Connects to the running IntentFrame services and provides a clean API
    for agent installation (from packages), user registration, workspace
    setup, and program execution.
    """

    def __init__(
        self,
        agent_dir: str | Path | None = None,
        socket_path: str = INTENTFRAME_SOCKET,
    ) -> None:
        self._policy_client = PolicyRegistryClient()
        self._resource_client = ResourceRegistryClient()
        self._server_client = IntentFrameClient()
        self._venv_manager = VenvManager()
        self._runner = Runner()
        self._socket_path = socket_path

        self._manifests: Dict[str, AgentManifest] = {}
        self._installed: Dict[str, AgentManifest] = {}
        self._users: Dict[tuple[str, str], UserPolicy] = {}

        self._agent_dir: Path | None = None
        if agent_dir is not None:
            self._agent_dir = Path(agent_dir)
            self._manifests = scan_agents(self._agent_dir)

    # ── Context manager ──────────────────────────────────────────────

    def __enter__(self) -> "IntentFrameDashboard":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        self._policy_client.close()
        self._resource_client.close()
        self._server_client.close()

    # ── User & Policy Management ─────────────────────────────────────

    def register_user(
        self,
        user_id: str,
        agent_id: str,
        allowed_actions: Dict[str, ActionPermission],
        intent_limits: List[SemanticIntentLimit] | None = None,
        domain_constraints: Dict[str, dict] | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> UserPolicy:
        """Register a (user, agent) policy with the registry.

        ``agent_id`` is required because the policy registry keys on the
        ``(user_id, agent_id)`` pair — one operator can run multiple
        agents with isolated policies.  The dashboard's local cache uses
        the same composite key.
        """
        policy = UserPolicy(
            user_id=user_id,
            agent_id=agent_id,
            allowed_actions=allowed_actions,
            intent_limits=intent_limits or [],
            domain_constraints=domain_constraints or {},
            metadata=metadata or {},
        )
        self._policy_client.set_user_policy(policy)
        stored = self._policy_client.get_user_policy(user_id, agent_id)
        self._users[(user_id, agent_id)] = stored
        return stored

    def get_user(self, user_id: str, agent_id: str) -> UserPolicy:
        key = (user_id, agent_id)
        if key in self._users:
            return self._users[key]
        return self._policy_client.get_user_policy(user_id, agent_id)

    # ── Workspace Management ─────────────────────────────────────────

    def register_workspace(
        self,
        workspace_id: str,
        mounts: List[ResourceMount],
        base_path: Path | str,
    ) -> None:
        """Register a workspace with file/resource mounts."""
        try:
            self._resource_client.create_workspace(
                workspace_id=workspace_id,
                mounts=mounts,
                base_path=Path(base_path),
            )
        except ValueError:
            pass  # workspace already exists

    # ── Agent Package Management ─────────────────────────────────────

    def install(self, name: str) -> AgentManifest:
        """Install an agent from its package in the agent directory.

        Creates an isolated virtual environment for the agent, installs
        the IntentFrame SDK and any dependencies declared in the manifest.
        """
        if self._agent_dir is None:
            raise RuntimeError("No agent_dir configured")
        if name not in self._manifests:
            raise KeyError(
                f"Agent '{name}' not found. "
                f"Available: {list(self._manifests.keys())}"
            )

        manifest = self._manifests[name]
        self._venv_manager.create(manifest)
        self._installed[name] = manifest
        return manifest

    def list_available(self) -> Dict[str, AgentManifest]:
        """Return manifests of all discovered (but not necessarily installed) agents."""
        return dict(self._manifests)

    def list_installed(self) -> List[str]:
        return list(self._installed.keys())

    # ── Run ───────────────────────────────────────────────────────────

    def run(
        self,
        task: str,
        *,
        agent: str,
        user_id: str,
        workspace_id: str,
        timeout: float = 120.0,
    ) -> RunResult:
        """
        Launch an installed agent program to handle a task.

        The dashboard builds environment variables and hands off to the
        Runner, which launches the program as a subprocess.  The program
        is responsible for importing Actor SDK and connecting to IntentFrame.

        Args:
            task:         Natural-language task description.
            agent:        Name of an installed agent package.
            user_id:      User whose policies govern this run.
            workspace_id: Workspace that defines accessible resources.
            timeout:      Max seconds before the process is killed.
        """
        if agent not in self._installed:
            raise KeyError(
                f"Agent '{agent}' is not installed. "
                f"Installed: {list(self._installed.keys())}"
            )

        manifest = self._installed[agent]
        package_dir = self._agent_dir / manifest.name  # type: ignore[operator]

        env = {
            "INTENTFRAME_SOCKET": self._socket_path,
            "INTENTFRAME_USER_ID": user_id,
            "INTENTFRAME_AGENT_ID": agent,
            "INTENTFRAME_WORKSPACE": workspace_id,
            "INTENTFRAME_TASK": task,
        }

        for key, value in manifest.options.items():
            env[f"INTENTFRAME_OPT_{key.upper()}"] = str(value)

        python = self._venv_manager.python_path(manifest.name)

        return self._runner.run(
            manifest=manifest,
            package_dir=package_dir,
            python=python,
            env=env,
            timeout=timeout,
        )

    # ── Audit & Observability ────────────────────────────────────────

    def get_audit_log(self) -> List[Dict[str, Any]]:
        """Retrieve the full audit trail from the IntentFrame Core service."""
        return self._server_client.get_audit_log()


# ═════════════════════════════════════════════════════════════════════════════
# Config-driven entry point
# ═════════════════════════════════════════════════════════════════════════════


def run_config(
    config: str | Path,
    agent_dir: str | Path = "external_agents",
    verbose: bool = True,
) -> None:
    """Single entry point: load config, setup dashboard, run all tasks.

    Args:
        config:    Path to a dashboard.yaml file.
        agent_dir: Path to the directory containing agent packages.
        verbose:   Print progress to stdout.
    """
    cfg = load_config(config)

    with IntentFrameDashboard(agent_dir=agent_dir) as dashboard:
        # ── Register users ───────────────────────────────────────
        # Each policy registers against the (user_id, agent_id) pair the
        # tasks declare it runs against.  A user that drives N agents is
        # registered N times — one slot per agent.
        agents_per_user: Dict[str, set[str]] = {}
        for t in cfg.tasks:
            agents_per_user.setdefault(t.user, set()).add(t.agent)

        for user_id, user_cfg in cfg.users.items():
            allowed_actions: Dict[str, ActionPermission] = {}
            for action, perm_cfg in user_cfg.allowed_actions.items():
                allowed_actions[action] = ActionPermission(
                    safe=perm_cfg.safe,
                    constraints=perm_cfg.constraints,
                )

            intent_limits = [
                SemanticIntentLimit(
                    limit_id=lc.limit_id,
                    domain=lc.domain,
                    description=lc.description,
                    raw=lc.raw,
                    threshold=lc.threshold,
                    pattern=lc.pattern,
                    effect=lc.effect,
                    scope=lc.scope,
                )
                for lc in user_cfg.intent_limits
            ]

            domain_constraints: Dict[str, dict] = {}
            for domain_name, dc_cfg in user_cfg.domain_constraints.items():
                domain_constraints[domain_name] = dc_cfg.model_dump(exclude_none=True)

            agent_ids = agents_per_user.get(user_id) or {user_id}
            for agent_id in sorted(agent_ids):
                dashboard.register_user(
                    user_id=user_id,
                    agent_id=agent_id,
                    allowed_actions=allowed_actions,
                    intent_limits=intent_limits,
                    domain_constraints=domain_constraints,
                    metadata=user_cfg.metadata,
                )
                if verbose:
                    print(f"  [OK] Policy registered for user='{user_id}' agent='{agent_id}'")

        # ── Register workspaces ──────────────────────────────────
        for ws_id, ws_cfg in cfg.workspaces.items():
            mounts = [
                ResourceMount(
                    virtual_path=m.virtual_path,
                    real_path=m.real_path,
                    **({"file_filter": m.file_filter} if m.file_filter else {}),
                    writable=m.writable,
                )
                for m in ws_cfg.mounts
            ]
            dashboard.register_workspace(
                workspace_id=ws_id,
                mounts=mounts,
                base_path=ws_cfg.base_path,
            )
            if verbose:
                print(f"  [OK] Workspace '{ws_id}' registered")

        # ── Install agents referenced by tasks ───────────────────
        needed_agents = {t.agent for t in cfg.tasks}
        available = dashboard.list_available()
        for name in needed_agents:
            if name not in available:
                raise RuntimeError(
                    f"Task references agent '{name}' but no package found "
                    f"in {agent_dir}/. Available: {list(available.keys())}"
                )
            dashboard.install(name)
            manifest = available[name]
            if verbose:
                print(
                    f"  [OK] Agent '{name}' installed "
                    f"(v{manifest.version} by {manifest.author})"
                )

        # ── Run tasks ────────────────────────────────────────────
        for task_cfg in cfg.tasks:
            if verbose:
                print(f"\n{'=' * 60}")
                print(f"  Running: {task_cfg.description}")
                print(f"  Agent: {task_cfg.agent}  User: {task_cfg.user}")
                print(f"{'=' * 60}")

            result = dashboard.run(
                task_cfg.description,
                agent=task_cfg.agent,
                user_id=task_cfg.user,
                workspace_id=task_cfg.workspace,
                timeout=task_cfg.timeout,
            )

            if verbose:
                _print_results(result)

        # ── Audit trail ──────────────────────────────────────────
        if verbose:
            audit_log = dashboard.get_audit_log()
            _print_audit(audit_log)


def _print_results(result: RunResult) -> None:
    print(f"\n  Agent:    {result.name}")
    print(f"  Status:   {result.status}")
    print(f"  Duration: {result.duration:.2f}s")

    if result.result:
        print(f"\n  Processed: {result.result.get('processed', 0)}")
        print(f"  Blocked:   {result.result.get('blocked', 0)}")
        print(f"  Skipped:   {result.result.get('skipped', 0)}")
        print(f"  Total:     {result.result.get('total', 0)}")

    if result.stdout:
        print(f"\n  --- Agent stdout ---")
        for line in result.stdout.strip().splitlines()[:40]:
            print(f"  {line}")

    if result.stderr:
        print(f"\n  --- Agent stderr ---")
        for line in result.stderr.strip().splitlines()[-30:]:
            print(f"  {line}")

    if result.error and not result.stderr:
        print(f"  Error:    {result.error[:200]}")


def _print_audit(audit_log: list) -> None:
    print(f"\n{'=' * 60}")
    print(f"  Audit Trail ({len(audit_log)} entries)")
    print(f"{'=' * 60}")

    for i, entry in enumerate(audit_log, 1):
        action = entry.get("action", "?")
        decision = entry.get("decision", "?")
        path = entry.get("decision_path", "?")
        reason = entry.get("message", "")[:50]
        icon = "\u2705" if decision == "ALLOW" else "\u26d4"
        path_tag = "\u26a1" if path == "fast_path" else "\U0001f916"
        print(f"  {i:>2}. {action:<18} {icon} {decision:<8} {path_tag} {path}")
        if reason:
            print(f"      {reason}")

    print(f"{'=' * 60}\n")
