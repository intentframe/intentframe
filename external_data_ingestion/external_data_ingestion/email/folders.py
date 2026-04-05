"""IMAP folder discovery using RFC 6154 special-use attributes.

The server tells us the *purpose* of each folder via flags in the LIST
response (``\\Drafts``, ``\\Sent``, ``\\Trash``, …).  We never hardcode
folder names — they're locale-dependent (e.g. ``[Gmail]/Todos`` in Spanish).

Reference: https://datatracker.ietf.org/doc/html/rfc6154
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from imap_tools import MailBox

log = structlog.get_logger()

# RFC 6154 §2 — standard special-use mailbox attributes.
# Keys are the flag strings exactly as they appear in LIST responses.
SPECIAL_USE_FLAGS: dict[str, str] = {
    "\\All": "all",
    "\\Archive": "archive",
    "\\Drafts": "drafts",
    "\\Flagged": "flagged",
    "\\Inbox": "inbox",
    "\\Junk": "junk",
    "\\Sent": "sent",
    "\\Trash": "trash",
}


def _classify_role(name: str, flags: tuple[str, ...]) -> str | None:
    """Derive the canonical role for a folder from its server-advertised flags.

    Falls back to the IMAP-guaranteed ``INBOX`` name only — everything else
    is determined by flags alone.
    """
    for flag in flags:
        role = SPECIAL_USE_FLAGS.get(flag.strip())
        if role:
            return role
    if name.upper() == "INBOX":
        return "inbox"
    return None


async def discover_folders(mailbox: "MailBox") -> list[dict]:
    """Query the IMAP server for all folders and their roles.

    Returns a list of dicts:
    ``{"name", "role", "delimiter", "flags", "selectable"}``.
    """
    folder_infos = await asyncio.to_thread(mailbox.folder.list)

    folders: list[dict] = []
    for fi in folder_infos:
        flags = list(fi.flags)
        role = _classify_role(fi.name, fi.flags)
        selectable = "\\Noselect" not in fi.flags
        folders.append(
            {
                "name": fi.name,
                "role": role,
                "delimiter": fi.delim,
                "flags": flags,
                "selectable": selectable,
            }
        )
        log.debug("discovered_folder", name=fi.name, role=role, flags=fi.flags)

    if not any(f["role"] == "inbox" for f in folders):
        folders.insert(
            0,
            {"name": "INBOX", "role": "inbox", "delimiter": "/", "flags": [], "selectable": True},
        )

    return folders


def folder_for_role(folders: list[dict], role: str) -> str | None:
    """Return the folder *name* that the server assigned to *role*, or None."""
    for f in folders:
        if f["role"] == role:
            return f["name"]
    return None
