"""
IntentFrame Executor -- config-driven entry point.

This is the main entry point for the executor service. It:
    1. Loads and validates configuration from executor.yaml
    2. Instantiates all components from config (transport, auth, adapters, services)
    3. Wires everything into the ExecutorGateway
    4. Starts the transport server with the gateway as the request handler
    5. Runs until interrupted (SIGINT/SIGTERM)

Usage:
    python -m executor.main
    python -m executor.main --config /path/to/executor.yaml
    python -m executor.main --config /path/to/executor.yaml --log-level DEBUG

The entry point is deliberately thin. All logic lives in the gateway,
services, and adapters. This file is pure wiring.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from typing import Any

from executor_sdk.adapters import create_adapter
from executor_sdk.auth import create_auth_verifier
from executor.config import ExecutorConfig, load_config
from executor.dispatch import ActionDispatcher
from executor_sdk.exceptions import ConfigurationError, ExecutorError
from executor.gateway import ExecutorGateway
from executor_sdk.services.audit_logger import create_audit_logger
from executor_sdk.services.credential_scrubber import CredentialScrubber
from executor_sdk.services.credential_vault import create_credential_vault
from executor_sdk.services.hash_chain import HashChain
from executor_sdk.services.state_store import create_state_store
from executor_sdk.transport import create_transport
from executor.worker_pool import WorkerPool

logger = logging.getLogger("executor")

__all__ = ["build_gateway", "run"]


# ═══════════════════════════════════════════════════════════════════════════════
# Component Assembly
# ═══════════════════════════════════════════════════════════════════════════════


def build_gateway(
    config: ExecutorConfig,
    service_overrides: dict[str, Any] | None = None,
) -> tuple[ExecutorGateway, Any, Any]:
    """Assemble all executor components from configuration.

    Creates and wires: auth verifier, dispatcher (with adapters),
    worker pool, and all services into an ExecutorGateway.

    Args:
        config: Validated executor configuration.
        service_overrides: Optional dict of service instances to inject
                           instead of creating from config. Keys are service
                           names: "audit_logger", "credential_vault",
                           "state_store". Useful for testing.

    Returns:
        Tuple of (gateway, transport_server, credential_vault) for the
        caller to manage lifecycle.

    Raises:
        ConfigurationError: If any component cannot be instantiated.
    """
    overrides = service_overrides or {}

    # ── Auth Verifier ─────────────────────────────────────────────────────
    auth_verifier = create_auth_verifier(config.auth)
    logger.info("Auth verifier: type=%s", config.auth.type)

    # ── Credential Vault ──────────────────────────────────────────────────
    credential_vault = overrides.get("credential_vault") or create_credential_vault(
        config.credentials
    )
    logger.info("Credential vault: backend=%s", config.credentials.backend)

    # ── Audit Logger ──────────────────────────────────────────────────────
    audit_logger = overrides.get("audit_logger") or create_audit_logger(config.storage)
    logger.info("Audit logger: backend=%s", config.storage.audit_backend)

    # ── State Store ───────────────────────────────────────────────────────
    state_store = overrides.get("state_store") or create_state_store(config.storage)
    logger.info("State store: backend=%s", config.storage.state_backend)

    # ── Concrete Services (platform-agnostic) ─────────────────────────────
    scrubber = CredentialScrubber()
    hash_chain = HashChain()

    # ── Worker Pool ───────────────────────────────────────────────────────
    worker_pool = WorkerPool(
        max_workers=config.worker_pool.max_workers,
        default_timeout=config.worker_pool.default_timeout_seconds,
    )
    logger.info(
        "Worker pool: max_workers=%d timeout=%.1fs",
        config.worker_pool.max_workers,
        config.worker_pool.default_timeout_seconds,
    )

    # ── Adapters ──────────────────────────────────────────────────────────
    # All possible adapter dependencies -- each adapter takes what it needs.
    # VFS mount resolution is owned by the files adapter via pack_options.files.
    adapter_deps: dict[str, Any] = {
        "credential_vault": credential_vault,
        "pack_options": config.pack_options,
    }

    dispatcher = ActionDispatcher()
    for adapter_id in config.adapters.enabled:
        try:
            adapter = create_adapter(adapter_id, **adapter_deps)
            dispatcher.register(adapter)
        except Exception as exc:
            raise ConfigurationError(
                f"Failed to create adapter '{adapter_id}': {exc}",
                details={"adapter_id": adapter_id},
            ) from exc

    logger.info(
        "Adapters loaded: %d adapters, %d actions",
        len(dispatcher.registered_adapters),
        len(dispatcher.registered_actions),
    )

    # ── Transport ─────────────────────────────────────────────────────────
    transport = create_transport(config.transport)
    logger.info("Transport: type=%s", config.transport.type)

    # ── Assemble Gateway ──────────────────────────────────────────────────
    gateway = ExecutorGateway(
        auth_verifier=auth_verifier,
        dispatcher=dispatcher,
        worker_pool=worker_pool,
        audit_logger=audit_logger,
        credential_vault=credential_vault,
        state_store=state_store,
        scrubber=scrubber,
        hash_chain=hash_chain,
    )

    return gateway, transport, worker_pool


# ═══════════════════════════════════════════════════════════════════════════════
# Logging Setup
# ═══════════════════════════════════════════════════════════════════════════════


def _setup_logging(level: str, fmt: str) -> None:
    """Configure logging based on executor config."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    if fmt == "json":
        # Structured JSON logging (production)
        handler = logging.StreamHandler(sys.stderr)
        formatter = logging.Formatter(
            '{"timestamp":"%(asctime)s","level":"%(levelname)s",'
            '"logger":"%(name)s","message":"%(message)s"}'
        )
        handler.setFormatter(formatter)
    else:
        # Human-readable console logging (development)
        handler = logging.StreamHandler(sys.stderr)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(formatter)

    root = logging.getLogger("executor")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)


