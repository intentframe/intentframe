---
name: python-env
description: Python environment – python, pip, venv, uv
version: "1.0"
metadata:
  requires:
    anyBins: ["python3", "python"]
---

# Python Environment

Manage Python environments and packages.

## Common operations

- `python3 --version`
- `pip install <package>`, `pip list`
- `python3 -m venv .venv`, `source .venv/bin/activate`
- `uv pip install <package>` (if uv is available)

Always use `run_command` to execute Python commands.
