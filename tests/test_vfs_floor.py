"""Tests for the non-negotiable deny-write floor on the VFS.

Covers:
    - ``resource_registry.floor.match_deny_prefix``:
        * exact match, prefix match, unrelated path miss;
        * canonicalization (trailing separator handling).
    - ``LocalVirtualFileSystem.write_file`` / ``delete_file`` reject
      writes that land under a floor prefix even when the mount is
      writable — the core gap Phase 7a closes.
    - ``APPEND_ROW`` path (which goes through ``write_file``) inherits
      the floor check for free.
    - Symmetry: every entry in ``intentframe_executor_pack_macos.sandbox.templates.NON_NEGOTIABLE_DENY_WRITE``
      is covered by ``resource_registry.floor.DENY_WRITE_PREFIXES`` so
      the sandbox and the file-tool floor cannot drift.

These tests use a temporary mount that shadows a real sensitive path by
pointing ``real_path`` directly at a floor location via symlink.  That
lets us exercise the deny-write floor without needing write permission
on ``/System`` etc.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from executor_sdk.exceptions import VirtualFileSystemError
from intentframe_executor_pack_macos.virtual_filesystem import LocalVirtualFileSystem
from intentframe_executor_pack_macos.sandbox.templates import NON_NEGOTIABLE_DENY_WRITE
from intentframe_executor_pack_macos.sandbox.venv import owner_home
from executor_sdk.services.virtual_filesystem import MountPointConfig
from resource_registry.floor import DENY_WRITE_PREFIXES, match_deny_prefix


# ─────────────────────────────────────────────────────────────────────────────
# match_deny_prefix unit tests
# ─────────────────────────────────────────────────────────────────────────────


class TestMatchDenyPrefix:
    def test_exact_match(self):
        assert match_deny_prefix("/System") == "/System"

    def test_nested_path_match(self):
        assert match_deny_prefix("/System/Library/Frameworks/Foo") == "/System"

    def test_unrelated_path_no_match(self):
        # /tmp realpath → /private/tmp on macOS; no floor entry covers it.
        assert match_deny_prefix("/private/tmp/foo") is None

    def test_prefix_boundary_not_substring(self):
        # "/usr2/local" must NOT match the "/usr" floor prefix — we require
        # a separator boundary so fake directories sharing a prefix substring
        # aren't caught.
        assert match_deny_prefix("/usr2/local/bin") is None

    def test_trailing_separator_normalized(self):
        assert match_deny_prefix("/System/") == "/System"

    def test_empty_input(self):
        assert match_deny_prefix("") is None

    def test_home_expansion_present(self):
        home = owner_home()
        if home is None:
            pytest.skip("No owning user HOME — running as bare root without SUDO_USER")
        # ~/Library/LaunchAgents is in the raw list; after expansion it must
        # appear as an absolute path matching the user's real HOME.
        candidate = os.path.realpath(os.path.join(home, "Library/LaunchAgents"))
        assert match_deny_prefix(candidate) is not None
        assert match_deny_prefix(candidate + "/com.evil.plist") is not None


# ─────────────────────────────────────────────────────────────────────────────
# VFS write/delete floor enforcement
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_mount(tmp_path: Path):
    """Build a writable LocalVirtualFileSystem pointed at a tmp dir.

    This is the "benign" mount used to prove that ordinary writes still
    succeed — it isolates floor-block assertions from mount-writability
    or path-arithmetic noise.
    """
    mount = MountPointConfig(
        virtual_path="/work/",
        real_path=str(tmp_path),
        writable=True,
    )
    return LocalVirtualFileSystem(mounts=[mount]), tmp_path


@pytest.fixture
def symlink_mount_to_floor(tmp_path: Path):
    """Build a writable mount whose real_path is a symlink into a floor prefix.

    Creating a symlink ``tmp_path/floor`` → ``/System`` lets us ask the VFS
    to write ``/work/x.txt`` and watch it resolve to ``/System/x.txt``
    *after* canonicalization.  The floor check must reject this even
    though the mount config declared ``writable=True``.

    We pick ``/System`` because it exists on every macOS host and is in
    both the narrower sandbox deny list and our floor; no privileged
    setup is needed since we never actually write there — the floor
    check fires first.
    """
    floor_target = "/System"
    symlink = tmp_path / "floor"
    symlink.symlink_to(floor_target)
    mount = MountPointConfig(
        virtual_path="/trap/",
        real_path=str(symlink),
        writable=True,
    )
    return LocalVirtualFileSystem(mounts=[mount])


class TestWriteFileFloor:
    def test_benign_write_succeeds(self, tmp_mount):
        vfs, tmp_path = tmp_mount
        vfs.write_file("/work/hello.txt", "hi")
        assert (tmp_path / "hello.txt").read_text() == "hi"

    def test_write_under_floor_is_denied(self, symlink_mount_to_floor):
        vfs = symlink_mount_to_floor
        with pytest.raises(VirtualFileSystemError) as exc:
            vfs.write_file("/trap/com.evil.plist", "pwned")
        assert "non-negotiable floor" in str(exc.value)

    def test_delete_under_floor_is_denied(self, symlink_mount_to_floor):
        vfs = symlink_mount_to_floor
        with pytest.raises(VirtualFileSystemError) as exc:
            vfs.delete_file("/trap/anything")
        assert "non-negotiable floor" in str(exc.value)

    def test_delete_nonexistent_benign_path_is_ok(self, tmp_mount):
        vfs, _tmp_path = tmp_mount
        # Idempotent: deleting a file that doesn't exist is fine when the
        # destination is outside the floor.
        assert vfs.delete_file("/work/nope.txt") is True

    def test_read_only_mount_still_rejected_first(self, tmp_path: Path):
        mount = MountPointConfig(
            virtual_path="/ro/",
            real_path=str(tmp_path),
            writable=False,
        )
        vfs = LocalVirtualFileSystem(mounts=[mount])
        with pytest.raises(VirtualFileSystemError) as exc:
            vfs.write_file("/ro/x.txt", "x")
        # Mount-writability gate runs before floor check — that's
        # intentional because an authoring error (read-only mount) is
        # more informative than a floor hit on the same path.
        assert "read-only" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────────────
# Sandbox ↔ registry symmetry
# ─────────────────────────────────────────────────────────────────────────────


class TestSandboxFloorSymmetry:
    """Drift guard: sandbox deny list must stay a subset of the registry floor.

    The sandbox Seatbelt profile (RUN_COMMAND) and the VFS floor
    (WRITE_FILE/DELETE_FILE) are enforced by different code paths but
    share the same semantic commitment: "no matter what policy says,
    these paths are never writable".  If someone adds a new entry to
    the sandbox list they must remember to mirror it (at least) in the
    registry floor.  This test turns that convention into a failing
    test rather than a silent gap.
    """

    def test_sandbox_deny_write_is_subset_of_registry_floor(self):
        # The sandbox list contains raw ``~``-prefixed entries; expand the
        # same way the floor module does so we compare canonical forms.
        expanded_sandbox: list[str] = []
        home = owner_home()
        for raw in NON_NEGOTIABLE_DENY_WRITE:
            if raw.startswith("~"):
                if home is None:
                    # Can't compare ~-entries without an owner; skip them
                    # rather than fail — the floor module drops the same
                    # entries under the same condition.
                    continue
                expanded = home + raw[1:]
            else:
                expanded = raw
            expanded_sandbox.append(os.path.realpath(expanded))

        missing = [p for p in expanded_sandbox if match_deny_prefix(p) is None]
        assert not missing, (
            f"Sandbox deny-write entries not covered by "
            f"resource_registry.floor.DENY_WRITE_PREFIXES: {missing}. "
            f"Add them to _RAW_DENY_WRITE_PREFIXES in resource_registry/floor.py."
        )

    def test_registry_floor_is_nonempty(self):
        # Sanity: at least the non-~ entries always expand.
        assert len(DENY_WRITE_PREFIXES) > 0
