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
