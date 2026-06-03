# Changelog

All notable public changes to IntentFrame will be documented in this file.

This project follows semantic versioning where practical. While IntentFrame is in alpha, breaking changes may still occur between minor releases.

## [Unreleased]

### Added

- **`intentframe-runtime`** workspace package — dependency-only meta-package (`intentframe-policy-registry`, `intentframe-executor`, `intentframe-server`).
- **`intentframe-supervisor`** workspace package — supervisor code, default `supervisor.yaml`, console scripts `intentframe` / `intentframe-backend`; depends on `intentframe-runtime`; optional **`[native]`** extra pulls `intentframe-native-kit` (4-service kit profile is still selected via `--config` / `INTENTFRAME_SUPERVISOR_CONFIG`, not auto-detected).

### Changed

- Supervisor service graph: pipeline process renamed **`intentframe-core` → `intentframe-server`** (per-service log: `intentframe-server.log`; socket unchanged: `intentframe.sock`). The **`intentframe-core`** pip package / `intentframe_core` import name is unchanged (shared DTOs).
- Supervisor source moved to `packages/intentframe-supervisor/`; root `intentframe` depends on `intentframe-supervisor[native]`.
- Docs and deploy examples: kit YAML paths resolved from the installed `intentframe-native-kit` package (`KIT=…`); Docker defaults use `/app/packages/intentframe-native-kit/intentframe_native_kit/…`.

### Added (prior)

- Config-driven **intentframe-core** profiles: `core.yaml` selected by `INTENTFRAME_CORE_CONFIG` (`intentframe_server/config.py`, `intentframe_server/config/core.example.yaml`, first-party `intentframe_native_kit/core.yaml`).
- `intentframe.bundles` and `intentframe.executor_packs` **entry-point groups** in root `pyproject.toml` for short-name plugin discovery.
- Gateway helper `intentframe_gateway/profiles.py` (`resolve_core_config_path()`) so bootstrap and supervisor child env share one core-profile resolution (missing/empty env → kit default).
- Public doc [docs/plugin-profiles.md](docs/plugin-profiles.md) for bundles, packs, YAML profiles, and entry points.

### Changed

- **Core HTTP client** moved from `intentframe_server/client.py` to neutral package `intentframe_client/` (no re-exports on `intentframe_server`). Actor, dashboard, and demo tests import `intentframe_client` directly so `import intentframe_actor` does not load the pipeline.
- **intentframe-core** loads action bundles only from the active core profile; no hardcoded native-kit fallback in substrate (`DeterministicGuardian`, `intentframe_server/server.py`, `policy_registry/seeds/loader.py`).
- Removed **`INTENTFRAME_BUNDLES`** env shortcut (parity with executor — no pack-list env var).
- Policy seed validation takes explicit `bundle_packages` from the deployment's `core.yaml` (gateway bootstrap, `jarvis_pa/seed_policies.py`).
- Native action surface packaging: `intentframe_native_kit.action_registry`, `intentframe_native_kit.intentframe_native_bundles`,
  and `intentframe_executor_pack_*` now live under `intentframe_native_kit/`
  (import names unchanged). Demo `ExecutorBridge` moved to test helper
  `tests/_bridge.py`; executor pipeline coverage lives in
  `tests/test_executor.py`.

- Policy registry decoupling: constraint schemas, system terminal floors, and
  contact-based recipient resolution moved from `policy_registry/` into action
  bundles (`intentframe_native_kit/intentframe_native_bundles/actions/*/constraints.py`) and
  `intentframe_native_kit/intentframe_native_bundles/platform/contacts_client.py`. The registry stores
  opaque constraint dicts only; bundles enforce shape and runtime resolution.

### Added

- Public-release README updates: logo, demo CTA, TL;DR, quickstart, audience routing, support, and commercial contact paths.
- Support, citation, changelog, and funding metadata for public launch readiness.

## [0.1.0-alpha.2] - 2026-05-08

### Changed

- Updated README positioning and public documentation links.
- Improved public docs ahead of the alpha release.

## [0.1.0-alpha.1] - 2026-05-08

### Added

- Public alpha release of IntentFrame.
- Hybrid deterministic and LLM action-validation pipeline.
- Actor SDK for submitting structured intents from external agents.
- Deterministic executor with credential isolation, macOS Seatbelt sandboxing, and tamper-evident audit logging.
- `command_shield` shell-command analysis and capability tagging.
- Jarvis reference assistant with 55+ tools routed through IntentFrame.
- Telegram bridge for remote interaction with Jarvis through the same runtime boundary.
- Root-demo evidence package covering 100 malicious intents, 100 benign workflows, and 20 gray-area developer/admin cases.
- Public docs for architecture, autonomy, threat model, privacy, evidence, executor design, and quickstart.

### Known Limitations

- macOS on Apple Silicon only.
- Python 3.14+ required.
- No independent third-party audit yet.
- No PyPI or Homebrew install yet.
- Policy editing still requires source-level changes.
- Stateful multi-intent tracking is on the roadmap.

[Unreleased]: https://github.com/intentframe/intentframe/compare/v0.1.0-alpha.2...HEAD
[0.1.0-alpha.2]: https://github.com/intentframe/intentframe/releases/tag/v0.1.0-alpha.2
[0.1.0-alpha.1]: https://github.com/intentframe/intentframe/releases/tag/v0.1.0-alpha.1
