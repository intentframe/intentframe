#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
    echo "Error: not inside a git repository." >&2
    exit 1
}

git config core.hooksPath "$REPO_ROOT/scripts/git-hooks"
echo "Git hooks path set to: scripts/git-hooks/"
echo "Pre-commit guard is now active — .vscode/, .idea/, .env, .aienv commits will be blocked."
