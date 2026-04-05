"""
Runner — launches agent programs and manages their lifecycle.

The Runner does NOT know what the program does internally.
It launches a process with the right environment, monitors it,
enforces timeouts, and collects the result.

Programs connect to IntentFrame via Actor SDK on their own —
the Runner never touches Actor, IntentFrame types, or agent internals.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from intentframe_dashboard.manifest import AgentManifest


@dataclass
class RunResult:
    """Outcome of a single program run."""
    run_id: str
    name: str
    status: str             # "completed", "failed", "timeout"
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    duration: float = 0.0
    env: Dict[str, str] = field(default_factory=dict)


class Runner:
    """
    Launches programs defined by AgentManifest and monitors lifecycle.

    The dashboard builds an env dict (socket path, user ID, task, etc.)
    and the Runner passes it to the process.  The program is responsible
    for reading those env vars and doing its own setup.
    """

    def __init__(self) -> None:
        self._run_counter = 0

    def run(
        self,
        manifest: AgentManifest,
        package_dir: Path,
        python: Path,
        env: Dict[str, str],
        timeout: float = 120.0,
    ) -> RunResult:
        """
        Launch a program according to its manifest and wait for completion.

        Args:
            manifest: The parsed manifest for this agent package.
            package_dir: Absolute path to the agent's package directory.
            python: Path to the agent's venv python executable.
            env: Environment variables to pass (INTENTFRAME_SOCKET, etc.).
            timeout: Max seconds before the process is killed.

        Returns:
            RunResult with status, output, and timing info.
        """
        self._run_counter += 1
        run_id = f"run_{self._run_counter}"

        print(f"\n{'='*60}")
        print(f"[RUNNER] {run_id}: {manifest.name} v{manifest.version}")
        print(f"[RUNNER] Package: {package_dir}")
        print(f"[RUNNER] Python: {python}")
        print(f"[RUNNER] Timeout: {timeout}s")
        print(f"{'='*60}")

        process_env = {**os.environ, **env}
        cmd = self._build_command(manifest, package_dir, python)

        start_time = time.time()

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(package_dir),
                env=process_env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            duration = time.time() - start_time
            status = "completed" if proc.returncode == 0 else "failed"

            result_data = self._parse_result(proc.stdout)

            print(f"\n[RUNNER] {run_id}: {status} in {duration:.1f}s (exit {proc.returncode})")

            return RunResult(
                run_id=run_id,
                name=manifest.name,
                status=status,
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                result=result_data,
                error=proc.stderr if proc.returncode != 0 else None,
                duration=duration,
                env=env,
            )

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            print(f"\n[RUNNER] {run_id}: TIMEOUT after {duration:.1f}s")
            return RunResult(
                run_id=run_id,
                name=manifest.name,
                status="timeout",
                error=f"Process killed after {timeout}s",
                duration=duration,
                env=env,
            )

        except Exception as e:
            duration = time.time() - start_time
            print(f"\n[RUNNER] {run_id}: ERROR: {e}")
            return RunResult(
                run_id=run_id,
                name=manifest.name,
                status="failed",
                error=str(e),
                duration=duration,
                env=env,
            )

    def _build_command(
        self, manifest: AgentManifest, package_dir: Path, python: Path
    ) -> list[str]:
        """Build the command list from manifest runner + entry_point."""
        if manifest.runner == "python":
            return [str(python), "-u", manifest.entry_point]
        elif manifest.runner == "executable":
            return [str(package_dir / manifest.entry_point)]
        elif manifest.runner == "docker":
            return [
                "docker", "run", "--rm",
                str(manifest.entry_point),
            ]
        else:
            raise ValueError(f"Unknown runner type: {manifest.runner!r}")

    def _parse_result(self, stdout: str) -> Optional[Dict[str, Any]]:
        """Try to extract a JSON result from the last line of stdout."""
        lines = stdout.strip().splitlines()
        if not lines:
            return None
        last_line = lines[-1].strip()
        if last_line.startswith("{"):
            try:
                return json.loads(last_line)
            except json.JSONDecodeError:
                pass
        return None
