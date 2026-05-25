"""Bundle lifecycle hook contract and orchestration."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.lifecycle import shutdown_bundles, startup_bundles
from tests._bundle_loader import ensure_test_bundles_loaded

ensure_test_bundles_loaded()


def _fresh_bundle_instances() -> list[Any]:
    """Fresh instances for lifecycle tests — never mutate registry singletons."""
    from intentframe_native_bundles.actions.api.bundle import ApiActionBundle
    from intentframe_native_bundles.actions.browser.bundle import BrowserActionBundle
    from intentframe_native_bundles.actions.calendar.bundle import CalendarActionBundle
    from intentframe_native_bundles.actions.clipboard.bundle import ClipboardActionBundle
    from intentframe_native_bundles.actions.contacts.bundle import ContactsActionBundle
    from intentframe_native_bundles.actions.email.bundle import EmailActionBundle
    from intentframe_native_bundles.actions.files.bundle import FilesActionBundle
    from intentframe_native_bundles.actions.host_files.bundle import HostFilesActionBundle
    from intentframe_native_bundles.actions.message.bundle import MessageActionBundle
    from intentframe_native_bundles.actions.notes.bundle import NotesActionBundle
    from intentframe_native_bundles.actions.reminders.bundle import RemindersActionBundle
    from intentframe_native_bundles.actions.spotlight.bundle import SpotlightActionBundle
    from intentframe_native_bundles.actions.system.bundle import SystemActionBundle
    from intentframe_native_bundles.actions.terminal.bundle import TerminalActionBundle
    from intentframe_native_bundles.actions.user_io.bundle import UserIoActionBundle
    from intentframe_native_bundles.domains.deletion.bundle import DeletionDomainBundle
    from intentframe_native_bundles.domains.finance.bundle import FinanceDomainBundle

    return [
        TerminalActionBundle(),
        FilesActionBundle(),
        HostFilesActionBundle(),
        EmailActionBundle(),
        ApiActionBundle(),
        BrowserActionBundle(),
        MessageActionBundle(),
        CalendarActionBundle(),
        RemindersActionBundle(),
        NotesActionBundle(),
        ContactsActionBundle(),
        ClipboardActionBundle(),
        SpotlightActionBundle(),
        SystemActionBundle(),
        UserIoActionBundle(),
        FinanceDomainBundle(),
        DeletionDomainBundle(),
    ]


@pytest.fixture(autouse=True)
def _load_bundles() -> None:
    ensure_test_bundles_loaded()


def test_default_aclose_is_noop() -> None:
    class Minimal(ActionBundle):
        bundle_id = "minimal_lifecycle"
        action_ids = frozenset({"MINIMAL_LIFECYCLE_TEST"})

    bundle = Minimal()
    asyncio.run(bundle.aclose())


@pytest.mark.asyncio
async def test_shutdown_bundles_calls_aclose_on_every_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[str] = []

    class Tracking(ActionBundle):
        bundle_id = "tracking_lifecycle"
        action_ids = frozenset({"TRACKING_LIFECYCLE_TEST"})

        async def aclose(self) -> None:
            closed.append(self.bundle_id)

    tracking = Tracking()
    monkeypatch.setattr(
        "intentframe_bundle_sdk.lifecycle.all_action_bundles",
        lambda: (tracking,),
    )
    monkeypatch.setattr(
        "intentframe_bundle_sdk.lifecycle.all_domain_bundles",
        lambda: (),
    )
    await shutdown_bundles()
    assert closed == ["tracking_lifecycle"]


@pytest.mark.asyncio
async def test_aclose_failure_is_aggregated(monkeypatch: pytest.MonkeyPatch) -> None:
    class Good(ActionBundle):
        bundle_id = "good_lifecycle"
        action_ids = frozenset({"GOOD_LIFECYCLE_TEST"})

        async def aclose(self) -> None:
            self.closed = True

    class Bad(ActionBundle):
        bundle_id = "bad_lifecycle"
        action_ids = frozenset({"BAD_LIFECYCLE_TEST"})

        async def aclose(self) -> None:
            raise RuntimeError("boom")

    good = Good()
    bad = Bad()
    monkeypatch.setattr(
        "intentframe_bundle_sdk.lifecycle.all_action_bundles",
        lambda: (good, bad),
    )
    monkeypatch.setattr(
        "intentframe_bundle_sdk.lifecycle.all_domain_bundles",
        lambda: (),
    )

    with pytest.raises(BaseExceptionGroup) as exc_info:
        await shutdown_bundles()

    assert len(exc_info.value.exceptions) == 1
    assert getattr(good, "closed", False) is True


@pytest.mark.asyncio
async def test_aclose_timeout_is_aggregated(monkeypatch: pytest.MonkeyPatch) -> None:
    class Slow(ActionBundle):
        bundle_id = "slow_lifecycle"
        action_ids = frozenset({"SLOW_LIFECYCLE_TEST"})

        async def aclose(self) -> None:
            await asyncio.sleep(10)

    monkeypatch.setattr(
        "intentframe_bundle_sdk.lifecycle.all_action_bundles",
        lambda: (Slow(),),
    )
    monkeypatch.setattr(
        "intentframe_bundle_sdk.lifecycle.all_domain_bundles",
        lambda: (),
    )

    with pytest.raises(BaseExceptionGroup):
        await shutdown_bundles(timeout_s=0.01)


@pytest.mark.asyncio
async def test_aclose_is_idempotent() -> None:
    calls = {"count": 0}

    class Counting(ActionBundle):
        bundle_id = "counting_lifecycle"
        action_ids = frozenset({"COUNTING_LIFECYCLE_TEST"})

        async def aclose(self) -> None:
            calls["count"] += 1

    bundle = Counting()
    await bundle.aclose()
    await bundle.aclose()
    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_startup_bundles_runs_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[str] = []

    class Starting(ActionBundle):
        bundle_id = "starting_lifecycle"
        action_ids = frozenset({"STARTING_LIFECYCLE_TEST"})

        async def startup(self) -> None:
            started.append(self.bundle_id)

    monkeypatch.setattr(
        "intentframe_bundle_sdk.lifecycle.all_action_bundles",
        lambda: (Starting(),),
    )
    monkeypatch.setattr(
        "intentframe_bundle_sdk.lifecycle.all_domain_bundles",
        lambda: (),
    )
    await startup_bundles()
    assert started == ["starting_lifecycle"]


@pytest.mark.parametrize(
    "bundle",
    _fresh_bundle_instances(),
    ids=lambda b: b.bundle_id,
)
@pytest.mark.asyncio
async def test_registered_bundle_aclose_is_idempotent(bundle) -> None:
    await bundle.aclose()
    await bundle.aclose()
