# Command Shield — Classifier Coverage Map

> **This file is auto-generated from
> `command_shield/capabilities/*.yaml` by
> `command_shield/generate_coverage_md.py`.  Do not hand-edit — update the
> YAML and regenerate.**

Command Shield's YAML-backed capability rules are annotated with
MITRE ATT&CK (Enterprise) tactics where the mapping is useful.  Each
row is a rule in the YAML corpus; the `capability` column is the
literal ID the classifier emits.  MITRE data is documentation
metadata only: it does not change runtime matching and does not create
policy aliases.

Rows marked `sensitive: true` are included in
`CORPUS.sensitive_capability_ids()`.  When the reachable shell /
Python tactics have coverage and the telemetry hook in
`command_shield.telemetry` stops surfacing untagged high-verdict
misses, the classifier is **done enough** for this layer.  Further
additions require either a newly published relevant MITRE technique,
a concrete production miss, or a rule split that makes an existing
tag more precise.  Speculative additions are out of scope; write the
evidence down before opening a PR.

Tactics not currently mapped (intentional out-of-scope for a
shell+python operator — listed here so reviewers know the gap is
deliberate):

- `initial_access` — outside the scope of this pre-exec command
  classifier.
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

## `command_and_control`

Outbound connect-back shapes.  Currently overlaps with ``exfiltration`` (a reverse SSH tunnel is both), and with ``network_probe:*`` for generic outbound network probes; no dedicated sub-tags yet.


| Rule ID | Capability tag | MITRE technique(s) | Source YAML |
|---|---|---|---|
| `binary_download` | `capability:binary_download` | _(none)_ | `command_shield/capabilities/binary_download.yaml` |
| `network_bind` | `capability:network_bind` | _(none)_ | `command_shield/capabilities/network_bind.yaml` |

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

## `discovery`

Reads that map the target environment (known_hosts, process lists, filesystem enumeration).  Currently represented only by ``data_read:ssh_known_hosts``; generic filesystem listing is covered by the ``read_only:filesystem_list`` family and is not classified as a sensitive surface.


