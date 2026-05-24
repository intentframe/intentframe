"""Domain routing manifest — maps domain_id to action ids (not owned by DomainBundle)."""

from __future__ import annotations

DOMAIN_ROUTES: dict[str, frozenset[str]] = {
    "finance": frozenset({"PAY_INVOICE"}),
    "deletion": frozenset({
        "DELETE_FILE",
        "DELETE_HOST_FILE",
        "DELETE_EVENT",
        "DELETE_REMINDER",
        "DELETE_CONTACT",
        "DELETE_NOTE",
    }),
}
