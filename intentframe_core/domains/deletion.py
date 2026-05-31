"""Typed intent data schema for the deletion domain.

Contract:
    The deletion domain is path-oriented. The destructive resource is carried
    in ``IntentFrame.data["path"]`` — the same field the executor adapter acts
    on (``params["path"]``). ``IntentFrame.target`` is display/audit only and is
    never the execution or policy authority.

Current limitation:
    This schema is still path-oriented. It works well for file deletions, but
    non-file destructive actions such as ``DELETE_EVENT`` and
    ``DELETE_REMINDER`` do not naturally have a ``path``. If those actions are
    mapped into the deletion domain without supplying a compatible payload,
    schema validation rejects them before policy enforcement runs.

    Follow-up work should generalize deletion-domain intent data so it can
    represent both path-based and non-path-based destructive actions.
"""

from __future__ import annotations

from intentframe_core.domains.base import DomainSchema


class DeletionIntentData(DomainSchema):
    """Required fields for any deletion/destructive action.

    When an action belongs to the deletion domain (e.g. DELETE_FILE),
    ``IntentFrame.data`` must conform to this schema.

    ``path`` is the executable resource the executor deletes; it is the same
    field validated by deletion policy. It currently reflects the file-deletion
    use case and is not a natural fit for calendar, reminders, contacts, or
    other record-oriented deletions.
    """

    path: str
    irreversible: bool = True
