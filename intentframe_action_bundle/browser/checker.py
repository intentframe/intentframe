"""Constraint checker for BROWSER category actions."""

from __future__ import annotations

import fnmatch

from intentframe_core.types import IntentFrame
from intentframe_components.guardian.checkers.base import CheckContext, ConstraintChecker
from policy_registry.constraints.browser import BrowserConstraints


class BrowserChecker(ConstraintChecker):
    """URL-based constraint enforcement for browser operations."""

    def check(
        self,
        intent: IntentFrame,
        constraints: BrowserConstraints,
        context: CheckContext | None = None,
    ) -> tuple[bool, str]:
        del context
        url = intent.target or (intent.data or {}).get("url", "")
        for pattern in constraints.allowed_urls:
            if fnmatch.fnmatch(url, pattern):
                return True, ""
        return False, f"URL '{url}' not in allowed URLs"

    def summarize(self, constraints: BrowserConstraints) -> str:
        return f"Allowed URLs: {', '.join(constraints.allowed_urls)}"
