# Changelog

All notable public changes to IntentFrame will be documented in this file.

This project follows semantic versioning where practical. While IntentFrame is in alpha, breaking changes may still occur between minor releases.

## [Unreleased]

### Changed

- Native action surface packaging: `intentframe_native_kit.action_registry`, `intentframe_native_kit.intentframe_native_bundles`,
  and `intentframe_executor_pack_*` now live under `intentframe_native_kit/`
  (import names unchanged; demo `ExecutorBridge` lives in
  `intentframe_native_kit/extras/bridge.py` only).

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