| Rule ID | Capability tag | MITRE technique(s) | Source YAML |
|---|---|---|---|
| `network_probe__dns` | `capability:network_probe:dns` | _(none)_ | `command_shield/capabilities/network_probe.yaml` |
| `network_probe__file_transfer` | `capability:network_probe:file_transfer` | _(none)_ | `command_shield/capabilities/network_probe.yaml` |
| `network_probe__file_transfer__2` | `capability:network_probe:file_transfer` | _(none)_ | `command_shield/capabilities/network_probe.yaml` |
| `network_probe__file_transfer__3` | `capability:network_probe:file_transfer` | _(none)_ | `command_shield/capabilities/network_probe.yaml` |
| `network_probe__http_download` | `capability:network_probe:http_download` | _(none)_ | `command_shield/capabilities/network_probe.yaml` |
| `network_probe__http_download__2` | `capability:network_probe:http_download` | _(none)_ | `command_shield/capabilities/network_probe.yaml` |
| `network_probe__http_get` | `capability:network_probe:http_get` | _(none)_ | `command_shield/capabilities/network_probe.yaml` |
| `network_probe__http_get__2` | `capability:network_probe:http_get` | _(none)_ | `command_shield/capabilities/network_probe.yaml` |
| `network_probe__http_get__3` | `capability:network_probe:http_get` | _(none)_ | `command_shield/capabilities/network_probe.yaml` |
| `network_probe__http_mutate` | `capability:network_probe:http_mutate` | _(none)_ | `command_shield/capabilities/network_probe.yaml` |
| `network_probe__http_mutate__2` | `capability:network_probe:http_mutate` | _(none)_ | `command_shield/capabilities/network_probe.yaml` |
| `network_probe__http_mutate__3` | `capability:network_probe:http_mutate` | _(none)_ | `command_shield/capabilities/network_probe.yaml` |
| `network_probe__icmp` | `capability:network_probe:icmp` | _(none)_ | `command_shield/capabilities/network_probe.yaml` |
| `network_probe__port_scan` | `capability:network_probe:port_scan` | _(none)_ | `command_shield/capabilities/network_probe.yaml` |
| `network_probe__port_scan__2` | `capability:network_probe:port_scan` | _(none)_ | `command_shield/capabilities/network_probe.yaml` |
| `network_probe__trace` | `capability:network_probe:trace` | _(none)_ | `command_shield/capabilities/network_probe.yaml` |
| `network_probe__whois` | `capability:network_probe:whois` | _(none)_ | `command_shield/capabilities/network_probe.yaml` |
| `read_only__archive_inspect` | `capability:read_only:archive_inspect` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__archive_inspect__2` | `capability:read_only:archive_inspect` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__archive_inspect__3` | `capability:read_only:archive_inspect` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__archive_inspect__4` | `capability:read_only:archive_inspect` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__archive_inspect__5` | `capability:read_only:archive_inspect` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__container_inspect` | `capability:read_only:container_inspect` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__container_inspect__2` | `capability:read_only:container_inspect` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__filesystem_list` | `capability:read_only:filesystem_list` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__filesystem_list__2` | `capability:read_only:filesystem_list` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__filesystem_read` | `capability:read_only:filesystem_read` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__network_inspect` | `capability:read_only:network_inspect` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__network_inspect__2` | `capability:read_only:network_inspect` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__network_inspect__3` | `capability:read_only:network_inspect` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__network_inspect__4` | `capability:read_only:network_inspect` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__network_inspect__5` | `capability:read_only:network_inspect` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__process_inspect` | `capability:read_only:process_inspect` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__search` | `capability:read_only:search` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__search__2` | `capability:read_only:search` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__system_info` | `capability:read_only:system_info` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__system_info__2` | `capability:read_only:system_info` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__system_info__3` | `capability:read_only:system_info` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__system_info__4` | `capability:read_only:system_info` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__text_transform` | `capability:read_only:text_transform` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__text_transform__2` | `capability:read_only:text_transform` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__text_transform__3` | `capability:read_only:text_transform` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__vcs_inspect` | `capability:read_only:vcs_inspect` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__vcs_inspect__2` | `capability:read_only:vcs_inspect` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__vcs_inspect__3` | `capability:read_only:vcs_inspect` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__vcs_inspect__4` | `capability:read_only:vcs_inspect` | _(none)_ | `command_shield/capabilities/read_only.yaml` |
| `read_only__vcs_inspect__5` | `capability:read_only:vcs_inspect` | _(none)_ | `command_shield/capabilities/read_only.yaml` |

## `execution`

Shapes that run code — already covered by ``capability:script_execution:*``, ``capability:stdin_exec:*``, and ``capability:download_and_exec``; not re-enumerated here since they are not part of the sensitive-surface classifier families documented in this map.


