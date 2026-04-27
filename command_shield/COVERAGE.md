# Command Shield — Classifier Coverage Map

> **This file is auto-generated from
> `command_shield/capabilities/*.yaml` by
> `scripts/generate_coverage_md.py`.  Do not hand-edit — update the
> YAML and regenerate.**

The classifier's sensitive-surface capability families map 1:1 to
MITRE ATT&CK (Enterprise) tactics.  Each row is a rule in the YAML
corpus; the `capability` column is the literal ID the classifier
emits and that `SENSITIVE_SURFACE_DENY_CAPABILITIES` clamps.

When every MITRE tactic a shell-and-python operator can reasonably
reach has at least one row, the classifier is **done** for that
tactic — further additions require either a newly published MITRE
technique or a production miss found via the telemetry hook in
`command_shield.telemetry`.  Speculative additions are out of scope;
write the evidence down before opening a PR.

Tactics not currently mapped (intentional out-of-scope for a
shell+python operator — listed here so reviewers know the gap is
deliberate):

- `initial_access` — handled upstream by the gateway, not by the
  command classifier.
- `reconnaissance`, `resource_development` — pre-compromise; no
  on-host shell shape to tag.
- `impact` — destructive shapes (``rm -rf /``, ``mkfs``, ``dd``)
  are caught by the catastrophic pattern layer in
  `command_shield/patterns/catastrophic.json`, not by a
  `capability:impact:*` tag.

---


## `collection`

Reads that yield non-credential PII / session state / contacts / mail / chat history.  Same emission shape as ``credential_access`` (``capability:data_read:*``); the distinction is the MITRE tactic mapping, not the tag prefix.


| Rule ID | Capability tag | MITRE technique(s) | Source YAML |
|---|---|---|---|
| `data_read__browser_profile_data` | `capability:data_read:browser_profile_data` | T1217 | `command_shield/capabilities/data_read.yaml` |
| `data_read__browser_session_data` | `capability:data_read:browser_session_data` | T1539, T1217 | `command_shield/capabilities/data_read.yaml` |
| `data_read__db_client_history` | `capability:data_read:db_client_history` | T1552.003 | `command_shield/capabilities/data_read.yaml` |
| `data_read__mail_store` | `capability:data_read:mail_store` | T1114.001 | `command_shield/capabilities/data_read.yaml` |
| `data_read__messaging_history` | `capability:data_read:messaging_history` | T1005 | `command_shield/capabilities/data_read.yaml` |
| `data_read__personal_records` | `capability:data_read:personal_records` | T1005, T1114 | `command_shield/capabilities/data_read.yaml` |
| `data_read__shell_history` | `capability:data_read:shell_history` | T1552.003 | `command_shield/capabilities/data_read.yaml` |

## `credential_access`

Reads that yield credentials (tokens, keys, password-manager vaults, keychain material, dotenv secrets).  The classifier emits ``capability:data_read:*`` with the read-only-incompatible gate active so a matching command can never also be tagged ``read_only:*``.


| Rule ID | Capability tag | MITRE technique(s) | Source YAML |
|---|---|---|---|
| `data_read__auth_authority` | `capability:data_read:auth_authority` | T1003.008 | `command_shield/capabilities/data_read.yaml` |
| `data_read__browser_cookies` | `capability:data_read:browser_cookies` | T1539, T1555.003 | `command_shield/capabilities/data_read.yaml` |
| `data_read__cloud_tokens` | `capability:data_read:cloud_tokens` | T1552.001, T1552.004 | `command_shield/capabilities/data_read.yaml` |
| `data_read__cloud_tokens__2` | `capability:data_read:cloud_tokens` | T1552.001, T1552.004 | `command_shield/capabilities/data_read.yaml` |
| `data_read__credential_material` | `capability:data_read:credential_material` | T1552.001, T1555 | `command_shield/capabilities/data_read.yaml` |
| `data_read__credential_material__2` | `capability:data_read:credential_material` | T1552.001, T1555 | `command_shield/capabilities/data_read.yaml` |
| `data_read__dotfile_secrets` | `capability:data_read:dotfile_secrets` | T1552.001 | `command_shield/capabilities/data_read.yaml` |
| `data_read__password_manager_export` | `capability:data_read:password_manager_export` | T1555.005 | `command_shield/capabilities/data_read.yaml` |
| `data_read__process_env` | `capability:data_read:process_env` | T1552.001 | `command_shield/capabilities/data_read.yaml` |
| `data_read__ssh_known_hosts` | `capability:data_read:ssh_known_hosts` | T1018, T1083 | `command_shield/capabilities/data_read.yaml` |

## `defense_evasion`

Shapes that disable, degrade, or tamper with host telemetry and trust surfaces (security daemons, audit / unified logging, TCC, firewall rules, kernel tunables, /etc/hosts).  Emitted as ``capability:system_mutate:*``.


