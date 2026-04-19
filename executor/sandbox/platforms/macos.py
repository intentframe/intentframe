"""macOS Seatbelt sandbox engine.

Generates the entire SBPL profile dynamically in Python — no static .sbpl
file.  This mirrors Anthropic's sandbox-runtime approach where the profile
is built as an array of rule strings and passed inline to ``sandbox-exec -p``.

Profile structure (order matters — Seatbelt uses last-match-wins):
  1. Header + deny default
  2. Essential system allowances (process, mach, sysctl, iokit, etc.)
  3. Global file reads: (allow file-read*) — reads are unrestricted
  4. Controlled temp writes (SANDBOX_TMPDIR only)
  5. Template-specific rules (process visibility, network scope)
  6. Config-derived write allow rules
  7. Non-negotiable deny overrides (always last so they win)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

from executor.sandbox.engine import SandboxedCommand, SandboxEngine
from executor.sandbox.planner import ExecutionPlan
from executor.sandbox.templates import SandboxTemplate

logger = logging.getLogger(__name__)

SANDBOX_TMPDIR = "/tmp/intentframe"


def _q(path: str) -> str:
    """JSON-quote a path for SBPL (handles spaces, special chars)."""
    return json.dumps(path)


# ======================================================================
# Essential Seatbelt rules (tested on macOS 15–26)
#
# Sourced from Anthropic sandbox-runtime macos-sandbox-utils.ts.
# Each section is a tuple of SBPL strings.
# ======================================================================

_HEADER = (
    "(version 1)",
    "(deny default)",
)

_PROCESS_RULES = (
    "(allow process-exec)",
    "(allow process-fork)",
    "(allow process-info* (target same-sandbox))",
    "(allow signal (target same-sandbox))",
    "(allow mach-priv-task-port (target same-sandbox))",
)

_USER_PREFS = (
    "(allow user-preference-read)",
)

_MACH_IPC = (
    "(allow mach-lookup",
    '  (global-name "com.apple.audio.systemsoundserver")',
    '  (global-name "com.apple.distributed_notifications@Uv3")',
    '  (global-name "com.apple.FontObjectsServer")',
    '  (global-name "com.apple.fonts")',
    '  (global-name "com.apple.logd")',
    '  (global-name "com.apple.lsd.mapdb")',
    '  (global-name "com.apple.PowerManagement.control")',
    '  (global-name "com.apple.system.logger")',
    '  (global-name "com.apple.system.notification_center")',
    '  (global-name "com.apple.system.opendirectoryd.libinfo")',
    '  (global-name "com.apple.system.opendirectoryd.membership")',
    '  (global-name "com.apple.bsd.dirhelper")',
    '  (global-name "com.apple.securityd.xpc")',
    '  (global-name "com.apple.coreservices.launchservicesd")',
    '  (global-name "com.apple.SecurityServer"))',
)

_POSIX_IPC = (
    "(allow ipc-posix-shm)",
    "(allow ipc-posix-sem)",
)

_IOKIT = (
    "(allow iokit-open",
    '  (iokit-registry-entry-class "IOSurfaceRootUserClient")',
    '  (iokit-registry-entry-class "RootDomainUserClient")',
    '  (iokit-user-client-class "IOSurfaceSendRight"))',
    "(allow iokit-get-properties)",
)

_SYSTEM_SOCKET = (
    "(allow system-socket (require-all (socket-domain AF_SYSTEM) (socket-protocol 2)))",
)

_SYSCTL = (
    "(allow sysctl-read",
    '  (sysctl-name "hw.activecpu")',
    '  (sysctl-name "hw.busfrequency_compat")',
    '  (sysctl-name "hw.byteorder")',
    '  (sysctl-name "hw.cacheconfig")',
    '  (sysctl-name "hw.cachelinesize_compat")',
    '  (sysctl-name "hw.cpufamily")',
    '  (sysctl-name "hw.cpufrequency")',
    '  (sysctl-name "hw.cpufrequency_compat")',
    '  (sysctl-name "hw.cputype")',
    '  (sysctl-name "hw.l1dcachesize_compat")',
    '  (sysctl-name "hw.l1icachesize_compat")',
    '  (sysctl-name "hw.l2cachesize_compat")',
    '  (sysctl-name "hw.l3cachesize_compat")',
    '  (sysctl-name "hw.logicalcpu")',
    '  (sysctl-name "hw.logicalcpu_max")',
    '  (sysctl-name "hw.machine")',
    '  (sysctl-name "hw.memsize")',
    '  (sysctl-name "hw.ncpu")',
    '  (sysctl-name "hw.nperflevels")',
    '  (sysctl-name "hw.packages")',
    '  (sysctl-name "hw.pagesize")',
    '  (sysctl-name "hw.pagesize_compat")',
    '  (sysctl-name "hw.physicalcpu")',
    '  (sysctl-name "hw.physicalcpu_max")',
    '  (sysctl-name "hw.tbfrequency_compat")',
    '  (sysctl-name "hw.vectorunit")',
    '  (sysctl-name "kern.argmax")',
    '  (sysctl-name "kern.bootargs")',
    '  (sysctl-name "kern.hostname")',
    '  (sysctl-name "kern.maxfiles")',
    '  (sysctl-name "kern.maxfilesperproc")',
    '  (sysctl-name "kern.maxproc")',
    '  (sysctl-name "kern.ngroups")',
    '  (sysctl-name "kern.osproductversion")',
    '  (sysctl-name "kern.osrelease")',
    '  (sysctl-name "kern.ostype")',
    '  (sysctl-name "kern.osvariant_status")',
    '  (sysctl-name "kern.osversion")',
    '  (sysctl-name "kern.secure_kernel")',
    '  (sysctl-name "kern.tcsm_available")',
    '  (sysctl-name "kern.tcsm_enable")',
    '  (sysctl-name "kern.usrstack64")',
    '  (sysctl-name "kern.version")',
    '  (sysctl-name "kern.willshutdown")',
    '  (sysctl-name "machdep.cpu.brand_string")',
    '  (sysctl-name "machdep.ptrauth_enabled")',
    '  (sysctl-name "security.mac.lockdown_mode_state")',
    '  (sysctl-name "sysctl.proc_cputype")',
    '  (sysctl-name "vm.loadavg")',
    '  (sysctl-name-prefix "hw.optional.arm")',
    '  (sysctl-name-prefix "hw.optional.arm.")',
    '  (sysctl-name-prefix "hw.optional.armv8_")',
    '  (sysctl-name-prefix "hw.perflevel")',
    '  (sysctl-name-prefix "kern.proc.all")',
    '  (sysctl-name-prefix "kern.proc.pgrp.")',
    '  (sysctl-name-prefix "kern.proc.pid.")',
    '  (sysctl-name-prefix "machdep.cpu.")',
    '  (sysctl-name-prefix "net.routetable."))',
    '(allow sysctl-write (sysctl-name "kern.tcsm_enable"))',
)

_NOTIFICATIONS = (
    "(allow distributed-notification-post)",
)

_DEVICE_IO = (
    '(allow file-ioctl (literal "/dev/null") (literal "/dev/zero")'
    ' (literal "/dev/random") (literal "/dev/urandom")'
    ' (literal "/dev/dtracehelper") (literal "/dev/tty"))',
    "(allow file-ioctl file-read-data file-write-data",
    '  (require-all (literal "/dev/null") (vnode-type CHARACTER-DEVICE)))',
)

_PTY = (
    "(allow pseudo-tty)",
    '(allow file-ioctl (literal "/dev/ptmx") (regex #"^/dev/ttys"))',
    '(allow file-read* file-write* (literal "/dev/ptmx") (regex #"^/dev/ttys"))',
)

# Global file reads — allow all reads, deny only sensitive paths later.
# This mirrors Anthropic's sandbox-runtime approach: reads are not the
# threat model; writes and network exfiltration are.  Whitelisting
# individual system directories is a losing game (xcrun needs Xcode.app,
# python3 shim needs CLT, Homebrew lives in different places per arch).
_GLOBAL_FILE_READS = (
    "(allow file-read*)",
)


def _sandbox_tmpdir_rules() -> tuple[str, ...]:
    """Write rules for the controlled sandbox temp directory."""
    canon = os.path.realpath(SANDBOX_TMPDIR)
    return (
        f"(allow file-write* (subpath {_q(canon)}))",
    )


_SYSTEM_DEVICE_WRITES = (
    '(allow file-write* (literal "/dev/null") (literal "/dev/tty")'
    ' (literal "/dev/dtracehelper"))',
)


_FALLBACK_PATH = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"


def _system_path() -> str:
    """Build PATH from /etc/paths and /etc/paths.d/* (macOS canonical source).

    This is exactly how macOS itself constructs the default PATH for login
    shells.  Reading these files guarantees the result works on both Intel
    (/usr/local/bin for Homebrew) and Apple Silicon (/opt/homebrew/bin via
    /etc/paths.d/homebrew), and never includes any Python venv.
    """
    dirs: list[str] = []
    try:
        with open("/etc/paths") as f:
            dirs.extend(line.strip() for line in f if line.strip())
        paths_d = Path("/etc/paths.d")
        if paths_d.is_dir():
            for entry in sorted(paths_d.iterdir()):
                if entry.is_file():
                    with open(entry) as f:
                        dirs.extend(line.strip() for line in f if line.strip())
    except OSError:
        dirs = _FALLBACK_PATH.split(":")
    return ":".join(dirs)


class MacOSSandboxEngine(SandboxEngine):
    """macOS ``sandbox-exec`` engine — fully dynamic profile generation."""

    def __init__(self) -> None:
        self._sandbox_exec = shutil.which("sandbox-exec")

    def available(self) -> bool:
        return self._sandbox_exec is not None

    def wrap(self, command: str, plan: ExecutionPlan) -> SandboxedCommand:
        if not self.available():
            raise RuntimeError("MacOSSandboxEngine.wrap() called but engine unavailable")

        _ensure_sandbox_tmpdir()
        profile = generate_sandbox_profile(plan)

        env_overrides: dict[str, str] = {
            "TMPDIR": os.path.realpath(SANDBOX_TMPDIR),
            "PATH": _system_path(),
        }
        if plan.executor_venv_path:
            venv = plan.executor_venv_path
            env_overrides["PATH"] = f"{venv}/bin:" + env_overrides["PATH"]
            env_overrides["VIRTUAL_ENV"] = venv
            env_overrides["PYTHONNOUSERSITE"] = "1"

        return SandboxedCommand(
            argv=[
                self._sandbox_exec,
                "-p", profile,
                "/bin/sh", "-c", command,
            ],
            env_overrides=env_overrides,
        )


def _ensure_sandbox_tmpdir() -> None:
    """Create the controlled sandbox temp directory if it doesn't exist."""
    canon = os.path.realpath(SANDBOX_TMPDIR)
    os.makedirs(canon, mode=0o700, exist_ok=True)


# ======================================================================
# Public profile generator (testable independently of the engine)
# ======================================================================

def generate_sandbox_profile(plan: ExecutionPlan) -> str:
    """Build the complete SBPL profile string for *plan*.

    All paths in *plan* are expected to be canonical (realpath-resolved)
    by the planner.  The engine only serialises them.
    """
    rules: list[str] = []

    # 1. Header + deny default
    rules.extend(_HEADER)

    # 2. Essential system allowances
    rules.extend(_PROCESS_RULES)
    rules.extend(_USER_PREFS)
    rules.extend(_MACH_IPC)
    rules.extend(_POSIX_IPC)
    rules.extend(_IOKIT)
    rules.extend(_SYSTEM_SOCKET)
    rules.extend(_SYSCTL)
    rules.extend(_NOTIFICATIONS)
    rules.extend(_DEVICE_IO)
    rules.extend(_PTY)

    # 3. Global file reads (allow everything, deny sensitive paths later)
    rules.extend(_GLOBAL_FILE_READS)

    # 4. Controlled temp directory + device writes
    rules.extend(_sandbox_tmpdir_rules())
    rules.extend(_SYSTEM_DEVICE_WRITES)

    # 5. Template-specific rules (process visibility, network)
    rules.extend(_template_specific_rules(plan.template))

    # 6. Config-derived write allow rules
    rules.extend(_write_rules(plan))

    # 7. Non-negotiable deny overrides (last so they win)
    rules.extend(_deny_override_rules(plan))

    return "\n".join(rules)


# ------------------------------------------------------------------
# Rule generators
# ------------------------------------------------------------------

def _template_specific_rules(tmpl: SandboxTemplate) -> list[str]:
    """Emit template-gated rules: process visibility, SUID exec, network scope.

    Placed after essential rules (step 2) so Seatbelt last-match-wins
    widens the baseline ``process-info* (target same-sandbox)`` to global
    ``process-info*`` for templates that need system-wide process visibility
    (ps, top, lsof, Activity Monitor queries).

    ``/bin/ps`` is setuid-root (``-rwsr-xr-x``).  macOS Seatbelt
    unconditionally blocks SUID binaries (``forbidden-exec-sugid``)
    regardless of ``(allow process-exec)``.  The ``(with no-sandbox)``
    modifier is the only way to permit it.  Gated to ``network_outbound``+
    because lower templates have no business enumerating system processes.
    """
    rules: list[str] = []

    if tmpl in (
        SandboxTemplate.NETWORK_OUTBOUND,
        SandboxTemplate.NETWORK_FULL,
        SandboxTemplate.UNRESTRICTED,
    ):
        rules.append("(allow process-info*)")
        rules.append('(allow process-exec (literal "/bin/ps") (with no-sandbox))')
        rules.append("(allow network-outbound)")
        rules.append("(allow system-socket (socket-domain AF_INET))")
        rules.append("(allow system-socket (socket-domain AF_INET6))")
        rules.append("(allow system-socket (socket-domain AF_UNIX))")

    if tmpl in (SandboxTemplate.NETWORK_FULL, SandboxTemplate.UNRESTRICTED):
        rules.append("(allow network-bind)")
        rules.append("(allow network-inbound)")

    if tmpl == SandboxTemplate.UNRESTRICTED:
        rules.append("(allow default)")

    return rules


def _write_rules(plan: ExecutionPlan) -> list[str]:
    tmpl = plan.template
    if tmpl in (SandboxTemplate.PURE_COMPUTE, SandboxTemplate.FILE_READ_ONLY):
        return []

    rules: list[str] = []
    for p in plan.allowed_write_paths:
        rules.append(f"(allow file-write* (subpath {_q(p)}))")
    return rules


def _deny_override_rules(plan: ExecutionPlan) -> list[str]:
    rules: list[str] = []
    for p in plan.deny_write_paths:
        rules.append(f"(deny file-write* (subpath {_q(p)}))")
    for p in plan.deny_access_paths:
        rules.append(f"(deny file-read* file-write* (subpath {_q(p)}))")
    return rules
