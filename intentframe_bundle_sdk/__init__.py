"""IntentFrame Bundle SDK — governed lifecycle for action and domain bundles.

Contract summary:

- All policy-aware hooks are async (``enrich``, ``enforce_constraints``,
  ``structural_gates``, ``allow_gates``, ``build_ai_context``,
  ``describe_constraints``).  Only ``validate_constraints`` and
  ``onboarding_guardrails`` are sync.
- Bundles receive a per-action :class:`ActionPermission` only — never
  ``UserContext`` or ``UserPolicy``.
- Constraint dicts are parsed fresh on each hook call; do not cache parsed
  models on bundle classes.
- :class:`DeterministicRunner` is the sole runtime caller of bundle hooks;
  it enforces per-hook deadlines and converts timeout/crash to structured
  BLOCK outcomes.
- Plugin packages register via ``register_bundles(registry)``; use
  :func:`ensure_loaded` as the single boot path.
- Optional :meth:`ActionBundle.startup` / :meth:`ActionBundle.aclose` hooks
  release bundle-owned resources; see :mod:`intentframe_bundle_sdk.lifecycle`.
- See :data:`BUNDLE_SDK_VERSION` for the current contract version.
"""

from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.domain import DomainBundle
from intentframe_bundle_sdk.loader import ensure_loaded, validate_policy_against_registry
from intentframe_bundle_sdk.lifecycle import shutdown_bundles, startup_bundles
from intentframe_bundle_sdk.onboarding_manifest import OnboardingManifest
from intentframe_bundle_sdk.registry import (
    action_bundle_for,
    all_action_bundles,
    all_domain_bundles,
    all_passive_read_action_ids,
    domain_bundle_for,
    domains_for_action,
    registered_domain_ids,
    register_action_bundle,
    register_domain_bundle,
    register_domain_routes,
    register_onboarding_manifest,
    routed_domain_ids,
    validate_policy_domain_constraints,
)
from intentframe_bundle_sdk.onboarding import render_onboarding_bundle_context
from intentframe_bundle_sdk.constraints import (
    describe_action_constraints,
    describe_action_constraints_from_policy,
    describe_permission_constraints,
)
from intentframe_bundle_sdk.runner import DeterministicRunner
from intentframe_bundle_sdk.audit_dump import (
    audit_dump,
    dump_bundle_ai_context,
    dump_bundle_context,
)
from intentframe_bundle_sdk.runner import HookTimeouts
from intentframe_bundle_sdk.types import (
    BUNDLE_SDK_VERSION,
    ActionPermission,
    BundleAIContext,
    BundleConfigError,
    BundleContext,
    BundleDeterministicResult,
    BundleError,
    BundleGateDecision,
    BundleHookCrashed,
    BundleHookTimeout,
    BundlePhaseOutcome,
    ConstraintPromptContext,
    EnrichmentRecord,
    action_permission_from_policy,
    bundle_ai_context_or_empty,
    enrichment_audit_fields,
    record_enrichment,
)
from intentframe_core.types import IntentSignal

__all__ = [
    "ActionBundle",
    "ActionPermission",
    "BUNDLE_SDK_VERSION",
    "BundleConfigError",
    "BundleError",
    "BundleHookCrashed",
    "BundleHookTimeout",
    "HookTimeouts",
    "IntentSignal",
    "BundleAIContext",
    "BundleContext",
    "BundleDeterministicResult",
    "BundleGateDecision",
    "BundlePhaseOutcome",
    "ConstraintPromptContext",
    "EnrichmentRecord",
    "OnboardingManifest",
    "describe_action_constraints",
    "describe_action_constraints_from_policy",
    "describe_permission_constraints",
    "DeterministicRunner",
    "DomainBundle",
    "ensure_loaded",
    "shutdown_bundles",
    "startup_bundles",
    "action_bundle_for",
    "action_permission_from_policy",
    "all_action_bundles",
    "all_domain_bundles",
    "all_passive_read_action_ids",
    "audit_dump",
    "domain_bundle_for",
    "domains_for_action",
    "dump_bundle_ai_context",
    "dump_bundle_context",
    "bundle_ai_context_or_empty",
    "enrichment_audit_fields",
    "record_enrichment",
    "registered_domain_ids",
    "register_action_bundle",
    "register_domain_bundle",
    "register_domain_routes",
    "register_onboarding_manifest",
    "render_onboarding_bundle_context",
    "routed_domain_ids",
    "validate_policy_domain_constraints",
    "validate_policy_against_registry",
]
