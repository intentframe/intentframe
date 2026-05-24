"""Terminal deny_capabilities brief for onboarding (lossless, family-grouped)."""


def summarize_deny_capabilities(deny_caps: frozenset[str]) -> str:
    """Render ``deny_capabilities`` as structured, lossless brief text."""
    if not deny_caps:
        return f"{len(deny_caps)} capability families denied"

    script_prefix = "capability:script_execution:"
    stdin_prefix = "capability:stdin_exec:"
    pkg_prefix = "capability:package_install:"

    by_family: dict[str, list[str]] = {
        "script_execution": [],
        "stdin_exec": [],
        "package_install": [],
        "other": [],
    }
    for tag in sorted(deny_caps):
        if tag.startswith(script_prefix):
            by_family["script_execution"].append(tag[len(script_prefix) :])
        elif tag.startswith(stdin_prefix):
            by_family["stdin_exec"].append(tag[len(stdin_prefix) :])
        elif tag.startswith(pkg_prefix):
            by_family["package_install"].append(tag[len(pkg_prefix) :])
        else:
            by_family["other"].append(tag.removeprefix("capability:"))

    parts: list[str] = []
    for family, items in by_family.items():
        if items:
            parts.append(f"{family}={{{', '.join(items)}}}")

    return f"deny_capabilities: {'; '.join(parts)}"
