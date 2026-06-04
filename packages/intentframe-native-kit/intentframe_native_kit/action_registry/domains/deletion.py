"""Deletion-domain intent slice for ``IntentFrame.data``.

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

Used by ``DeletionDomainBundle`` and optionally by agent authors via
``DOMAIN_SCHEMAS`` for local pre-flight validation.
"""

from __future__ import annotations

from intentframe_bundle_sdk import DomainSchema


class DeletionIntentData(DomainSchema):
    """Deletion-domain slice of ``IntentFrame.data``.

    Validates ``path`` and ``irreversible`` only. Other payload fields (e.g.
    finance ``amount``) are ignored so deletion can compose with other routed
    domains on the same action.
    """

    path: str
    irreversible: bool = True
