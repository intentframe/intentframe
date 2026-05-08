---
name: Security boundary concern
about: Report a suspected policy bypass, unsafe execution path, or security architecture question
title: "[Security Boundary]: "
labels: security
assignees: ''
---

> **Important:** If you believe this is an exploitable vulnerability, please follow the responsible disclosure process in [SECURITY.md](../../SECURITY.md) instead of opening a public issue.

## Summary

<!-- Briefly describe what boundary you think failed or what architectural concern you have. -->

## Which boundary do you think is affected?

- [ ] Agent bypassed the Actor SDK (called system directly)
- [ ] Deterministic gate missed a dangerous command or action
- [ ] Guardian allowed an intent it should have blocked
- [ ] Executor ran something outside policy
- [ ] Credential exposed to agent or LLM context
- [ ] Audit / logging issue
- [ ] Architectural concern (not a specific failure)
- [ ] Other

## Minimal reproduction

<!-- Minimal intent, command, or scenario that triggers the issue. Do not include real credentials. -->

```python
# paste code or intent fixture here
```

## Expected decision

<!-- ALLOW / BLOCK / NEEDS_REVIEW — and why you expected that -->

## Actual decision

<!-- What did IntentFrame actually do? -->

## Logs or evidence

<!-- Paste relevant pipeline output or audit log entries. Redact anything sensitive. -->

## Notes

<!-- Any additional context, related docs, or prior discussion. -->
