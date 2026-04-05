"""
Policy Registry -- HTTP client over Unix Domain Socket.

Drop-in replacement for the in-process PolicyRegistry.
Same method signatures, but calls the policy-registry service over HTTP/UDS.
"""

from __future__ import annotations

from typing import Optional

import httpx

from policy_registry.models import ActionPermission, UserPolicy

DEFAULT_SOCKET = "~/.intentframe/run/policy-registry.sock"


class PolicyRegistryClient:
    """HTTP client that mirrors the PolicyRegistry interface.

    Uses httpx with UDS transport to talk to the policy-registry service.
    """

    def __init__(self, socket_path: str = DEFAULT_SOCKET) -> None:
        import os

        self._socket = os.path.expanduser(socket_path)
        self._transport = httpx.HTTPTransport(uds=self._socket)
        self._client = httpx.Client(
            transport=self._transport,
            base_url="http://policy-registry",
            timeout=10.0,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def set_user_policy(self, policy: UserPolicy) -> None:
        resp = self._client.post("/policies", json=policy.model_dump(mode="json"))
        resp.raise_for_status()

    def get_user_policy(self, user_id: str) -> UserPolicy:
        resp = self._client.get(f"/policies/{user_id}")
        if resp.status_code == 404:
            raise KeyError(f"No policy found for user '{user_id}'")
        resp.raise_for_status()
        return UserPolicy.model_validate(resp.json())

    def delete_user_policy(self, user_id: str) -> None:
        resp = self._client.delete(f"/policies/{user_id}")
        resp.raise_for_status()

    def list_users(self) -> list[str]:
        resp = self._client.get("/policies")
        resp.raise_for_status()
        return resp.json()

    def get_permission(
        self, user_id: str, action_type: str
    ) -> Optional[ActionPermission]:
        resp = self._client.get(
            f"/policies/{user_id}/permission", params={"action": action_type}
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        if data is None:
            return None
        return ActionPermission.model_validate(data)
