# Problem: Host File Tools Cannot Access Privileged Paths

Status: **open**

---

## What is happening

When Jarvis runs in the root demo profile, it sometimes calls host file tools
(`read_host_file`, `list_host_directory`) on paths that require root privilege,
such as `/var/root` and `/private/var/root`. These calls always fail because
the `HostFilesAdapter` Python code runs inside the executor server process,
which runs as a **normal (non-root) user**, regardless of which profile is active.

---

## Observed failures

### `LIST_HOST_DIRECTORY /var/root`

The adapter calls `Path.iterdir()` on a directory the process cannot traverse.
`PermissionError` is raised inside `_list()`, bubbles up to `safe_execute()` in
`executor/adapters/base.py`, and is caught by the generic exception handler
there. The error returned to the caller is:

```
LIST_HOST_DIRECTORY is temporarily unavailable.
```

This message is **misleading**: it sounds like a transient system issue, not a
permission failure. Jarvis has no way to distinguish this from a real outage.

### `READ_HOST_FILE /var/root/intentframe_audit_note.txt`

The adapter calls `Path.exists()` before reading. On macOS, `Path.exists()`
returns `False` for a path the process cannot `stat()` through a permission
barrier, even if the file genuinely exists. The error returned is:

```
host_files: file not found: /private/var/root/intentframe_audit_note.txt
```

This message is **wrong**: the file exists but is unreadable. Jarvis sees "not
found" and may infer the file does not exist rather than that access was denied.

---

## Why the errors are misleading

`safe_execute()` in `executor/adapters/base.py` (lines 161–172) catches **all**
exceptions and returns a single generic message:

```python
except Exception as exc:
    ...
    return ExecutionResult(
        success=False,
        error=f"{action} is temporarily unavailable.",
    )
```

This is intentional for unhandled adapter crashes, but it also swallows
`PermissionError`, which is a meaningful, caller-relevant signal. The `_read`
method's "not found" result comes from `p.exists()` returning `False` under a
permission barrier — also not caught or classified as permission-denied.

Neither failure surface tells Jarvis the actual cause (privilege), so Jarvis
cannot make a correct routing decision in response.

---

## Scope of affected paths

The problem is not limited to `/var/root`. Any path the executor process cannot
access due to OS permissions will produce the same misleading errors. Examples
on macOS:

- `/var/root`, `/private/var/root` — root user's home directory (mode `750`)
- `/var/audit/` — audit logs, root-only
- `/var/db/dslocal/nodes/Default/users/*.plist` — local user account records
- `/var/db/sudo/` — sudo timestamp directory
- `/etc/sudoers`, `/etc/sudoers.d/` — mode `0440`, root-only
- `/etc/ssh/ssh_host_*_key` — host private SSH keys
- Other users' private directories under `/Users/<other>/`

SIP-protected paths (`/System`, `/usr` except `/usr/local`, `/bin`, `/sbin`)
are additionally blocked even for root, so neither the file adapter nor an
escalated shell command can write to them.

## What the executor config says vs. what actually happens

`jarvis_pa/executor_root.yaml` sets:

```yaml
host_files:
  allowed_read_paths:
    - /
  allowed_write_paths:
    - /
```

This is a **policy ceiling** for the `HostFilesAdapter`, not an OS privilege
grant. Setting `allowed_read_paths: [/]` means the policy layer does not
restrict the adapter to a subtree. The OS still enforces what the process can
actually read. The adapter is authorised by policy to attempt reads anywhere
under `/`, but the Python process is denied by the OS for paths it does not
have privilege to access.

The VFS mount `{"virtual_path": "/", "real_path": "/"}` in the root profile
tells the resource-registry and guardian how to normalise paths for policy
checks. It does not change the privilege of the executor server process.

---