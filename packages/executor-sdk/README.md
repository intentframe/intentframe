# intentframe-executor-sdk

Author **executor packs** and capability adapters for
[IntentFrame](https://github.com/intentframe/intentframe). Packs register
adapters, transports, auth verifiers, and services via the
`intentframe.executor_packs` entry-point group.

```bash
pip install intentframe-executor-sdk
```

Imports as `executor_sdk`. Depends on `intentframe-core` and
`intentframe-credentials` (credential vault interfaces). See the package's
in-tree `executor_sdk/README.md` for the pack/adapter contract.
