---
name: homebrew
description: Homebrew package manager – install, upgrade, search
version: "1.0"
metadata:
  requires:
    bins: ["brew"]
  os: ["darwin"]
---

# Homebrew

Use `brew` to manage macOS packages.

## Common operations

- `brew install <package>`
- `brew upgrade`, `brew upgrade <package>`
- `brew search <query>`
- `brew list`, `brew info <package>`
- `brew cleanup`

Always use `run_command` to execute brew commands.