| Rule ID | Capability tag | MITRE technique(s) | Source YAML |
|---|---|---|---|
| `system_mutate__audit_log` | `capability:system_mutate:audit_log` | T1562.006, T1070 | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__backup` | `capability:system_mutate:backup` | T1490 | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__boot_policy` | `capability:system_mutate:boot_policy` | T1542 | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__browser_security_pref` | `capability:system_mutate:browser_security_pref` | T1562.001 | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__disk_encryption` | `capability:system_mutate:disk_encryption` | T1486, T1490 | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__firewall` | `capability:system_mutate:firewall` | T1562.004 | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__host_network_config` | `capability:system_mutate:host_network_config` | T1562.004 | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__hostname` | `capability:system_mutate:hostname` | T1036 | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__hosts_file` | `capability:system_mutate:hosts_file` | T1565.001 | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__kernel_tunable` | `capability:system_mutate:kernel_tunable` | T1562.004 | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__print_config` | `capability:system_mutate:print_config` | _(none)_ | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__radio_power` | `capability:system_mutate:radio_power` | _(none)_ | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__remote_access` | `capability:system_mutate:remote_access` | T1021 | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__screen_sharing` | `capability:system_mutate:screen_sharing` | T1021.004 | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__security_daemon` | `capability:system_mutate:security_daemon` | T1562.001 | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__tcc_privacy` | `capability:system_mutate:tcc_privacy` | T1562.001 | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__time_sync` | `capability:system_mutate:time_sync` | T1070.006 | `command_shield/capabilities/system_mutate.yaml` |

## `exfiltration`

Shapes whose primary effect is moving local-host data outbound (HTTP upload, scp / rsync outbound, ssh tunnels, cloud-bucket upload).  Emitted as ``capability:network_exfil:*`` with the same read-only-incompatible gate as ``data_read:*``.


| Rule ID | Capability tag | MITRE technique(s) | Source YAML |
|---|---|---|---|
| `network_exfil__cloud_upload` | `capability:network_exfil:cloud_upload` | T1567.002 | `command_shield/capabilities/network_exfil.yaml` |
| `network_exfil__file_transfer_outbound` | `capability:network_exfil:file_transfer_outbound` | T1048 | `command_shield/capabilities/network_exfil.yaml` |
| `network_exfil__http_upload` | `capability:network_exfil:http_upload` | T1041, T1567.002 | `command_shield/capabilities/network_exfil.yaml` |
| `network_exfil__ssh_tunnel` | `capability:network_exfil:ssh_tunnel` | T1572, T1021.004 | `command_shield/capabilities/network_exfil.yaml` |

## `persistence`

Shapes that plant long-lived execution or config (scheduled tasks, launchd, systemd, browser extensions, MDM profiles, boot-chain trust, account mutation).  Emitted as ``capability:system_mutate:*``.


| Rule ID | Capability tag | MITRE technique(s) | Source YAML |
|---|---|---|---|
| `system_mutate__browser_extension` | `capability:system_mutate:browser_extension` | T1176 | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__cron_mutation` | `capability:system_mutate:cron_mutation` | T1053.003 | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__installer_pkg` | `capability:system_mutate:installer_pkg` | T1072 | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__kernel_extension` | `capability:system_mutate:kernel_extension` | T1547.006 | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__launchd_mutation` | `capability:system_mutate:launchd_mutation` | T1543.004 | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__mdm_profile` | `capability:system_mutate:mdm_profile` | T1556 | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__persistence` | `capability:system_mutate:persistence` | T1547, T1037 | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__service_mgmt` | `capability:system_mutate:service_mgmt` | T1543.002 | `command_shield/capabilities/system_mutate.yaml` |
| `system_mutate__user_account` | `capability:system_mutate:user_account` | T1136 | `command_shield/capabilities/system_mutate.yaml` |

## `privilege_escalation`

Shapes that rewrite the privilege graph itself — sudoers / PAM / passwd / shadow / group writes.  Emitted as ``capability:system_mutate:privilege_config``.


| Rule ID | Capability tag | MITRE technique(s) | Source YAML |
|---|---|---|---|
| `system_mutate__privilege_config` | `capability:system_mutate:privilege_config` | T1548.003 | `command_shield/capabilities/system_mutate.yaml` |

---

## Summary

- **Total sensitive-surface rules:** 48
- **Distinct capability tags:** 46
- **Tactics covered:** 6

Per-tactic counts (unique `capability:<family>:<suffix>` pairs; a suffix split across multiple regex rows — e.g. `data_read:cloud_tokens` file-shape and verb-shape — counts once):

- `defense_evasion`: **17**
- `persistence`: **9**
- `credential_access`: **8**
- `collection`: **7**
- `exfiltration`: **4**
- `privilege_escalation`: **1**
