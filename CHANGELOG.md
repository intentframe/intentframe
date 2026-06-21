# Changelog

All notable public changes to IntentFrame will be documented in this file.

IntentFrame follows semantic versioning where practical. During early `0.x` releases, breaking changes may still occur between minor releases.

## [0.1.1] - 2026-06-21

### Added

- CI: **Mac Tests** workflow (`mac-tests.yml`) — full root `tests/` plus `command-shield` on `macos-14`, with executor sandbox venv provisioning for fresh runners.
- CI: **Linux Tests** workflow (`linux-tests.yml`) — portable root subset (skips macOS sandbox/TCC/action-matrix tests) plus `command-shield` and `intentframe-credentials` package tests on `ubuntu-latest`.
- README badges for Mac Tests and Linux Tests.
- **`intentframe-server`**: configurable Guardian HMAC signing via `core.yaml` `executor.hmac_key` and `INTENTFRAME_EXECUTOR_HMAC_KEY` env override (must match executor `auth.options.secret_key`).

### Changed

- **`command-shield`**: ShellCheck findings are advisory command intel only; they no longer promote verdicts to `NEEDS_REVIEW`. Fixes non-deterministic classification when the optional `shellcheck` binary is present on PATH (common on Linux CI, uncommon on macOS dev machines).
- Documentation: PyPI is the primary install path for all 18 `packages/` distributions; GitHub release wheels documented as optional mirror ([`docs/package-consumers.md`](docs/package-consumers.md)).
- All **18** packages republished to [PyPI](https://pypi.org/) at **`0.1.1`**.

## [0.1.0] - 2026-06-04

### Added

- First package-oriented IntentFrame release: 18 lockstep-versioned Python distributions under `packages/`.
- **`intentframe-runtime`** workspace package — dependency-only meta-package (`intentframe-policy-registry`, `intentframe-executor`, `intentframe-server`).
- **`intentframe-supervisor`** workspace package — supervisor code, default `supervisor.yaml`, console scripts `intentframe` / `intentframe-backend`; depends on `intentframe-runtime`; optional **`[native]`** extra pulls `intentframe-native-kit` (4-service kit profile is still selected via `--config` / `INTENTFRAME_SUPERVISOR_CONFIG`, not auto-detected).
- Config-driven core, supervisor, edge, bundle, and executor-pack profiles.
- First-party native kit packaging for native bundles, executor packs, resource registry wiring, and profile YAML files.
- GitHub release wheel install path for third-party `uv` projects (URL-pinned fallback; PyPI is primary for `0.1.0`).
- All **18** packages published to [PyPI](https://pypi.org/) at **`0.1.0`**.
- Package-level AGPL/Apache licensing split, documented in [`docs/licensing.md`](docs/licensing.md).

### Changed

- Supervisor service graph: pipeline process renamed **`intentframe-core` → `intentframe-server`** (per-service log: `intentframe-server.log`; socket unchanged: `intentframe.sock`). The **`intentframe-core`** pip package / `intentframe_core` import name is unchanged (shared DTOs).
- Supervisor source moved to `packages/intentframe-supervisor/`; root `intentframe` depends on `intentframe-supervisor[native]`.
- Docs and deploy examples: kit YAML paths resolved from the installed `intentframe-native-kit` package (`KIT=…`); Docker defaults use `/app/packages/intentframe-native-kit/intentframe_native_kit/…`.
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

### Current limitations

- Full native assistant stack still targets macOS on Apple Silicon.
- Python 3.14+ is expected for the package set.
- No independent third-party security audit yet.
- Stateful cumulative-abuse detection remains roadmap work.

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
- No Homebrew install for the full product yet. SDK/runtime packages install from PyPI (`docs/package-consumers.md`); Jarvis and the gateway still require a repo clone.
- Policy editing still requires source-level changes.
- Stateful multi-intent tracking is on the roadmap.

[Unreleased]: https://github.com/intentframe/intentframe/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/intentframe/intentframe/releases/tag/v0.1.1
[0.1.0]: https://github.com/intentframe/intentframe/releases/tag/v0.1.0
[0.1.0-alpha.2]: https://github.com/intentframe/intentframe/releases/tag/v0.1.0-alpha.2
[0.1.0-alpha.1]: https://github.com/intentframe/intentframe/releases/tag/v0.1.0-alpha.1