# ═══════════════════════════════════════════════════════════════════════════════
# Entry Point
# ═══════════════════════════════════════════════════════════════════════════════


async def run(config: ExecutorConfig) -> None:
    """Start the executor service and run until interrupted.

    Args:
        config: Validated executor configuration.
    """
    _setup_logging(config.logging.level, config.logging.format)

    logger.info("IntentFrame Executor starting...")
    logger.info("Config: transport=%s auth=%s", config.transport.type, config.auth.type)

    if sys.platform == "darwin":
        try:
            from intentframe_executor_pack_macos.permissions import check_permissions
            check_permissions(config.adapters.enabled)
        except Exception as exc:
            logger.warning("Platform server permission check failed: %s", exc)

    gateway, transport, worker_pool = build_gateway(config)

    # Handle shutdown signals
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    # Start transport (runs until shutdown)
    logger.info("Executor ready. Listening for requests...")

    transport_task = asyncio.create_task(transport.start(gateway.handle))
    shutdown_task = asyncio.create_task(shutdown_event.wait())

    # Wait for either transport to finish or shutdown signal
    done, pending = await asyncio.wait(
        {transport_task, shutdown_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    # Graceful shutdown
    logger.info("Shutting down...")

    await transport.stop()
    await worker_pool.shutdown()
    gateway.close()

    for task in pending:
        task.cancel()

    logger.info("IntentFrame Executor stopped.")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="IntentFrame Executor -- Protocol-Driven Capability Service",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to executor.yaml configuration file",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=None,
        help="Override log level (DEBUG, INFO, WARNING, ERROR)",
    )

    args = parser.parse_args()

    try:
        config = load_config(config_path=args.config)
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    # CLI overrides
    if args.log_level:
        config.logging.level = args.log_level

    try:
        asyncio.run(run(config))
    except ExecutorError as exc:
        print(f"Executor error: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