| Rule ID | Capability tag | MITRE technique(s) | Source YAML |
|---|---|---|---|
| `compilation` | `capability:compilation` | _(none)_ | `command_shield/capabilities/compilation.yaml` |
| `download_and_exec` | `capability:download_and_exec` | _(none)_ | `command_shield/capabilities/download_and_exec.yaml` |
| `package_install__apk` | `capability:package_install:apk` | _(none)_ | `command_shield/capabilities/package_install.yaml` |
| `package_install__apt` | `capability:package_install:apt` | _(none)_ | `command_shield/capabilities/package_install.yaml` |
| `package_install__brew` | `capability:package_install:brew` | _(none)_ | `command_shield/capabilities/package_install.yaml` |
| `package_install__cargo` | `capability:package_install:cargo` | _(none)_ | `command_shield/capabilities/package_install.yaml` |
| `package_install__composer` | `capability:package_install:composer` | _(none)_ | `command_shield/capabilities/package_install.yaml` |
| `package_install__dnf` | `capability:package_install:dnf` | _(none)_ | `command_shield/capabilities/package_install.yaml` |
| `package_install__gem` | `capability:package_install:gem` | _(none)_ | `command_shield/capabilities/package_install.yaml` |
| `package_install__go` | `capability:package_install:go` | _(none)_ | `command_shield/capabilities/package_install.yaml` |
| `package_install__npm` | `capability:package_install:npm` | _(none)_ | `command_shield/capabilities/package_install.yaml` |
| `package_install__pacman` | `capability:package_install:pacman` | _(none)_ | `command_shield/capabilities/package_install.yaml` |
| `package_install__pip` | `capability:package_install:pip` | _(none)_ | `command_shield/capabilities/package_install.yaml` |
| `package_install__yum` | `capability:package_install:yum` | _(none)_ | `command_shield/capabilities/package_install.yaml` |
| `script_execution__awk` | `capability:script_execution:awk` | _(none)_ | `command_shield/capabilities/script_execution.yaml` |
| `script_execution__deno_bun` | `capability:script_execution:deno_bun` | _(none)_ | `command_shield/capabilities/script_execution.yaml` |
| `script_execution__dotnet` | `capability:script_execution:dotnet` | _(none)_ | `command_shield/capabilities/script_execution.yaml` |
| `script_execution__go` | `capability:script_execution:go` | _(none)_ | `command_shield/capabilities/script_execution.yaml` |
| `script_execution__java` | `capability:script_execution:java` | _(none)_ | `command_shield/capabilities/script_execution.yaml` |
| `script_execution__java__2` | `capability:script_execution:java` | _(none)_ | `command_shield/capabilities/script_execution.yaml` |
| `script_execution__julia` | `capability:script_execution:julia` | _(none)_ | `command_shield/capabilities/script_execution.yaml` |
| `script_execution__local_binary` | `capability:script_execution:local_binary` | _(none)_ | `command_shield/capabilities/script_execution.yaml` |
| `script_execution__lua` | `capability:script_execution:lua` | _(none)_ | `command_shield/capabilities/script_execution.yaml` |
| `script_execution__node` | `capability:script_execution:node` | _(none)_ | `command_shield/capabilities/script_execution.yaml` |
| `script_execution__node__2` | `capability:script_execution:node` | _(none)_ | `command_shield/capabilities/script_execution.yaml` |
| `script_execution__perl` | `capability:script_execution:perl` | _(none)_ | `command_shield/capabilities/script_execution.yaml` |
| `script_execution__perl__2` | `capability:script_execution:perl` | _(none)_ | `command_shield/capabilities/script_execution.yaml` |
| `script_execution__php` | `capability:script_execution:php` | _(none)_ | `command_shield/capabilities/script_execution.yaml` |
| `script_execution__php__2` | `capability:script_execution:php` | _(none)_ | `command_shield/capabilities/script_execution.yaml` |
| `script_execution__python` | `capability:script_execution:python` | _(none)_ | `command_shield/capabilities/script_execution.yaml` |
| `script_execution__r` | `capability:script_execution:r` | _(none)_ | `command_shield/capabilities/script_execution.yaml` |
| `script_execution__ruby` | `capability:script_execution:ruby` | _(none)_ | `command_shield/capabilities/script_execution.yaml` |
| `script_execution__ruby__2` | `capability:script_execution:ruby` | _(none)_ | `command_shield/capabilities/script_execution.yaml` |
| `script_execution__shell` | `capability:script_execution:shell` | _(none)_ | `command_shield/capabilities/script_execution.yaml` |
| `script_execution__swift` | `capability:script_execution:swift` | _(none)_ | `command_shield/capabilities/script_execution.yaml` |
| `spawns_process` | `capability:spawns_process` | _(none)_ | `command_shield/capabilities/spawns_process.yaml` |
| `stdin_exec__any` | `capability:stdin_exec` | _(none)_ | `command_shield/capabilities/stdin_exec.yaml` |
| `stdin_exec__node` | `capability:stdin_exec:node` | _(none)_ | `command_shield/capabilities/stdin_exec.yaml` |
| `stdin_exec__perl` | `capability:stdin_exec:perl` | _(none)_ | `command_shield/capabilities/stdin_exec.yaml` |
| `stdin_exec__php` | `capability:stdin_exec:php` | _(none)_ | `command_shield/capabilities/stdin_exec.yaml` |
| `stdin_exec__python` | `capability:stdin_exec:python` | _(none)_ | `command_shield/capabilities/stdin_exec.yaml` |
| `stdin_exec__ruby` | `capability:stdin_exec:ruby` | _(none)_ | `command_shield/capabilities/stdin_exec.yaml` |
| `stdin_exec__shell` | `capability:stdin_exec:shell` | _(none)_ | `command_shield/capabilities/stdin_exec.yaml` |

