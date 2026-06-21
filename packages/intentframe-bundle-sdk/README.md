# intentframe-bundle-sdk

Author action and domain **bundles** for
[IntentFrame](https://github.com/intentframe/intentframe). Bundles plug into
the deterministic + semantic policy pipeline via the `intentframe.bundles`
entry-point group.

```bash
pip install intentframe-bundle-sdk
```

PyPI: [intentframe-bundle-sdk](https://pypi.org/project/intentframe-bundle-sdk/) · `pip install intentframe-bundle-sdk==0.1.1` · License: Apache-2.0 · [Consumer guide](../../docs/package-consumers.md)

This SDK pulls in only the foundation (`intentframe-core`,
`intentframe-policy-registry`) — not the runtime server, executor, or native
kit. See the package's in-tree `intentframe_bundle_sdk/README.md` for the full
bundle contract.
