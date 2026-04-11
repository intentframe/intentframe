"""System prompt assembly using Jinja2 templates.

Template files live in jarvis/prompts/. The main template is system.j2
which includes partial templates for each instruction block. Keeping
prompts in files means they can be edited without touching Python code.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from jinja2 import Environment, PackageLoader, select_autoescape

from jarvis.config import JarvisConfig

# ---------------------------------------------------------------------------
# Jinja2 environment
# ---------------------------------------------------------------------------

_env = Environment(
    loader=PackageLoader("jarvis", "prompts"),
    autoescape=select_autoescape(enabled_extensions=()),  # no HTML escaping for prompts
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)

SKILLS_INSTRUCTIONS = (
    "Below is an index of skills available on this system. "
    "When a task matches a skill, read the full SKILL.md for detailed "
    "instructions before acting."
)


def build_system_prompt(
    *,
    soul: str,
    user: str,
    memory: str,
    heartbeat: str,
    guardrails: list[str],
    virtual_paths: list[str] | None = None,
    path_permissions: dict[str, str] | None = None,
    skills_xml: str,
    config: JarvisConfig,
    session_id: str | None = None,
) -> str:
    """Render the system prompt from the Jinja2 template.

    All parameters are keyword-only so call sites are explicit about what
    they're passing.  Missing/empty strings are treated as falsy by the
    template so their sections are omitted.
    """
    template = _env.get_template("system.j2")
    return template.render(
        soul=soul,
        user=user,
        memory=memory,
        heartbeat=heartbeat,
        guardrails=guardrails,
        virtual_paths=virtual_paths or [],
        path_permissions=path_permissions or {},
        skills_xml=skills_xml,
        skills_instructions=SKILLS_INSTRUCTIONS,
        now=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z (UTC%z)"),
        model=config.model,
        session_id=session_id or str(uuid.uuid4())[:8],
    )
