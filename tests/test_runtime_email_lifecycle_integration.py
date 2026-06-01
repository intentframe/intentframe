"""End-to-end runtime shutdown closes the registry-owned email client."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from intentframe_native_kit.action_registry.types import ActionType
from intentframe_bundle_sdk.registry import action_bundle_for
from intentframe_core.types import IntentFrame, UserContext
from intentframe_native_kit.intentframe_native_bundles.actions.email.bundle import EmailActionBundle
from intentframe_server.dry_run_executor import DryRunExecutor
from intentframe_server.pipeline import IntentFrameRuntime
from policy_registry.models import ActionPermission
from tests._bundle_loader import ensure_test_bundles_loaded
from tests._bundle_registry_snapshot import isolated_bundle_registry
from tests.test_runtime_lifecycle import _AllowAnalysis, _AllowGuardian


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
        reason="integration test",
        agent_id="test",
        data={"rfc_message_id": "<msg@example.com>", "body": "hi"},
    )


def _reply_user_context() -> UserContext:
    return UserContext(
        user_id="test",
        allowed_actions={"REPLY_EMAIL": ActionPermission(safe=False)},
    )


@pytest.mark.asyncio
async def test_runtime_shutdown_closes_registry_email_client(
    _isolated_registry,
) -> None:
    email_bundle = action_bundle_for("REPLY_EMAIL")
    assert isinstance(email_bundle, EmailActionBundle)

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

    with patch(
        "external_data_ingestion.email.client.EmailClient.create",
        new=AsyncMock(return_value=mock_client),
    ):
        await runtime.startup()
        await runtime.process_intent(_reply_intent(), _reply_user_context())
        await runtime.aclose()

    mock_client.close.assert_awaited_once()
    assert email_bundle._client is None
    assert email_bundle._closed is True


def test_isolated_registry_refreshes_email_after_close() -> None:
    ensure_test_bundles_loaded()
    with isolated_bundle_registry():
        email_bundle = action_bundle_for("REPLY_EMAIL")
        assert isinstance(email_bundle, EmailActionBundle)
        email_bundle._closed = True

    refreshed = action_bundle_for("REPLY_EMAIL")
    assert isinstance(refreshed, EmailActionBundle)
    assert refreshed is not email_bundle
    assert refreshed._closed is False
