# intentframe-bundle-sdk

Author action and domain **bundles** for
[IntentFrame](https://github.com/intentframe/intentframe). Bundles plug into
the deterministic + semantic policy pipeline via the `intentframe.bundles`
entry-point group.

```bash
pip install intentframe-bundle-sdk
```

This SDK pulls in only the foundation (`intentframe-core`,
`intentframe-policy-registry`) — not the runtime server, executor, or native
kit. See the package's in-tree `intentframe_bundle_sdk/README.md` for the full
bundle contract.
