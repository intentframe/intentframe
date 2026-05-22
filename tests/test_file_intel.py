"""Realistic tests for ``intentframe_action_bundle.files.file_intel``.

These tests exercise the LAYER 2b FileIntel builder against real
filesystem fixtures (``tmp_path``) rather than mocking ``os.stat``.
They pin the deterministic contract the rest of the pipeline depends
on:

  * ``build_destination_intel`` correctly differentiates missing /
    existing / symlink / directory / dangling-symlink destinations
    for ``WRITE_HOST_FILE`` actions.
  * For ``WRITE_FILE`` (virtual) actions, destination-state fields
    stay ``None`` while path-semantic fields (``extension``,
    ``path_category``) are still populated from the target string.
  * ``hits_floor_deny_prefix`` fires for canonical paths under the
    resource-registry floor (``/System``, ``/usr``, …).
  * ``extension_of`` produces the normalized extension string the AE
    renders alongside ``language`` — FileIntel deliberately does NOT
    decide whether the two "disagree"; that judgment is contextual
    (container formats like ``.md`` legitimately host code) and lives
    in the AE prompt, not in this module.
  * ``build_file_intel`` merges inspector output with destination
    intel correctly, survives inspector exceptions (fail-minimal, not
    fail-open), and truncates the symlink-target and extension fields
    at their :class:`FileIntel` bounds.
  * The key regression case — a ``WRITE_HOST_FILE`` to a path that
    does NOT exist — produces ``destination_exists=False`` so AE can
    avoid the bogus "deletion" tag that originally caused the false-
    positive block.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from action_registry.types import ActionType
from intentframe_action_bundle.evidence import (
    FILE_INTEL_EXTENSION_MAX_LEN,
    FILE_INTEL_PATH_MAX_LEN,
    FileIntel,
)
from intentframe_action_bundle.files.file_intel import (
    build_destination_intel,
    build_file_intel,
    extension_of,
)

WRITE_FILE = ActionType.WRITE_FILE.value
WRITE_HOST_FILE = ActionType.WRITE_HOST_FILE.value


# ─────────────────────────────────────────────────────────────────────
# extension_of
# ─────────────────────────────────────────────────────────────────────


class TestExtensionOf:
    """``extension_of`` is the canonical source for ``FileIntel.extension``."""

    def test_simple_extension(self):
        assert extension_of("foo.py") == ".py"

    def test_full_path_extension(self):
        assert extension_of("/Users/alice/docs/note.md") == ".md"

    def test_uppercase_extension_normalized(self):
        assert extension_of("REPORT.TXT") == ".txt"

    def test_compound_suffix_returns_last(self):
        # Path.suffix returns the last component only — ``.tar.gz`` ->
        # ``.gz``.  This matches our mismatch table's expectations.
        assert extension_of("archive.tar.gz") == ".gz"

    def test_no_extension_returns_none(self):
        assert extension_of("Makefile") is None

    def test_dotfile_without_suffix_returns_none(self):
        # ``.zshrc`` is a dotfile, not an extension on an empty name.
        assert extension_of(".zshrc") is None

    def test_empty_string_returns_none(self):
        assert extension_of("") is None

    def test_none_input_returns_none(self):
        assert extension_of(None) is None


# ─────────────────────────────────────────────────────────────────────
# build_destination_intel — WRITE_HOST_FILE (real-path probing)
# ─────────────────────────────────────────────────────────────────────


class TestBuildDestinationIntelHostFile:
    """Exercise the stat-based destination probe against real fixtures."""

    def test_missing_file_under_existing_parent(self, tmp_path: Path):
        # The regression case: target does not exist, parent does.
        # Must yield destination_exists=False so AE avoids the bogus
        # "assume overwrite → deletion" tag that caused false positives.
        target = tmp_path / "new_file.txt"
        intel = build_destination_intel(WRITE_HOST_FILE, str(target))

        assert intel["destination_exists"] is False
        assert intel["destination_kind"] == "missing"
        assert intel["parent_kind"] == "directory"
        assert intel["is_symlink"] is False
        assert intel["symlink_target_real_path"] is None
        assert intel["extension"] == ".txt"
        # tmp_path is not a sensitive category — ``"unknown"`` is the
        # defined default (AE's rubric keys off positive categories,
        # not the absence of one, so "unknown" is treated the same as
        # "no category").
        assert intel["path_category"] == "unknown"
        assert intel["hits_floor_deny_prefix"] is False

    def test_existing_regular_file(self, tmp_path: Path):
        target = tmp_path / "existing.md"
        target.write_text("hello")

        intel = build_destination_intel(WRITE_HOST_FILE, str(target))

        assert intel["destination_exists"] is True
        assert intel["destination_kind"] == "file"
        # parent_kind is only populated when the destination is missing;
        # on existing paths we deliberately leave it None to avoid a
        # redundant stat call.
        assert intel["parent_kind"] is None
        assert intel["is_symlink"] is False
        assert intel["extension"] == ".md"

    def test_existing_directory(self, tmp_path: Path):
        target = tmp_path / "subdir"
        target.mkdir()

        intel = build_destination_intel(WRITE_HOST_FILE, str(target))

        assert intel["destination_exists"] is True
        assert intel["destination_kind"] == "directory"

    def test_missing_target_with_missing_parent(self, tmp_path: Path):
        # Deeper nonexistent path — parent itself is missing.  This is
        # the "write implicitly creates a directory tree" scope-expansion
        # signal AE cites.
        target = tmp_path / "nonexistent_dir" / "file.txt"

        intel = build_destination_intel(WRITE_HOST_FILE, str(target))

        assert intel["destination_exists"] is False
        assert intel["destination_kind"] == "missing"
        assert intel["parent_kind"] == "missing"

    def test_missing_target_with_file_parent(self, tmp_path: Path):
        # Pathological: parent is a regular file, so the write cannot
        # succeed.  ``parent_kind="file"`` lets AE flag an inconsistency.
        parent_file = tmp_path / "not_a_dir"
        parent_file.write_text("x")
        target = parent_file / "child.txt"

        intel = build_destination_intel(WRITE_HOST_FILE, str(target))

        assert intel["destination_exists"] is False
        assert intel["destination_kind"] == "missing"
        assert intel["parent_kind"] == "file"

    def test_resolving_symlink(self, tmp_path: Path):
        real = tmp_path / "real.txt"
        real.write_text("data")
        link = tmp_path / "link.txt"
        link.symlink_to(real)

        intel = build_destination_intel(WRITE_HOST_FILE, str(link))

        assert intel["destination_exists"] is True
        assert intel["is_symlink"] is True
        # destination_kind reflects the LINK TARGET (via stat()), so
        # a symlink pointing at a regular file reports "file" — AE
        # uses this together with ``is_symlink=True`` to reason about
        # "write may target a different file than it appears to".
        assert intel["destination_kind"] == "file"
        assert intel["symlink_target_real_path"] is not None
        # realpath must resolve to the underlying target.
        assert os.path.realpath(intel["symlink_target_real_path"]) == os.path.realpath(
            str(real)
        )

    def test_dangling_symlink(self, tmp_path: Path):
        link = tmp_path / "dangling.txt"
        link.symlink_to(tmp_path / "does_not_exist.txt")

        intel = build_destination_intel(WRITE_HOST_FILE, str(link))

        assert intel["destination_exists"] is True
        assert intel["is_symlink"] is True
        # Dangling: the link itself is the only thing present, so
        # destination_kind degrades to ``"symlink"`` rather than
        # pretending the missing target has a kind.
        assert intel["destination_kind"] == "symlink"
        # readlink must still populate the target (even though it
        # points at a missing path) so AE can see "this link aims at X".
        assert intel["symlink_target_real_path"] is not None
        assert "does_not_exist.txt" in intel["symlink_target_real_path"]

    def test_floor_deny_prefix_match(self):
        # ``/System`` is always floor-denied on every platform that
        # populates DENY_WRITE_PREFIXES.  We don't need the file to
        # exist — canonicalization + prefix match is pure-string.
        intel = build_destination_intel(WRITE_HOST_FILE, "/System/Library/probe.txt")
        assert intel["hits_floor_deny_prefix"] is True

    def test_floor_deny_miss_for_tmp(self, tmp_path: Path):
        intel = build_destination_intel(WRITE_HOST_FILE, str(tmp_path / "x.txt"))
        assert intel["hits_floor_deny_prefix"] is False

    def test_empty_target_returns_defaults(self):
        intel = build_destination_intel(WRITE_HOST_FILE, "")
        assert intel["destination_exists"] is None
        assert intel["destination_kind"] is None
        assert intel["parent_kind"] is None
        assert intel["is_symlink"] is False
        assert intel["extension"] is None
        assert intel["hits_floor_deny_prefix"] is False

    def test_none_target_returns_defaults(self):
        intel = build_destination_intel(WRITE_HOST_FILE, None)
        assert intel["destination_exists"] is None
        assert intel["extension"] is None

    def test_lstat_oserror_degrades_to_unknown(self, tmp_path: Path):
        # Simulate a transient OS error mid-probe — must NOT propagate,
        # must collapse destination_exists to None (explicit "unknown")
        # so downstream consumers can fail-closed into the critical
        # lane rather than see a confident "exists" or "missing" signal.
        target = tmp_path / "whatever.txt"
        target.write_text("data")

        def _raising_lstat(path):
            raise PermissionError("EACCES simulated")

        with patch("intentframe_action_bundle.files.file_intel.os.lstat", side_effect=_raising_lstat):
            intel = build_destination_intel(WRITE_HOST_FILE, str(target))

        assert intel["destination_exists"] is None
        assert intel["destination_kind"] is None
        # Path-semantic fields come from the TARGET STRING alone, so
        # they must still be populated even when stat fails.
        assert intel["extension"] == ".txt"


# ─────────────────────────────────────────────────────────────────────
# build_destination_intel — WRITE_FILE (virtual, no host stat)
# ─────────────────────────────────────────────────────────────────────


class TestBuildDestinationIntelVirtual:
    """VFS-rooted targets must NOT be stat'd against the host filesystem."""

    def test_virtual_target_leaves_destination_unknown(self, tmp_path: Path):
        # tmp_path-hosted fixture: even though this real file EXISTS,
        # build_destination_intel must not probe it for WRITE_FILE
        # because the target would normally be a virtual path in the
        # VFS, not a real host path.  Leaving destination_* as None
        # is the correct "unknown" signal.
        target = tmp_path / "virtual.py"
        target.write_text("print('hi')")

        intel = build_destination_intel(WRITE_FILE, str(target))

        assert intel["destination_exists"] is None
        assert intel["destination_kind"] is None
        assert intel["is_symlink"] is False
        assert intel["symlink_target_real_path"] is None
        assert intel["parent_kind"] is None

    def test_virtual_target_populates_path_semantics(self):
        # Virtual target with a known extension — semantic fields
        # MUST still be populated even without host stat.
        intel = build_destination_intel(WRITE_FILE, "/home/user/notes/todo.md")
        assert intel["extension"] == ".md"
        # ``/home/user/notes/…`` is not in any sensitive category —
        # default is ``"unknown"`` (not ``None``) by contract.
        assert intel["path_category"] == "unknown"

    def test_virtual_target_classifies_sensitive_category(self):
        # ``.ssh/`` fragment is in the credential_store category.
        intel = build_destination_intel(WRITE_FILE, "/home/user/.ssh/id_rsa")
        assert intel["path_category"] == "credential_store"


