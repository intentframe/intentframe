"""Typed intent data schema for the deletion domain.

Current limitation:
    This schema is still path-oriented. It works well for file deletions, but
    non-file destructive actions such as ``DELETE_EVENT`` and
    ``DELETE_REMINDER`` do not naturally have a ``target_path``. If those
    actions are mapped into the deletion domain without supplying a compatible
    payload, Actor-side validation rejects them before they enter the
    IntentFrame pipeline.

    That means:
    - the request never reaches Analysis Engine / Guardian / Executor
    - no runtime audit entry is created for the failed action
    - the caller sees an Actor validation error rather than a policy decision

    Follow-up work should generalize deletion-domain intent data so it can
    represent both path-based and non-path-based destructive actions.
"""

from __future__ import annotations

from intentframe_core.domains.base import DomainSchema


class DeletionIntentData(DomainSchema):
    """Required fields for any deletion/destructive action.

    When an action belongs to the deletion domain (e.g. DELETE_FILE),
    the Actor validates that ``IntentFrame.data`` conforms to this
    schema before entering the pipeline.

    ``target_path`` currently reflects the original file-deletion use case.
    It is not a natural fit for calendar, reminders, contacts, or other
    record-oriented deletions.
    """

    target_path: str
    irreversible: bool = True
