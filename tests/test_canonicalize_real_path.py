"""Unit tests for :func:`resource_registry.floor.canonicalize_real_path`.

This is the single canonicalization primitive shared between the
Deterministic Guardian host-file floor gates, ``HostFileChecker``, and
``HostFilesAdapter``.  All three must agree on the canonical string form
before calling :func:`match_deny_prefix`, otherwise a symlink escape
could pass one layer and fail another.

Covers:

- empty-string passthrough (preserves caller's ability to distinguish
  "no target" from a canonical empty path);
- ``~`` expansion via :func:`os.path.expanduser`;
- ``Path.resolve(strict=False)`` semantics for existing symlink prefixes
  (e.g. ``/tmp`` → ``/private/tmp`` on macOS);
- nonexistent-leaf preservation (typical ``WRITE_HOST_FILE`` target —
  the file doesn't exist yet);
- relative-path handling (paths become absolute).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from resource_registry.floor import canonicalize_real_path


class TestEmptyPassthrough:
    def test_empty_string_returns_empty(self):
        # Callers rely on this to distinguish "no target" from a
        # canonicalized empty path.  Changing this behaviour would
        # require auditing every callsite that treats "" as sentinel.
        assert canonicalize_real_path("") == ""


class TestHomeExpansion:
    def test_tilde_expanded_to_home(self):
        home = os.path.expanduser("~")
        result = canonicalize_real_path("~/Documents/foo.txt")
        assert result.startswith(home), (
            f"expected result under HOME ({home!r}), got {result!r}"
        )
        assert result.endswith(os.sep + "foo.txt")

    def test_bare_tilde_expanded(self):
        home_canonical = str(Path(os.path.expanduser("~")).resolve(strict=False))
        assert canonicalize_real_path("~") == home_canonical


class TestSymlinkResolution:
    def test_tmp_resolved_on_macos(self):
        # macOS: /tmp is a symlink to /private/tmp.  Canonicalizer must
        # follow it so DG's floor comparison sees the same form as the
        # adapter will at I/O time.
        # Skip on non-Darwin platforms (Linux has /tmp as a real dir).
        if not Path("/private/tmp").exists():
            pytest.skip("/private/tmp not present; not macOS")
        result = canonicalize_real_path("/tmp")
        assert result == "/private/tmp"

    def test_tmp_subpath_resolved(self):
        if not Path("/private/tmp").exists():
            pytest.skip("/private/tmp not present; not macOS")
        result = canonicalize_real_path("/tmp/intentframe-test-nonexistent")
        assert result == "/private/tmp/intentframe-test-nonexistent"


class TestNonexistentLeaf:
    def test_nonexistent_leaf_preserved(self, tmp_path):
        # Typical WRITE_HOST_FILE target: parent exists, leaf doesn't.
        # Canonicalizer must resolve the parent and re-join the literal
        # leaf name so "about to be created" paths work correctly.
        leaf = "will-be-created.txt"
        target = tmp_path / leaf
        assert not target.exists()
        result = canonicalize_real_path(str(target))
        assert Path(result).name == leaf
        # Parent must be the canonical form of tmp_path.
        assert str(Path(result).parent) == str(tmp_path.resolve())

    def test_nonexistent_parent_and_leaf(self, tmp_path):
        # Deeper nonexistent chain — still canonicalizes without error.
        target = tmp_path / "does" / "not" / "exist.txt"
        result = canonicalize_real_path(str(target))
        assert result.endswith(os.sep + "exist.txt")


class TestRelativePaths:
    def test_relative_path_becomes_absolute(self, tmp_path, monkeypatch):
        # ``Path.resolve`` makes relative paths absolute relative to cwd.
        # Pinning cwd makes this deterministic across CI environments.
        monkeypatch.chdir(tmp_path)
        result = canonicalize_real_path("foo/bar.txt")
        assert os.path.isabs(result)
        assert result.endswith(os.sep + "bar.txt")


class TestIdempotence:
    def test_canonicalizing_twice_is_stable(self, tmp_path):
        # match_deny_prefix calls expect the caller to already have
        # canonicalized.  Passing a canonical path back through must
        # yield the same string so audit logs stay deterministic.
        raw = str(tmp_path / "about-to-write.txt")
        once = canonicalize_real_path(raw)
        twice = canonicalize_real_path(once)
        assert once == twice


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
