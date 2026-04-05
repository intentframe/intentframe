"""EDI email account management routes — /edi/*

Wraps the EDI email config module for account CRUD and daemon status.
Email passwords must be stored in the credential vault first, then
accounts are added here.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/edi", tags=["edi"])

logger = logging.getLogger(__name__)


class AddAccountRequest(BaseModel):
    email: str
    display_name: str = ""
    validate_imap: bool = True


@router.get("/accounts")
async def list_accounts():
    """List configured email accounts (from config.yaml, no daemon required)."""
    from external_data_ingestion.email.config import list_configured_emails
    return {"accounts": list_configured_emails()}


@router.post("/accounts")
async def add_account(body: AddAccountRequest):
    """Add an email account.

    The password must already exist in the vault under
    ``email.<address> / password``.
    """
    from external_data_ingestion.email.config import add_email
    try:
        resolved = add_email(
            body.email,
            body.display_name,
            validate=body.validate_imap,
        )
    except ValueError as exc:
        logger.warning("EDI add account rejected for %s: %s", body.email, exc)
        raise HTTPException(400, str(exc))
    except ConnectionError as exc:
        logger.warning("EDI add account IMAP check failed for %s: %s", body.email, exc)
        raise HTTPException(503, str(exc))

    logger.info("EDI account added: %s", resolved.email)
    return {
        "email": resolved.email,
        "provider": resolved.provider,
        "imap_host": resolved.imap_host,
    }


@router.delete("/accounts/{email:path}")
async def remove_account(email: str):
    """Remove an email account from the workspace config."""
    from external_data_ingestion.email.config import remove_email
    removed = remove_email(email)
    if not removed:
        logger.warning("EDI remove account: not found: %s", email)
        raise HTTPException(404, f"Account {email!r} not found")
    logger.info("EDI account removed: %s", email)
    return {"email": email, "removed": True}


@router.get("/status")
async def daemon_status(request: Request):
    """Return EDI daemon process status."""
    proc_manager = getattr(request.app.state, "proc_manager", None)
    if not proc_manager:
        return {"running": False}
    status = proc_manager.status("edi")

    from external_data_ingestion.email.daemon import is_daemon_running
    alive, pid = is_daemon_running()
    status["daemon_alive"] = alive
    status["daemon_pid"] = pid

    return status
