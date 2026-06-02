"""Capability deny-set constants for the built-in policy profiles.

These constants encode IntentFrame's *language surface* clamp
(``PYTHON_SHELL_ONLY_DENY_CAPABILITIES``) and *sensitive surface* clamp
(``SENSITIVE_SURFACE_DENY_CAPABILITIES``).  They are kept as Python
constants — not pulled from the YAML — so that:

* Other deterministic-accuracy tests can reference them by name without
  parsing YAML (see ``tests/deterministic_accuracy/policies.py``).
* The classifier-vs-policy contract test
  (``tests/test_python_shell_only_policy.py``) can compare strings.

The packaged ``jarvis.yaml`` and ``jarvis_root.yaml`` MUST list
``RUN_COMMAND.constraints.deny_capabilities`` equal to
``sorted(DEFAULT_TERMINAL_DENY_CAPABILITIES)`` — this drift is pinned by
``tests/test_seed_capability_parity.py``.

Profile-independent on purpose: the language surface IntentFrame is
willing to reason about does not change just because the executor
happens to run as root.
"""

from __future__ import annotations


# Tag suffixes mirror what ``command_shield.classifier._SCRIPT_EXECUTION_RULES``
# emits.  ``awk`` is intentionally NOT denied — POSIX shell utility,
# same risk class as sed/cut/grep which are allowed.  Classifier still
# tags it for telemetry so the decision stays one edit away.
PYTHON_SHELL_ONLY_DENY_CAPABILITIES: frozenset[str] = frozenset({
    # Script execution — non-python/shell language interpreters.
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
    # Direct execution of compiled local binaries (``./foo``).
    "capability:script_execution:local_binary",
    # Build / link toolchains (gcc, clang, make, cargo build, …).
    "capability:compilation",
    # Stdin-piped exec into non-python/shell interpreters.
    "capability:stdin_exec:node",
    "capability:stdin_exec:ruby",
    "capability:stdin_exec:perl",
    "capability:stdin_exec:php",
    # Non-python/non-shell ecosystem package installers.  pip / brew /
    # apt / yum / dnf / pacman / apk / gem-via-bundler are intentionally
    # absent — those count as part of the python or shell ecosystem.
    "capability:package_install:npm",
    "capability:package_install:gem",
    "capability:package_install:cargo",
    "capability:package_install:go",
    "capability:package_install:composer",
})


# Sensitive-surface clamp.  Closes the root-demo attack-sweep gap
# (intents 36, 38, 87–91, 97, 99) where the AE rated sensitive reads /
# host mutations as LOW/MEDIUM and Guardian allowed them; denying at
# Gate 2 on the classifier tag catches those shapes without burning an
# AE call.
SENSITIVE_SURFACE_DENY_CAPABILITIES: frozenset[str] = frozenset({
    # Sensitive reads (``data_read:*``).
    "capability:data_read:browser_cookies",
    "capability:data_read:browser_profile_data",
    "capability:data_read:browser_session_data",
    "capability:data_read:auth_authority",
    "capability:data_read:credential_material",
    "capability:data_read:shell_history",
    "capability:data_read:db_client_history",
    "capability:data_read:messaging_history",
    "capability:data_read:personal_records",
    "capability:data_read:dotfile_secrets",
    "capability:data_read:cloud_tokens",
    "capability:data_read:password_manager_export",
    "capability:data_read:process_env",
    "capability:data_read:ssh_known_hosts",
    "capability:data_read:mail_store",
    "capability:data_read:process_memory",
    # System mutations (``system_mutate:*``).
    "capability:system_mutate:host_network_config",
    "capability:system_mutate:hostname",
    "capability:system_mutate:time_sync",
    "capability:system_mutate:security_daemon",
    "capability:system_mutate:browser_security_pref",
    "capability:system_mutate:firewall",
    "capability:system_mutate:hosts_file",
    "capability:system_mutate:privilege_config",
    "capability:system_mutate:user_account",
    "capability:system_mutate:remote_access",
    "capability:system_mutate:disk_encryption",
    "capability:system_mutate:kernel_tunable",
    "capability:system_mutate:persistence",
    "capability:system_mutate:mdm_profile",
    "capability:system_mutate:boot_policy",
    "capability:system_mutate:audit_log",
    "capability:system_mutate:tcc_privacy",
    "capability:system_mutate:backup",
    "capability:system_mutate:installer_pkg",
    "capability:system_mutate:kernel_extension",
    "capability:system_mutate:service_mgmt",
    "capability:system_mutate:launchd_mutation",
    "capability:system_mutate:cron_mutation",
    "capability:system_mutate:browser_extension",
    "capability:system_mutate:screen_sharing",
    "capability:system_mutate:print_config",
    "capability:system_mutate:radio_power",
    "capability:system_mutate:ca_trust",
    "capability:system_mutate:shell_init",
    "capability:system_mutate:history_tamper",
    # Outbound data-exfil surfaces (``network_exfil:*``).
    "capability:network_exfil:http_upload",
    "capability:network_exfil:file_transfer_outbound",
    "capability:network_exfil:ssh_tunnel",
    "capability:network_exfil:cloud_upload",
})


# Union of the two profile-independent clamps.  ``terminal_constraint``
# in the packaged profile YAMLs denies the full set; the two constants
# stay distinct so the *why* of each deny is reviewable (a language-surface
# clamp vs a sensitive-surface clamp) without grepping a flat list.
DEFAULT_TERMINAL_DENY_CAPABILITIES: frozenset[str] = (
    PYTHON_SHELL_ONLY_DENY_CAPABILITIES | SENSITIVE_SURFACE_DENY_CAPABILITIES
)


__all__ = [
    "DEFAULT_TERMINAL_DENY_CAPABILITIES",
    "PYTHON_SHELL_ONLY_DENY_CAPABILITIES",
    "SENSITIVE_SURFACE_DENY_CAPABILITIES",
]
