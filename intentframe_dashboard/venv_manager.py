"""
VenvManager — creates and manages isolated per-agent virtual environments.

Each installed agent gets its own venv with:
1. The IntentFrame SDK packages (auto-installed from the project root)
2. Agent-specific dependencies declared in its manifest

Uses ``uv`` for speed when available, falls back to stdlib ``venv`` + ``pip``.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

from intentframe_dashboard.manifest import AgentManifest

logger = logging.getLogger(__name__)

DEFAULT_ENVS_DIR = Path("~/.intentframe/envs").expanduser()


def _has_uv() -> bool:
    return shutil.which("uv") is not None


class VenvManager:
    """Creates and manages per-agent virtual environments."""

    def __init__(self, envs_dir: Path = DEFAULT_ENVS_DIR) -> None:
        self._envs_dir = envs_dir
        self._use_uv = _has_uv()
        self._project_root = Path(__file__).parent.parent.resolve()

    def env_dir(self, agent_name: str) -> Path:
        return self._envs_dir / agent_name

    def python_path(self, agent_name: str) -> Path:
        return self.env_dir(agent_name) / "bin" / "python"

    def is_installed(self, agent_name: str) -> bool:
        return self.python_path(agent_name).is_file()

    def create(self, manifest: AgentManifest) -> Path:
        """Create a venv for the agent, install IntentFrame SDK + declared deps.

        Returns the path to the venv's python executable.
        """
        venv_dir = self.env_dir(manifest.name)

        logger.info("[VENV] Creating environment for %s at %s", manifest.name, venv_dir)
        print(f"  [VENV] Creating environment for '{manifest.name}'...")

        self._create_venv(venv_dir)
        self._install_sdk(venv_dir)

        if manifest.dependencies:
            self._install_deps(venv_dir, manifest.dependencies)

        python = self.python_path(manifest.name)
        print(f"  [VENV] Ready: {python}")
        return python

    def remove(self, agent_name: str) -> None:
        """Remove an agent's virtual environment."""
        venv_dir = self.env_dir(agent_name)
        if venv_dir.is_dir():
            shutil.rmtree(venv_dir)
            logger.info("[VENV] Removed environment for %s", agent_name)

    def _create_venv(self, venv_dir: Path) -> None:
        """Create a fresh venv (removes existing if present)."""
        if venv_dir.is_dir():
            shutil.rmtree(venv_dir)

        venv_dir.parent.mkdir(parents=True, exist_ok=True)

        if self._use_uv:
            self._run(["uv", "venv", str(venv_dir), "--python", sys.executable])
        else:
            self._run([sys.executable, "-m", "venv", str(venv_dir)])

    def _install_sdk(self, venv_dir: Path) -> None:
        """Install the IntentFrame project (all SDK packages) into the venv."""
        print(f"  [VENV] Installing IntentFrame SDK...")
        pip_cmd = self._pip_install_cmd(venv_dir)
        self._run([*pip_cmd, "-e", str(self._project_root)])

    def _install_deps(self, venv_dir: Path, deps: list[str]) -> None:
        """Install agent-specific dependencies."""
        print(f"  [VENV] Installing agent dependencies: {', '.join(deps)}")
        pip_cmd = self._pip_install_cmd(venv_dir)
        self._run([*pip_cmd, *deps])

    def _pip_install_cmd(self, venv_dir: Path) -> list[str]:
        """Return the base command for pip install in the given venv."""
        if self._use_uv:
            return ["uv", "pip", "install", "--python", str(venv_dir / "bin" / "python")]
        return [str(venv_dir / "bin" / "pip"), "install"]

    def _run(self, cmd: list[str]) -> None:
        """Run a command, raise on failure."""
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Command failed: {' '.join(cmd)}\n"
                f"stderr: {result.stderr[:500]}"
            )
