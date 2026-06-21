# intentframe-core

Foundation layer for [IntentFrame](https://github.com/intentframe/intentframe):
neutral data types (`IntentFrame`, `ExecutionResult`, `RuntimeContext`),
enums, virtual-path helpers, policy contract models, and the `Executor` ABC.

This is an internal base package. Most users install a higher-level
distribution (`intentframe-actor`, `intentframe-bundle-sdk`,
`intentframe-executor-sdk`, or the `intentframe` runtime) which depends on
this package transitively.

```bash
pip install intentframe-core
```

PyPI: [intentframe-core](https://pypi.org/project/intentframe-core/) · `pip install intentframe-core==0.1.1` · License: Apache-2.0 · [Consumer guide](../../docs/package-consumers.md)
