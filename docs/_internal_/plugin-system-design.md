# Plugin System Design & Shared Code Mechanics

This document captures the architectural decisions and mechanics of the IntentFrame plugin system, specifically addressing how shared code is handled, how the SDK loads plugins, and how the system supports third-party extensions.

## 1. Shared Code in Plugin Systems

A common misconception is that if plugins run in a single process, they can safely import each other's internal modules. 

### Why Cross-Plugin Imports are Harmful
Even in a single-process architecture, allowing Plugin A to import Plugin B's internals creates tight coupling. Plugin A accidentally becomes part of Plugin B's API surface. If Plugin B is removed, refactored, or replaced by a third-party alternative, Plugin A breaks.

### Standard Patterns for Shared Code
Good plugin systems handle shared code using one of three patterns:
1. **Shared SDK / Core Library:** Common types and helpers live in a neutral, versioned package that all plugins depend on.
2. **Service Registry / Extension Points:** Plugin B registers a named service (e.g., `"file-intel-builder"`); Plugin A asks the host for it. Coupling is through an interface, not a Python path.
3. **Event Bus:** Plugins emit and listen to named events.

### Our Approach: Neutral Shared Libraries
In IntentFrame, we use the **Shared Library** pattern for first-party code. 
Instead of duplicating code or allowing `actions/host_files` to import from `actions/files`, we extract shared logic (like `FileIntel` and payload inspection) into a neutral `shared/files/` directory.
- **Rule:** Bundles (`actions/*`) may import from `shared/*`.
- **Rule:** Shared code (`shared/*`) must never import from `actions/*`.
- **Rule:** Bundles must never import from sibling bundles.

This ensures that any bundle can be removed or replaced without breaking others, and third-party plugins can safely depend on the shared library.

## 2. The "Same Author" Fallacy

When building a first-party plugin ecosystem, it is tempting to assume that all plugins are written by the same author and can therefore safely bypass boundaries. 

However, designing for third-party isolation from day one is critical because:
- It prevents a "slow-motion behavior fork" where duplicated code diverges.
- It preserves the ability to unbundle or swap plugins later.
- It forces the core SDK contract to remain honest and complete.

## 3. How the IntentFrame SDK Loads Plugins

The IntentFrame Bundle SDK is a **contract**, not a magic discovery mechanism. 

### The Loading Mechanism
The SDK does not scan directories for classes marked as SDK components. Instead, it loads **Python packages** via an explicit entry point:

1. The host calls `ensure_loaded(["intentframe_native_kit.intentframe_native_bundles", "acme_custom_bundle"])`.
2. The loader imports the package (`importlib.import_module`).
3. The loader looks for a top-level `register_bundles(registry)` function in the package.
4. The package's function instantiates its bundles and registers them (`registry.register_action_bundle(...)`).

### Memory and Process Model
- **Single Process:** All bundles run in one Python process, in the same event loop, sharing the same registry globals and `sys.modules`.
- **Eager Loading:** Bundles are loaded unconditionally at boot, regardless of the active policy. Heavyweight I/O (like opening database connections) is deferred to the `startup()` lifecycle hook.
- **No Sandboxing (Yet):** Because plugins share the Python heap, a malicious plugin could theoretically mutate globals. True untrusted third-party execution requires a future out-of-process architecture (e.g., UDS/subprocess).

## 4. Third-Party Plugin Lifecycle

If a third-party developer wants to use IntentFrame in their agentic app, the flow looks like this:

1. **Authoring:** The developer creates a Python package (e.g., `acme_slack_plugin`) containing classes that inherit from `ActionBundle` or `DomainBundle`.
2. **Registration:** They expose a `register_bundles` function in their package's `__init__.py`.
3. **Loading:** The host processor boots up and calls `ensure_loaded(["intentframe_native_kit.intentframe_native_bundles", "acme_slack_plugin"])`.
4. **Validation:** The SDK validates that no two packages register the same `action_id` or `domain_id`. It then validates the user's policy against the registered constraint schemas.
5. **Execution:** When the agent submits an intent, the SDK deterministically routes it to the registered bundle for that `action_id`, enforcing the fixed runner order (`prepare_evidence` → `enrich` → `enforce_constraints` → `structural_gates` → `allow_gates` → `build_ai_context`).

### Is this overengineered?
No. For a robust plugin platform, this is the minimum useful architecture. Features like duplicate action rejection, policy validation before serving traffic, fixed lifecycle ordering, and hook timeouts (fail-closed behavior) are essential to ensure that intent processing is safe and predictable once loading passes.

## 5. Enforcing Boundaries

- **First-Party Enforcement:** We enforce import boundaries statically in CI (`tests/test_boundary_imports.py`). This guarantees that our native bundles adhere to the strict layering rules.
- **Third-Party Enforcement:** The SDK does not police a third-party package's internal `import` graph at runtime (which is standard for Python plugin systems). Third parties are expected to respect the public API boundaries. If stronger enforcement is needed in the future, it would be implemented as a static CLI validator tool (e.g., `intentframe plugin validate acme_plugin`) rather than a runtime boot check.