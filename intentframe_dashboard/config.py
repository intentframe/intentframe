"""
Dashboard Config Loader — reads a dashboard.yaml that declares
users, workspaces, and tasks for a dashboard run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field


class ActionPermissionConfig(BaseModel):
    """Config-level representation of an action permission."""
    safe: bool = False
    constraints: Optional[Dict[str, Any]] = None


class IntentLimitConfig(BaseModel):
    """Config-level representation of a semantic intent limit."""
    limit_id: str
    domain: str
    description: str
    raw: str
    threshold: Optional[float] = None
    pattern: Optional[str] = None
    effect: str = "block"
    scope: str = "per_action"


class DomainConstraintConfig(BaseModel):
    """Config-level representation of a domain constraint set."""
    max_amount: Optional[float] = None
    allowed_currencies: Optional[List[str]] = None
    allowed_recipients: Optional[List[str]] = None
    require_confirmation: bool = True
    allowed_paths: Optional[List[str]] = None
    block_irreversible: bool = False


class UserConfig(BaseModel):
    """Config-level user policy definition.

    allowed_actions maps action type strings to permission config.
    intent_limits lists cross-cutting semantic restrictions for AI evaluation.
    domain_constraints maps domain names to structural enforcement limits.
    """
    allowed_actions: Dict[str, ActionPermissionConfig] = Field(default_factory=dict)
    intent_limits: List[IntentLimitConfig] = Field(default_factory=list)
    domain_constraints: Dict[str, DomainConstraintConfig] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MountConfig(BaseModel):
    virtual_path: str
    real_path: str
    file_filter: Optional[str] = None
    writable: bool = False


class WorkspaceConfig(BaseModel):
    base_path: str
    mounts: List[MountConfig]


class TaskConfig(BaseModel):
    description: str
    agent: str
    user: str
    workspace: str
    timeout: float = 120.0


class DashboardConfig(BaseModel):
    users: Dict[str, UserConfig] = Field(default_factory=dict)
    workspaces: Dict[str, WorkspaceConfig] = Field(default_factory=dict)
    tasks: List[TaskConfig] = Field(default_factory=list)


def load_config(path: str | Path) -> DashboardConfig:
    """Load and validate a dashboard.yaml file."""
    with open(path) as f:
        raw = yaml.safe_load(f)
    return DashboardConfig(**raw)
