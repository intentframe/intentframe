"""Shared fixtures for email sync integration tests.

Email addresses are loaded from test_config.yaml (same directory).
Passwords come from the credential vault (must be running).

    uv run python -m intentframe_credentials.dev_server &
    uv run pytest external_data_ingestion/tests/test_integration.py -v -s

The test suite sets INTENTFRAME_EMAIL_HOME to a temp directory so that
load_config() / EmailClient() / SyncDaemon resolve everything from
the same workspace — exactly as they do in production.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import yaml

from intentframe_credentials.client import VaultClientSync

TEST_TAG = f"emailsync_{uuid.uuid4().hex[:8]}"
CLEANUP_SUBJECT_PREFIX = f"[{TEST_TAG}]"

_TEST_CONFIG_PATH = Path(__file__).parent / "test_config.yaml"


def _load_test_config() -> dict[str, str]:
    """Read email from the YAML file next to this conftest."""
    if not _TEST_CONFIG_PATH.exists():
        return {}
    raw = yaml.safe_load(_TEST_CONFIG_PATH.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def pytest_addoption(parser: Any) -> None:
    parser.addoption("--email", default=None, help="Test email address (overrides test_config.yaml)")


@pytest.fixture(scope="session")
def email_address(request: Any) -> str:
    addr = request.config.getoption("--email") or _load_test_config().get("email")
    if not addr:
        pytest.skip(
            "No test email configured. "
            "Copy test_config_example.yaml → test_config.yaml and fill in your email, "
            "or pass --email <address>."
        )
    return addr


@pytest.fixture(scope="session")
def email_password(email_address: str) -> str:
    """Fetch the test account password from the credential vault."""
    vault = VaultClientSync()
    pw = vault.get(f"email.{email_address}", "password")
    if not pw:
        pytest.skip(
            f"No vault password for {email_address}. "
            f"Start the dev vault (uv run python -m intentframe_credentials.dev_server) "
            f"and seed it with: vault set email.{email_address} password <app-password>"
        )
    return pw


@pytest.fixture(scope="session")
def test_tag() -> str:
    return TEST_TAG


@pytest.fixture(scope="session")
def subject_prefix() -> str:
    return CLEANUP_SUBJECT_PREFIX


@pytest.fixture(scope="session")
def tmp_workspace(tmp_path_factory: Any) -> Path:
    return tmp_path_factory.mktemp("email_sync_test")


@pytest.fixture(scope="session", autouse=True)
def email_home(tmp_workspace: Path, email_address: str, email_password: str):
    """Point the entire email service at a temp workspace via env var.

    Writes a config.yaml into the temp dir with email only (no password)
    and sets INTENTFRAME_EMAIL_HOME so that load_config() picks it up.
    Password is fetched from the vault at config-load time.
    """
    cfg = tmp_workspace / "config.yaml"
    cfg.write_text(
        yaml.dump(
            {
                "accounts": [
                    {
                        "email": email_address,
                        "display_name": "Integration Test",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    old = os.environ.get("INTENTFRAME_EMAIL_HOME")
    os.environ["INTENTFRAME_EMAIL_HOME"] = str(tmp_workspace)
    yield tmp_workspace
    if old is None:
        del os.environ["INTENTFRAME_EMAIL_HOME"]
    else:
        os.environ["INTENTFRAME_EMAIL_HOME"] = old


@pytest_asyncio.fixture(scope="session")
async def service_config(email_home):
    from external_data_ingestion.email.config import load_config_async

    return await load_config_async()


@pytest_asyncio.fixture(scope="session")
async def db(service_config):
    from external_data_ingestion.email.db import init_db

    conn = await init_db(service_config.db_path)
    yield conn
    await conn.close()


@pytest.fixture(scope="session")
def account(service_config):
    return service_config.accounts[0]


@pytest_asyncio.fixture(scope="session")
async def discovered_folders(account):
    """Discover IMAP folders once per session to avoid redundant connections."""
    from external_data_ingestion.email.folders import discover_folders
    from external_data_ingestion.email.imap_connection import get_provider

    provider = get_provider(account)
    async with provider.connection() as mb:
        folders = await discover_folders(mb)
    return folders


@pytest.fixture(scope="session")
def attachments_dir(service_config) -> Path:
    d = service_config.attachments_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest_asyncio.fixture(scope="session")
async def client(email_home, db):
    from external_data_ingestion.email.client import EmailClient

    c = await EmailClient.create()
    yield c
    await c.close()


# ── Remote + local cleanup (runs once at session end) ────────────

def _imap_purge_test_emails(email_addr: str, password: str, prefix: str) -> int:
    """Delete every message on the remote server whose subject contains *prefix*."""
    from imap_tools import AND, MailBox

    from external_data_ingestion.email.providers import resolve_provider

    provider = resolve_provider(email_addr)
    deleted = 0
    with MailBox(provider.imap_host, provider.imap_port).login(
        email_addr, password, initial_folder=None
    ) as mb:
        for folder_info in mb.folder.list():
            if "\\Noselect" in folder_info.flags:
                continue
            try:
                mb.folder.set(folder_info.name)
            except Exception:
                continue
            uids = [msg.uid for msg in mb.fetch(AND(subject=prefix), mark_seen=False)]
            if uids:
                mb.delete(uids)
                deleted += len(uids)
    return deleted


@pytest.fixture(scope="session", autouse=True)
def cleanup_after_all_tests(
    request: Any,
    email_address: str,
    email_password: str,
    tmp_workspace: Path,
):
    """Session-scoped finalizer: purge test emails from remote + wipe temp dir."""
    yield
    print(f"\n{'=' * 60}")
    print("CLEANUP: removing test emails from remote server...")
    try:
        n = _imap_purge_test_emails(email_address, email_password, CLEANUP_SUBJECT_PREFIX)
        print(f"CLEANUP: deleted {n} test email(s) from remote")
    except Exception as exc:
        print(f"CLEANUP: remote purge failed: {exc}")

    print(f"CLEANUP: removing temp workspace {tmp_workspace}")
    shutil.rmtree(tmp_workspace, ignore_errors=True)
    print("CLEANUP: done")
    print("=" * 60)
