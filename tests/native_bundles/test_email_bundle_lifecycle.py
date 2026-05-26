"""EmailActionBundle resource ownership and lifecycle."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from action_registry.types import ActionType
from intentframe_bundle_sdk.types import ActionPermission, BundleContext
from intentframe_core.types import IntentFrame
from intentframe_native_bundles.actions.email.bundle import EmailActionBundle

_NO_PERM = ActionPermission(safe=True)


def _reply_intent(message_id: str = "<test@example.com>") -> IntentFrame:
    return IntentFrame(
        action=ActionType.REPLY_EMAIL,
        target="",
        reason="test",
        agent_id="test",
        data={"rfc_message_id": message_id, "body": "hi"},
    )


@pytest.mark.asyncio
async def test_aclose_without_enrich_is_noop() -> None:
    bundle = EmailActionBundle()
    await bundle.aclose()
    assert bundle._client is None


@pytest.mark.asyncio
async def test_aclose_closes_client_after_enrich() -> None:
    mock_client = AsyncMock()
    mock_client.close = AsyncMock()

    with patch(
        "external_data_ingestion.email.client.EmailClient.create",
        new=AsyncMock(return_value=mock_client),
    ):
        bundle = EmailActionBundle()
        ctx = BundleContext(intent=_reply_intent())
        await bundle.enrich(_reply_intent(), _NO_PERM, ctx)
        await bundle.aclose()

    mock_client.close.assert_awaited_once()
    assert bundle._client is None


@pytest.mark.asyncio
async def test_aclose_is_idempotent() -> None:
    mock_client = AsyncMock()
    mock_client.close = AsyncMock()

    with patch(
        "external_data_ingestion.email.client.EmailClient.create",
        new=AsyncMock(return_value=mock_client),
    ):
        bundle = EmailActionBundle()
        ctx = BundleContext(intent=_reply_intent())
        await bundle.enrich(_reply_intent(), _NO_PERM, ctx)
        await bundle.aclose()
        await bundle.aclose()

    mock_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_concurrent_enrich_shares_one_client() -> None:
    create_calls = {"count": 0}

    async def _create() -> Any:
        create_calls["count"] += 1
        client = AsyncMock()
        client.get_email = AsyncMock(return_value=None)
        return client

    with patch(
        "external_data_ingestion.email.client.EmailClient.create",
        side_effect=_create,
    ):
        bundle = EmailActionBundle()
        intents = [_reply_intent(f"<msg{i}@example.com>") for i in range(5)]
        await asyncio.gather(
            *(
                bundle.enrich(
                    intent,
                    _NO_PERM,
                    BundleContext(intent=intent),
                )
                for intent in intents
            )
        )

    assert create_calls["count"] == 1


@pytest.mark.asyncio
async def test_enrich_after_aclose_raises() -> None:
    mock_client = AsyncMock()
    mock_client.close = AsyncMock()
    mock_client.get_email = AsyncMock(return_value=None)

    with patch(
        "external_data_ingestion.email.client.EmailClient.create",
        new=AsyncMock(return_value=mock_client),
    ):
        bundle = EmailActionBundle()
        intent = _reply_intent()
        ctx = BundleContext(intent=intent)
        await bundle.enrich(intent, _NO_PERM, ctx)
        await bundle.aclose()

        with pytest.raises(RuntimeError, match="closed"):
            await bundle.enrich(intent, _NO_PERM, ctx)
