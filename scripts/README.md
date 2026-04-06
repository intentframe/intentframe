# scripts/

Utility scripts for local development setup.

## Git Hooks

The `git-hooks/` directory contains shared git hooks that are tracked in the repository. These enforce code hygiene rules locally, before anything reaches CI.

### Setup (run once per clone)

```bash
bash scripts/install-hooks.sh
```

This runs `git config core.hooksPath scripts/git-hooks`, pointing git at the shared hooks directory instead of the default `.git/hooks/`.

### What the hooks do

| Hook | What it blocks |
|---|---|
| `pre-commit` | Commits containing `.vscode/`, `.idea/`, `.env`, `.aienv` |

The same checks are enforced server-side by the `Repo Hygiene` CI workflow (`.github/workflows/repo-hygiene.yml`), which acts as a backstop if local hooks are bypassed.
