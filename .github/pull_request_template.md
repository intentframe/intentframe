## Summary

<!-- What changed and why? Link to any related issue. -->

## Type of change

- [ ] Bug fix
- [ ] Feature
- [ ] Security hardening
- [ ] Documentation
- [ ] Test coverage
- [ ] Refactor / cleanup

## Security impact

Does this change affect any of the following?

- [ ] Policy enforcement (Guardian, deterministic gates, command_shield)
- [ ] Executor or sandboxing behaviour
- [ ] Credential handling
- [ ] Audit logging or hash chain
- [ ] AI review layers (Analysis Engine, Guardian prompts)
- [ ] Actor SDK contract

If yes, describe the impact and how it was tested:

## Test plan

<!-- Commands run to verify the change. -->

```bash
# paste commands here
```

## Checklist

- [ ] No secrets, tokens, private keys, or local-only paths committed
- [ ] Docs updated if behaviour changed
- [ ] Package metadata and `docs/licensing.md` updated if distribution boundaries or licenses changed
- [ ] Tests added or updated where appropriate
- [ ] Fail-closed behaviour preserved — a failure in this code should not allow an unsafe action through
