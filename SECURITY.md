# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in IntentFrame, please report it
responsibly. **Do not open a public GitHub issue.**

Email: **intentframe@gmail.com**

Please include:

- A description of the vulnerability
- Steps to reproduce it
- The potential impact
- Any suggested fix (optional)

We will acknowledge receipt within 48 hours and aim to provide an initial
assessment within 7 days.

## Scope

IntentFrame is a security gateway for AI agents. Vulnerabilities in any of
the following are in scope:

- Policy bypass (Guardian, Analysis Engine, Executor)
- Command injection through the command shield
- Prompt injection that circumvents hardened system prompts
- Path traversal through the virtual filesystem
- Credential leakage from the vault
- Privilege escalation across user/workspace boundaries
- Authentication or authorization flaws in the gateway or executor
- Bypass of the root-demo escalation boundary: the narrow `NOPASSWD: SETENV: /usr/bin/sandbox-exec` sudoers entry installed by `intentframe_setup_root_demo.sh` is intentionally scoped to that one binary; anything that allows running arbitrary commands as root through this mechanism is in scope

## Out of Scope

- Vulnerabilities in third-party dependencies (report upstream)
- Issues that require physical access to the host machine
- Social engineering attacks against users

## Disclosure

We follow coordinated disclosure. We will work with you on a timeline and
credit you in the advisory unless you prefer to remain anonymous.
