# intentframe-runtime

The IntentFrame runtime substrate: a dependency-only meta-package that pulls in
the three services the supervisor spawns —
[`intentframe-policy-registry`](https://github.com/intentframe/intentframe),
[`intentframe-executor`](https://github.com/intentframe/intentframe), and
[`intentframe-server`](https://github.com/intentframe/intentframe).

Installing it makes `policy_registry.server:app`, `executor.server:app`, and
`intentframe_server.server:app` importable in one environment, so the supervisor
can launch the default three-process service graph. Each dependency carries its
own transitive deps (`intentframe-core`, `intentframe-components`,
`intentframe-prompt-library`, the SDKs, and `intentframe-executor-client`), so
this is the complete runnable substrate.

This package contains no source code. The resource-registry / native-kit
"flavour" is **not** part of the runtime — that lives at the supervisor layer
(e.g. `intentframe-supervisor[native]`).

```bash
pip install intentframe-runtime
```

PyPI: [intentframe-runtime](https://pypi.org/project/intentframe-runtime/) · `pip install intentframe-runtime==0.1.1` · License: AGPL-3.0 · [Consumer guide](../../docs/package-consumers.md)
