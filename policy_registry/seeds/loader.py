"""YAML → :class:`UserPolicy` loader.

Single-call entry point :func:`load_policy_seed` covers every existing
caller (gateway bootstrap, dev seed CLI, attack/red-team test loaders,
external-agent installers).  The function returns a fully validated
:class:`UserPolicy`; callers can ``.model_dump(mode="json")`` it for
the policy-registry HTTP body or hand it directly to in-process
consumers.

Schema versioning
-----------------
Every YAML must declare ``intentframe_schema_version: <int>`` at the
top level.  The loader compares against
:data:`policy_registry.models.INTENTFRAME_POLICY_SCHEMA_VERSION` and
hard-fails on mismatch with a friendly error so users with stale YAMLs
get a clear migration signal instead of a Pydantic stacktrace.

Identity
--------
The loader does not consult the environment.  Callers pass ``user_id``
and ``agent_id`` explicitly (the gateway derives them from
:mod:`policy_registry.seeds.resolver`).  Both fields must end up
populated — either via the YAML or via the keyword overrides — or
:meth:`UserPolicy.model_validate` raises.

Constraint dispatch
-------------------
Validation goes through :meth:`UserPolicy.model_validate`, which reuses
the registry's untagged ``ConstraintTypes`` union (dispatches on the
disjoint required fields, e.g. ``allowed_paths`` vs
``allowed_host_paths``).  Both sides set ``extra="forbid"`` — see
``tests/test_policy_host_constraints_roundtrip.py`` for the regression
pin.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from policy_registry.models import (
    INTENTFRAME_POLICY_SCHEMA_VERSION,
    UserPolicy,
)


class PolicySchemaVersionError(ValueError):
    """Raised when a YAML's ``intentframe_schema_version`` is missing or stale."""


def load_policy_seed(
    yaml_path: str | Path,
    *,
    user_id: str | None = None,
    agent_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> UserPolicy:
    """Build a :class:`UserPolicy` from a YAML seed.

    Args:
        yaml_path: Path to the YAML file (packaged builtin or
            user-override).  Required.
        user_id: Override the YAML's ``user_id`` field.  Optional;
            when ``None`` the YAML's value is used.
        agent_id: Override the YAML's ``agent_id`` field.  Optional;
            when ``None`` the YAML's value is used.
        metadata: Shallow overlay on the YAML ``metadata`` dict
            (caller wins).  Useful for runtime tags like
            ``{"note": "Auto-seeded by gateway bootstrap"}``.

    Returns:
        A validated :class:`UserPolicy`.

    Raises:
        PolicySchemaVersionError: YAML is missing the schema version
            field or declares a version this build does not support.
        ValueError: YAML is not a mapping or has structural issues.
        pydantic.ValidationError: Policy fields fail Pydantic validation
            (e.g. unknown action type, bad constraint shape).
    """
    path = Path(yaml_path)
    raw = _read_yaml(path)
    _validate_schema_version(raw, source=path)
    _normalise_domain_constraints(raw)

    if user_id is not None:
        raw["user_id"] = user_id
    if agent_id is not None:
        raw["agent_id"] = agent_id

    if metadata:
        merged = dict(raw.get("metadata") or {})
        merged.update(metadata)
        raw["metadata"] = merged

    policy = UserPolicy.model_validate(raw)
    _validate_loaded_policy(policy)
    return policy


def _validate_loaded_policy(policy: UserPolicy) -> None:
    if not policy.domain_constraints:
        return
    from intentframe_action_bundle.bundles.register import ensure_bundles_registered
    from intentframe_bundle_sdk.registry import validate_policy_domain_constraints

    ensure_bundles_registered()
    validate_policy_domain_constraints(policy.domain_constraints)


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML seed file into a dict (rejects non-mapping documents)."""
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(
            f"Policy seed at {path} must be a YAML mapping, got {type(data).__name__}"
        )
    return data


def _validate_schema_version(raw: dict[str, Any], *, source: Path) -> None:
    """Hard-fail on missing or mismatched ``intentframe_schema_version``.

    Uses a custom error type so installers / CLIs can present a
    human-friendly migration message instead of a generic ``ValueError``.
    """
    declared = raw.get("intentframe_schema_version")
    expected = INTENTFRAME_POLICY_SCHEMA_VERSION

    if declared is None:
        raise PolicySchemaVersionError(
            f"Policy YAML at {source} is missing the required field "
            f"`intentframe_schema_version`. Add `intentframe_schema_version: {expected}` "
            f"at the top of the file. This build of IntentFrame supports schema version {expected}."
        )

    if not isinstance(declared, int) or isinstance(declared, bool):
        raise PolicySchemaVersionError(
            f"Policy YAML at {source} has `intentframe_schema_version: {declared!r}`; "
            f"expected an integer (this build supports schema version {expected})."
        )

    if declared != expected:
        raise PolicySchemaVersionError(
            f"Policy YAML at {source} declares `intentframe_schema_version: {declared}`, "
            f"but this build of IntentFrame supports schema version {expected}. "
            f"Either update the YAML to the new schema or pin to a matching IntentFrame release."
        )


def _normalise_domain_constraints(raw: dict[str, Any]) -> None:
    """Inject the dict key into each ``domain_constraints`` value as ``domain``.

    The YAML schema is ``domain_constraints: {<domain>: {<fields>}}``,
    which is friendly to author but does not carry the ``domain`` field
    that :data:`policy_registry.models.DomainConstraintTypes`'s
    discriminator dispatches on.  Inject the key into each value (no-op
    when the field is already present and matches).
    """
    dc = raw.get("domain_constraints")
    if not isinstance(dc, dict):
        return
    for domain_name, value in dc.items():
        if not isinstance(value, dict):
            continue
        existing = value.get("domain")
        if existing is None:
            value["domain"] = domain_name
        elif existing != domain_name:
            raise ValueError(
                f"domain_constraints[{domain_name!r}] has conflicting "
                f"`domain: {existing!r}` field; remove it or align with the key."
            )


__all__ = [
    "PolicySchemaVersionError",
    "load_policy_seed",
]
