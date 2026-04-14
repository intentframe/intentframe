"""macOS Seatbelt sandbox engine.

Generates the entire SBPL profile dynamically in Python — no static .sbpl
file.  This mirrors Anthropic's sandbox-runtime approach where the profile
is built as an array of rule strings and passed inline to ``sandbox-exec -p``.

Profile structure (order matters — Seatbelt uses last-match-wins):
  1. Header + deny default
  2. Essential system allowances (process, mach, sysctl, iokit, etc.)
  3. Essential system file reads (dyld, libs, shells, /dev)
  4. Controlled temp writes (SANDBOX_TMPDIR only — not the entire /var/folders)
  5. Template-specific rules (network scope)
  6. Mount-derived allow rules (from VFS mounts)
  7. Non-negotiable deny overrides (always last so they win)
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil

from executor.sandbox.engine import SandboxEngine
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

# System file reads — intentionally does NOT include /private/var/folders
# or /var.  Those broad allows would undermine deny rules for paths under
# the macOS per-user temp directory.  Mount-derived rules grant access to
# specific directories the command actually needs.
_SYSTEM_FILE_READS = (
    "(allow file-read-metadata)",
    "(allow file-read*",
    '  (subpath "/usr/lib")',
    '  (subpath "/usr/bin")',
    '  (subpath "/usr/sbin")',
    '  (subpath "/usr/share")',
    '  (subpath "/bin")',
    '  (subpath "/sbin")',
    '  (subpath "/System/Library")',
    '  (subpath "/Library/Apple")',
    '  (subpath "/private/etc")',
    '  (subpath "/private/var/db")',
    '  (subpath "/dev")',
    '  (literal "/")',
    '  (literal "/etc")',
    '  (literal "/private")',
    '  (literal "/private/var"))',
)


def _sandbox_tmpdir_rules() -> tuple[str, ...]:
    """Read+write rules for the controlled sandbox temp directory."""
    canon = os.path.realpath(SANDBOX_TMPDIR)
    return (
        f"(allow file-read* (subpath {_q(canon)}))",
        f"(allow file-write* (subpath {_q(canon)}))",
    )


_SYSTEM_DEVICE_WRITES = (
    '(allow file-write* (literal "/dev/null") (literal "/dev/tty")'
    ' (literal "/dev/dtracehelper"))',
)


class MacOSSandboxEngine(SandboxEngine):
    """macOS ``sandbox-exec`` engine — fully dynamic profile generation."""

    def __init__(self) -> None:
        self._sandbox_exec = shutil.which("sandbox-exec")

    def available(self) -> bool:
        return self._sandbox_exec is not None

    def wrap(self, command: str, plan: ExecutionPlan) -> str:
        if not self.available():
            raise RuntimeError("MacOSSandboxEngine.wrap() called but engine unavailable")

        _ensure_sandbox_tmpdir()
        profile = generate_sandbox_profile(plan)
        quoted_cmd = shlex.quote(command)
        env_prefix = f"TMPDIR={os.path.realpath(SANDBOX_TMPDIR)}"
        return (
            f"env {env_prefix} {self._sandbox_exec}"
            f" -p {shlex.quote(profile)} /bin/sh -c {quoted_cmd}"
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

    # 3. Essential system file reads
    rules.extend(_SYSTEM_FILE_READS)

    # 4. Controlled temp directory + device writes
    rules.extend(_sandbox_tmpdir_rules())
    rules.extend(_SYSTEM_DEVICE_WRITES)

    # 5. Template-specific rules (network)
    rules.extend(_network_rules(plan.template))

    # 6. Mount-derived allow rules
    rules.extend(_mount_read_rules(plan))
    rules.extend(_mount_write_rules(plan))

    # 7. Non-negotiable deny overrides (last so they win)
    rules.extend(_deny_override_rules(plan))

    return "\n".join(rules)


# ------------------------------------------------------------------
# Rule generators
# ------------------------------------------------------------------

def _network_rules(tmpl: SandboxTemplate) -> list[str]:
    rules: list[str] = []

    if tmpl in (
        SandboxTemplate.NETWORK_OUTBOUND,
        SandboxTemplate.NETWORK_FULL,
        SandboxTemplate.UNRESTRICTED,
    ):
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


def _mount_read_rules(plan: ExecutionPlan) -> list[str]:
    if plan.template == SandboxTemplate.PURE_COMPUTE:
        return []

    rules: list[str] = []
    for p in plan.allowed_read_paths:
        rules.append(f"(allow file-read* (subpath {_q(p)}))")
    return rules


def _mount_write_rules(plan: ExecutionPlan) -> list[str]:
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
