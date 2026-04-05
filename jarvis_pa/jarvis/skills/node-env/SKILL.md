---
name: node-env
description: Node.js environment – node, npm, npx, nvm
version: "1.0"
metadata:
  requires:
    anyBins: ["node", "npm"]
---

# Node.js Environment

Manage Node.js environments and packages.

## Common operations

- `node --version`, `npm --version`
- `npm install <package>`, `npm list`
- `npx <command>`
- `nvm use <version>`, `nvm install <version>`

Always use `run_command` to execute Node commands.
