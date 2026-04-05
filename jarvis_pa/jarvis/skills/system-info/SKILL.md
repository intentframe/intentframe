---
name: system-info
description: System diagnostics – profiler, versions, disk, processes
version: "1.0"
metadata:
  requires:
    bins: ["sw_vers"]
  os: ["darwin"]
  always: true
---

# System Info

Use macOS CLI tools for system diagnostics.

## Common commands

- `sw_vers` – macOS version
- `system_profiler SPHardwareDataType` – hardware info
- `df -h` – disk usage
- `top -l 1 -n 5` – top processes
- `vm_stat` – memory pressure
- `sysctl -n hw.memsize` – total RAM

Always use `run_command` to execute these commands.
