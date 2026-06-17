# intentframe-executor-sdk

Author **executor packs** and capability adapters for
[IntentFrame](https://github.com/intentframe/intentframe). Packs register
adapters, transports, auth verifiers, and services via the
`intentframe.executor_packs` entry-point group.

```bash
pip install intentframe-executor-sdk
```

PyPI: [intentframe-executor-sdk](https://pypi.org/project/intentframe-executor-sdk/) · `pip install intentframe-executor-sdk==0.1.0` · License: Apache-2.0 · [Consumer guide](../../docs/package-consumers.md)

Imports as `executor_sdk`. Depends on `intentframe-core` and
`intentframe-credentials` (credential vault interfaces). See the package's
in-tree `executor_sdk/README.md` for the pack/adapter contract.