## `exfiltration`

Shapes whose primary effect is moving local-host data outbound (HTTP upload, scp / rsync outbound, ssh tunnels, cloud-bucket upload).  Emitted as ``capability:network_exfil:*`` with the same read-only-incompatible gate as ``data_read:*``.


| Rule ID | Capability tag | MITRE technique(s) | Source YAML |
|---|---|---|---|
| `network_exfil__cloud_upload` | `capability:network_exfil:cloud_upload` | T1567.002 | `command_shield/capabilities/network_exfil.yaml` |
| `network_exfil__file_transfer_outbound` | `capability:network_exfil:file_transfer_outbound` | T1048 | `command_shield/capabilities/network_exfil.yaml` |
| `network_exfil__http_upload` | `capability:network_exfil:http_upload` | T1041, T1567.002 | `command_shield/capabilities/network_exfil.yaml` |
| `network_exfil__ssh_tunnel` | `capability:network_exfil:ssh_tunnel` | T1572, T1021.004 | `command_shield/capabilities/network_exfil.yaml` |

## `impact`

Destructive shapes — caught by the catastrophic pattern layer (``command_shield/patterns/catastrophic.json``), not by the sensitive-surface classifier.


| Rule ID | Capability tag | MITRE technique(s) | Source YAML |
|---|---|---|---|
| `process_signal` | `capability:process_signal` | _(none)_ | `command_shield/capabilities/process_signal.yaml` |

## `persistence`

Shapes that plant long-lived execution or config (scheduled tasks, launchd, systemd, browser extensions, MDM profiles, boot-chain trust, account mutation).  Emitted as ``capability:system_mutate:*``.


| Rule ID | Capability tag | MITRE technique(s) | Source YAML |
|---|---|---|---|
| `background_exec` | `capability:background_exec` | _(none)_ | `command_shield/capabilities/background_exec.yaml` |
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

## Unmapped (no MITRE tactic declared)

Non-sensitive rules whose YAML row does not declare a `mitre_family`.  They still produce a `capability:*` tag and are listed here so every rule remains traceable, but they do not roll up into a tactic bucket.


| Rule ID | Capability tag | Source YAML |
|---|---|---|
| `filesystem_write` | `capability:filesystem_write` | `command_shield/capabilities/filesystem_write.yaml` |

---

## Summary

- **Total rules:** 143
- **Sensitive-surface capability tags:** 46
- **Tactics covered:** 10
- **Unmapped (no MITRE tactic):** 1

Per-tactic counts (unique `capability:<family>[:<suffix>]` pairs; a suffix split across multiple regex rows — e.g. `data_read:cloud_tokens` file-shape and verb-shape — counts once):

- `execution`: **38**
- `discovery`: **19**
- `defense_evasion`: **17**
- `persistence`: **10**
- `credential_access`: **8**
- `collection`: **7**
- `exfiltration`: **4**
- `command_and_control`: **2**
- `impact`: **1**
- `privilege_escalation`: **1**
