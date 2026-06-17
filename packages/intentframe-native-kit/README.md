# intentframe-native-kit

The first-party kit for [IntentFrame](https://github.com/intentframe/intentframe).
It bundles the reference implementations that ship out of the box:

- **action registry** — the canonical action catalog, categories, and domain schemas
- **native bundles** — the deterministic action/domain bundles (files, terminal, email, finance, deletion, …)
- **executor packs** — `console`, `posix`, and `macos` capability adapters
- **resource registry** — the deny-floor and resource model
- packaged service-graph profiles (`supervisor_profile.yaml`, `edge_profile.yaml`, `core.yaml`)

The executor packs and bundles register themselves through the
`intentframe.executor_packs` and `intentframe.bundles` entry-point groups, so
the executor service and bundle loader discover them automatically once this
package is installed. Built on `intentframe-bundle-sdk`,
`intentframe-executor-sdk`, and `command-shield`.

```bash
pip install intentframe-native-kit
```

PyPI: [intentframe-native-kit](https://pypi.org/project/intentframe-native-kit/) · `pip install intentframe-native-kit==0.1.0` · License: Apache-2.0 · [Consumer guide](../../docs/package-consumers.md)

## License

`intentframe-native-kit` is distributed under the Apache License 2.0.

## Email integration (optional)

Email bundles and macOS mail adapters call the product-side EDI `EmailClient` via
**lazy imports** — nothing email-related is imported at package install time.

- `email-sync-service` (`external_data_ingestion`) is **not** on PyPI and is **not**
  declared in this package’s dependencies.
- A normal `pip install intentframe-native-kit` is enough for all non-email actions.
- To use email actions, your deployment must also provide EDI (for example the
  in-repo `external_data_ingestion` tree used by the IntentFrame product). Without
  it, importing or running those code paths fails at **use time** with
  `ImportError`, not at install time.

See [docs/licensing.md](../../docs/licensing.md) for the publishable `packages/`
surface vs product-facing modules.
