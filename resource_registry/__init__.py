"""
Resource Registry -- Workspace and resource management for IntentFrame.

The registry is the single source of truth for workspace configurations.
It distributes different views to different consumers:

    Client/Agent  -> ClientView   (virtual paths + permissions)
    Executor      -> ExecutorView (full mount table + real paths)

In the demo this runs in-process.  In production it becomes its own
microservice backed by a database.

Usage:
    from resource_registry import ResourceRegistry, ResourceMount

    registry = ResourceRegistry()
    registry.create_workspace(
        workspace_id="my_workspace",
        mounts=[ResourceMount(virtual_path="/data/", real_path="/real/path", writable=True)],
    )

    client_view   = registry.client_view("my_workspace")
    executor_view = registry.executor_view("my_workspace")
"""

from resource_registry.models import (
    ClientView,
    ExecutorView,
    ResourceMount,
    Workspace,
)
from resource_registry.registry import ResourceRegistry

__all__ = [
    "ClientView",
    "ExecutorView",
    "ResourceMount",
    "ResourceRegistry",
    "Workspace",
]
