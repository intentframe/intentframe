---
name: github
description: GitHub CLI – issues, PRs, repos, actions
version: "1.0"
metadata:
  requires:
    bins: ["gh"]
    env: ["GITHUB_TOKEN"]
  os: ["darwin"]
---

# GitHub

Use the `gh` CLI to interact with GitHub repositories.

## Common operations

- `gh issue list`, `gh issue create`
- `gh pr list`, `gh pr create`, `gh pr merge`
- `gh repo clone`, `gh repo view`
- `gh run list`, `gh run view`

Always use `run_command` to execute `gh` commands.
