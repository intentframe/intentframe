"""Smoke tests that runtime shutdown does not leak fds or asyncio tasks."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest

from intentframe_native_kit.action_registry.types import ActionType
from intentframe_core.types import IntentFrame, UserContext
from intentframe_server.dry_run_executor import DryRunExecutor
from intentframe_server.pipeline import IntentFrameRuntime
from policy_registry.models import ActionPermission
from tests._bundle_loader import ensure_test_bundles_loaded
from tests._bundle_registry_snapshot import isolated_bundle_registry
from tests.test_runtime_lifecycle import _AllowAnalysis, _AllowGuardian


def _open_fd_count() -> int:
    return len(os.listdir("/dev/fd"))


def _background_tasks() -> set[asyncio.Task[object]]:
    current = asyncio.current_task()
    return {task for task in asyncio.all_tasks() if task is not current and not task.done()}


@pytest.fixture(autouse=True)
def _load_bundles() -> None:
    ensure_test_bundles_loaded()


@pytest.fixture
def _isolated_registry():
    with isolated_bundle_registry():
        yield


def _reply_intent() -> IntentFrame:
    return IntentFrame(
        action=ActionType.REPLY_EMAIL,
        target="",
        reason="leak smoke test",
        agent_id="test",
        data={"rfc_message_id": "<msg@example.com>", "body": "hi"},
    )


def _reply_user_context() -> UserContext:
    return UserContext(
        user_id="test",
        allowed_actions={"REPLY_EMAIL": ActionPermission(safe=False)},
    )


@pytest.mark.asyncio
async def test_runtime_shutdown_does_not_grow_fd_count(
    _isolated_registry,
) -> None:
    mock_client = AsyncMock()
    mock_client.get_email = AsyncMock(return_value=None)
    mock_client.close = AsyncMock()

    runtime = IntentFrameRuntime(
        analysis_engine=_AllowAnalysis(),
        guardian=_AllowGuardian(),
        executor=DryRunExecutor(),
        verbose=False,
    )
    runtime._resolve_user_context = lambda user_context: user_context

    fds_before = _open_fd_count()
    tasks_before = _background_tasks()

    with patch(
        "external_data_ingestion.email.client.EmailClient.create",
        new=AsyncMock(return_value=mock_client),
    ):
        await runtime.startup()
        await runtime.process_intent(_reply_intent(), _reply_user_context())
        await runtime.aclose()

    fds_after = _open_fd_count()
    tasks_after = _background_tasks()

    assert fds_after <= fds_before
    assert tasks_after <= tasks_before


@pytest.mark.asyncio
async def test_runtime_shutdown_does_not_grow_tasks_without_email_intent(
    _isolated_registry,
) -> None:
    runtime = IntentFrameRuntime(
        analysis_engine=_AllowAnalysis(),
        guardian=_AllowGuardian(),
        executor=DryRunExecutor(),
        verbose=False,
    )

    tasks_before = _background_tasks()
    await runtime.startup()
    await runtime.aclose()
    tasks_after = _background_tasks()

    assert tasks_after <= tasks_before
