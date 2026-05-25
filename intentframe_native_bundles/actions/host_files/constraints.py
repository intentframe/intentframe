"""Constraints for HOST_FILE category actions.

HOST_FILE actions (READ_HOST_FILE / WRITE_HOST_FILE / DELETE_HOST_FILE /
LIST_HOST_DIRECTORY) operate on real host filesystem paths
(``~/Documents/...``) rather than the virtual filesystem (``/home/...``)
used by the FILE category.

The constraint schema lives in a separate module so:

- the field name ``allowed_host_paths`` stays disjoint from
  :class:`intentframe_native_bundles.actions.files.constraints.FileConstraints.allowed_paths`,
  so virtual and host file policies never share field names;
- each family bundle validates its slice at startup via
  :func:`intentframe_bundle_sdk.loader.validate_policy_against_registry`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HostFileConstraints(BaseModel):
    """Real-path constraints for HOST_FILE actions.

    Unlike :class:`FileConstraints` (virtual vocabulary), these patterns
    are matched against canonicalized real filesystem paths (after
    ``~`` expansion and symlink resolution via
    :func:`resource_registry.floor.canonicalize_real_path`).  The
    host-files bundle does **not** apply ``normalize_virtual_path``.

    Attributes:
        allowed_host_paths: Real host path patterns the user permits.
            Exactly two shapes are supported:

              - **exact path**: ``~/Documents/note.txt`` — matches that
                single file only.
              - **subtree glob**: ``~/Documents/*`` — matches children
                under the directory via :mod:`fnmatch`.

            Patterns may start with ``~`` — enforcement canonicalizes
            them before matching.  Trailing-slash directory shorthand
            (``~/Documents/``) is **rejected at load time**: real-path
            canonicalization (``pathlib.Path.resolve``) strips trailing
            separators, which would make the trailing-slash prefix
            branch of the matcher dead code and the policy's intent
            ambiguous.  Use the explicit ``dir/*`` form instead.  This
            differs from :class:`FileConstraints`, which operates in a
            virtual vocabulary where ``normalize_virtual_path``
            preserves trailing slashes as a directory marker.

    Note:
        Field name is deliberately disjoint from
        ``FileConstraints.allowed_paths`` so virtual and host file
        policies never share YAML field names.  Startup validation
        routes each ``allowed_actions`` entry by action id to its
        bundle, which parses constraints with
        :class:`FileConstraints` or this class respectively.
        ``model_config(extra="forbid")`` on both models rejects mixed
        or wrong-key payloads loudly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed_host_paths: list[str] = Field(min_length=1)

    @field_validator("allowed_host_paths")
    @classmethod
    def _reject_trailing_slash(cls, patterns: list[str]) -> list[str]:
        # Trailing-slash directory shorthand is rejected at config load
        # time rather than handled at match time.  Rationale:
        #
        #   1. ``canonicalize_real_path`` uses ``pathlib.Path.resolve``,
        #      which strips trailing separators by OS convention.  A
        #      policy pattern ``~/Documents/`` therefore canonicalizes
        #      to the same string as ``~/Documents`` and the "this is
        #      a directory" signal is lost before any matcher branch
        #      can read it.
        #   2. Supporting both ``dir/`` and ``dir/*`` at match time
        #      would require a separator-boundary check that must be
        #      kept in perfect sync with the floor and the executor
        #      adapter.  Silent drift in any one of them is a direct
        #      path to an allowlist-widening bug.
        #   3. Rejecting the form at load time collapses the matcher
        #      surface to two unambiguous shapes (exact / ``dir/*``),
        #      fails closed at config time (loud ValidationError, not
        #      a runtime false-deny), and can never accidentally
        #      widen access in any future refactor.
        #
        # The VFS sibling (``FileConstraints.allowed_paths``) does NOT
        # share this restriction: ``normalize_virtual_path`` preserves
        # trailing slashes as an explicit directory marker.  Do not
        # attempt to unify — the vocabularies are deliberately
        # distinct.
        bad = [p for p in patterns if p != "/" and p.endswith("/")]
        if bad:
            raise ValueError(
                "HostFileConstraints.allowed_host_paths rejects trailing-slash "
                f"directory shorthand (got {bad!r}). Use the explicit "
                "glob form instead: 'dir/' -> 'dir/*'."
            )
        return patterns