# ─────────────────────────────────────────────────────────────────────
# build_file_intel — end-to-end merge of payload + destination intel
# ─────────────────────────────────────────────────────────────────────


class TestBuildFileIntel:
    """Payload inspection + destination probe merged into one FileIntel."""

    def test_missing_host_file_regression_case(self, tmp_path: Path):
        # Regression pin for the original false-positive: a
        # WRITE_HOST_FILE to a path that DOES NOT exist must yield
        # destination_exists=False.  Previously FileIntel had no
        # destination fields → AE assumed overwrite → tagged
        # ``deletion`` → Guardian's ``confirm-before-delete`` limit
        # blocked a simple new-file write.
        target = tmp_path / "new_notes.txt"

        intel = build_file_intel(
            content="hello world\n",
            target=str(target),
            action_value=WRITE_HOST_FILE,
        )

        assert isinstance(intel, FileIntel)
        assert intel.destination_exists is False
        assert intel.destination_kind == "missing"
        assert intel.parent_kind == "directory"
        assert intel.extension == ".txt"
        assert intel.size_bytes == len("hello world\n".encode("utf-8"))
        # Plain text → language is not ``binary``; is_binary stays False.
        assert intel.is_binary is False
        assert intel.is_oversized is False

    def test_existing_host_file_is_overwrite(self, tmp_path: Path):
        target = tmp_path / "diary.md"
        target.write_text("old entry\n")

        intel = build_file_intel(
            content="new entry\n",
            target=str(target),
            action_value=WRITE_HOST_FILE,
        )

        assert intel.destination_exists is True
        assert intel.destination_kind == "file"
        assert intel.extension == ".md"

    def test_virtual_write_populates_payload_not_destination(self, tmp_path: Path):
        # Virtual WRITE_FILE path — inspector runs, destination stays
        # unknown.  The key property here is that ``extension`` and
        # ``language`` both come from the inspector / target string
        # and are consistent with each other.
        intel = build_file_intel(
            content="print('hello')\n",
            target="/home/user/hello.py",
            action_value=WRITE_FILE,
        )

        assert intel.destination_exists is None
        assert intel.destination_kind is None
        assert intel.extension == ".py"
        # Inspector should sniff Python on a ``.py`` + ``print(...)``
        # payload — if the sniffer ever changes we want to know.
        assert intel.language == "python"

    def test_no_mismatch_field_emitted(self):
        # FileIntel is a fact-gatherer, not a policy engine — it
        # surfaces ``extension`` and ``language`` as observations and
        # leaves the "do these disagree?" question to AE, because the
        # answer is contextual: a ``.md`` with Python content is
        # normal documentation, a ``.py`` with shell content is
        # suspicious, and no flat table can distinguish the two.
        # This test pins the contract — any future re-addition of a
        # hardcoded "mismatch" field trips it immediately.
        intel = build_file_intel(
            content="print('x')\n",
            target="/home/user/hello.py",
            action_value=WRITE_FILE,
        )
        assert not hasattr(intel, "extension_vs_language_mismatch")

    def test_container_extension_does_not_mark_code_as_suspicious(self, tmp_path: Path):
        # The design regression this whole change guards against:
        # writing Python-shaped content into a ``.md`` target (normal
        # documentation with fenced code blocks) must NOT produce any
        # deterministic "mismatch" signal on FileIntel.  Both fields
        # are populated; the PAIR is handed to AE verbatim.
        content = (
            "# Example\n\n```python\n"
            "def greet(name):\n    return f'hello {name}'\n"
            "```\n"
        )
        intel = build_file_intel(
            content=content,
            target="/home/user/notes.md",
            action_value=WRITE_FILE,
        )

        assert intel.extension == ".md"
        # We don't pin the sniffer's exact output — just that both
        # fields are present and FileIntel emits no categorical
        # "these disagree" boolean alongside them.
        assert intel.language is not None
        assert not hasattr(intel, "extension_vs_language_mismatch")

    def test_inspector_exception_returns_minimal_intel(self, tmp_path: Path):
        # A broken inspector must NOT fail-open the pipeline.  We fall
        # back to a FileIntel with destination fields populated and
        # payload fields at their "unknown / not analyzed" defaults.
        target = tmp_path / "file.py"

        def _raising(*args, **kwargs):
            raise RuntimeError("inspector exploded")

        with patch(
            "intentframe_action_bundle.files.file_intel.shield_inspect_code",
            side_effect=_raising,
        ):
            intel = build_file_intel(
                content="print('x')",
                target=str(target),
                action_value=WRITE_HOST_FILE,
            )

        assert intel.language is None
        assert intel.is_binary is False
        assert intel.is_oversized is False
        assert intel.signal_ids == ()
        assert intel.has_code_intel_findings is False
        # Destination probing is independent of the inspector — it
        # must still populate on failure so the prompt has something
        # concrete to condition on.
        assert intel.destination_exists is False
        assert intel.destination_kind == "missing"
        assert intel.extension == ".py"

    def test_sensitive_path_category_surfaces(self, tmp_path: Path):
        # ``.zshrc`` belongs to the ``shell_init`` category — DG
        # treats it as sensitive and AE's rubric cites the category
        # name directly, so pinning the classification here guards
        # against silent category renames.  VIRTUAL target keeps the
        # real user's ``~/.zshrc`` untouched.
        intel = build_file_intel(
            content="export PATH=...\n",
            target="/home/user/.zshrc",
            action_value=WRITE_FILE,
        )
        assert intel.path_category == "shell_init"

    def test_persistence_hook_category(self):
        intel = build_file_intel(
            content="[user]\n  email = x@y.com\n",
            target="/home/user/.gitconfig",
            action_value=WRITE_FILE,
        )
        assert intel.path_category == "persistence_hook"

    def test_credential_store_keychain_category(self):
        # Regression pin for the user's latest directive: macOS
        # keychain paths must classify as credential_store so AE
        # (and DG via the derived sensitive-fragment list) see them.
        intel = build_file_intel(
            content="blob",
            target="/home/user/library/keychains/login.keychain-db",
            action_value=WRITE_FILE,
        )
        assert intel.path_category == "credential_store"

    def test_symlink_target_truncated_at_bound(self, tmp_path: Path):
        # A pathologically long symlink target must be truncated by
        # FileIntel's validator so downstream payloads stay bounded.
        real = tmp_path / "real.txt"
        real.write_text("x")
        link = tmp_path / "link.txt"
        # Build a synthetic "long" target via patching os.readlink +
        # Path.resolve to a value longer than FILE_INTEL_PATH_MAX_LEN.
        long_target = "/" + ("a" * (FILE_INTEL_PATH_MAX_LEN + 100)) + "/file.txt"
        link.symlink_to(real)

        with patch(
            "intentframe_action_bundle.files.file_intel.Path.resolve",
            return_value=Path(long_target),
        ):
            intel = build_file_intel(
                content="x",
                target=str(link),
                action_value=WRITE_HOST_FILE,
            )

        assert intel.symlink_target_real_path is not None
        assert len(intel.symlink_target_real_path) <= FILE_INTEL_PATH_MAX_LEN

    def test_extension_truncated_at_bound(self, tmp_path: Path):
        # Absurdly long extension — ``_clip_string`` must bound it at
        # FILE_INTEL_EXTENSION_MAX_LEN so a malicious target name
        # cannot blow up the downstream payload.
        absurd_ext = "." + ("x" * (FILE_INTEL_EXTENSION_MAX_LEN + 50))
        target = tmp_path / f"file{absurd_ext}"
        target.write_text("x")

        intel = build_file_intel(
            content="x",
            target=str(target),
            action_value=WRITE_HOST_FILE,
        )

        assert intel.extension is not None
        assert len(intel.extension) <= FILE_INTEL_EXTENSION_MAX_LEN

    def test_floor_deny_prefix_populated(self):
        # A WRITE_HOST_FILE at ``/usr/local/bin/…`` matches the floor
        # deny list — AE's rubric cites this as a non-negotiable
        # red flag regardless of payload shape.
        intel = build_file_intel(
            content="#!/bin/sh\necho hi\n",
            target="/usr/local/bin/new_tool",
            action_value=WRITE_HOST_FILE,
        )
        assert intel.hits_floor_deny_prefix is True
