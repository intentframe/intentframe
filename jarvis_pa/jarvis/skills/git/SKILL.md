---
name: git
description: Git operations – status, diff, commit, branch, merge
version: "1.0"
metadata:
  requires:
    bins: ["git"]
  os: ["darwin"]
---

# Git

Use `git` for version control operations.

## Common operations

- `git status`, `git diff`, `git log --oneline`
- `git add`, `git commit -m "..."`, `git push`
- `git branch`, `git checkout`, `git merge`
- `git stash`, `git stash pop`

Always use `run_command` to execute git commands.
