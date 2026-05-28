"""
Platform-specific implementations for the IntentFrame Executor.

Each platform (macOS, Linux, Windows, Cloud) provides concrete
implementations of the executor's abstract interfaces. Platforms
register their implementations into the executor's plugin registries
so the config-driven startup can instantiate the right components.

Usage:
    from intentframe_executor_pack_macos import register_all
    register_all()  # Registers all macOS implementations
"""
