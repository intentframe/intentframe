"""Unit tests for :class:`intentframe_native_kit.intentframe_executor_pack_macos.adapters.host_files.HostFilesAdapter`.

The adapter is the final wall before real-path I/O.  It runs two
independent checks on every call:

1. ``resource_registry.floor.match_deny_prefix`` on writes/deletes
   (non-negotiable floor — ``/etc/sudoers``, shell rc files, ``~/.ssh``,
   launchd plists, etc.).
2. ``HostFilesConfig.allowed_{read,write}_paths`` (the executor YAML
   ceiling — reads must land under ``allowed_read_paths``, mutations
   under ``allowed_write_paths``).

Both run regardless of upstream guardian decisions; a compromised
pipeline cannot escape these walls.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from intentframe_native_kit.action_registry import ActionType
from intentframe_native_kit.intentframe_executor_pack_macos.adapters.host_files import HostFilesAdapter
from intentframe_native_kit.intentframe_executor_pack_macos.adapters.host_files_config import HostFilesConfig


def _run(adapter: HostFilesAdapter, action, params):
    return asyncio.run(adapter.execute(action.value, params))


@pytest.fixture
def sandbox(tmp_path: Path):
    """Fresh ``HostFilesAdapter`` with reads and writes bound to tmp_path."""
    cfg = HostFilesConfig(
        allowed_read_paths=[str(tmp_path)],
        allowed_write_paths=[str(tmp_path)],
    )
    return HostFilesAdapter(host_files_options=cfg), tmp_path


# ═══════════════════════════════════════════════════════════════════════
# Happy-path I/O
# ═══════════════════════════════════════════════════════════════════════

class TestReadWriteListDelete:
    def test_write_then_read_roundtrip(self, sandbox):
        adapter, root = sandbox
        target = root / "hello.txt"
        w = _run(adapter, ActionType.WRITE_HOST_FILE, {
            "path": str(target), "content": "hi there",
        })
        assert w.success, w.error
        assert target.read_text() == "hi there"

        r = _run(adapter, ActionType.READ_HOST_FILE, {"path": str(target)})
        assert r.success, r.error
        assert r.data["content"] == "hi there"
        assert r.data["total_lines"] == 1

    def test_list_directory(self, sandbox):
        adapter, root = sandbox
        (root / "a.txt").write_text("a")
        (root / "b.txt").write_text("b")
        sub = root / "sub"
        sub.mkdir()
        r = _run(adapter, ActionType.LIST_HOST_DIRECTORY, {"path": str(root)})
        assert r.success, r.error
        names = {e["name"] for e in r.data["entries"]}
        assert {"a.txt", "b.txt", "sub"} <= names

    def test_delete_existing_file(self, sandbox):
        adapter, root = sandbox
        target = root / "gone.txt"
        target.write_text("x")
        r = _run(adapter, ActionType.DELETE_HOST_FILE, {"path": str(target)})
        assert r.success, r.error
        assert r.data["deleted"] is True
        assert not target.exists()

    def test_delete_missing_file_is_idempotent(self, sandbox):
        adapter, root = sandbox
        target = root / "never-existed.txt"
        r = _run(adapter, ActionType.DELETE_HOST_FILE, {"path": str(target)})
        assert r.success, r.error
        assert r.data["deleted"] is False

    def test_read_truncation_and_paging(self, sandbox):
        adapter, root = sandbox
        target = root / "many.txt"
        target.write_text("\n".join(f"line{i}" for i in range(100)) + "\n")
        r = _run(adapter, ActionType.READ_HOST_FILE, {
            "path": str(target), "offset": 0, "limit": 10,
        })
        assert r.success, r.error
        assert r.data["truncated"] is True
        assert r.data["total_lines"] == 100
        assert r.data["content"].count("\n") == 10


# ═══════════════════════════════════════════════════════════════════════
# Wall 1: deny-write floor
# ═══════════════════════════════════════════════════════════════════════
# The floor fires on mutations *before* the executor YAML ceiling, so
# even if an operator mistakenly puts ``/etc/`` in allowed_write_paths
# the adapter still refuses.

class TestFloorWall:
    def test_write_to_sudoers_blocked_even_if_in_write_allowlist(self):
        # Construct an adapter whose *executor* allowlist includes /etc —
        # an operator config mistake.  The floor must still refuse.
        cfg = HostFilesConfig(
            allowed_read_paths=["/etc"],
            allowed_write_paths=["/etc"],
        )
        adapter = HostFilesAdapter(host_files_options=cfg)
        r = _run(adapter, ActionType.WRITE_HOST_FILE, {
            "path": "/etc/sudoers",
            "content": "x",
        })
        assert not r.success
        assert "floor" in r.error.lower()

    def test_delete_of_sudoers_blocked_even_if_in_write_allowlist(self):
        cfg = HostFilesConfig(
            allowed_read_paths=["/etc"],
            allowed_write_paths=["/etc"],
        )
        adapter = HostFilesAdapter(host_files_options=cfg)
        r = _run(adapter, ActionType.DELETE_HOST_FILE, {"path": "/etc/sudoers"})
        assert not r.success
        assert "floor" in r.error.lower()


# ═══════════════════════════════════════════════════════════════════════
# Wall 2: executor YAML ceiling
# ═══════════════════════════════════════════════════════════════════════

class TestCeilingWall:
    def test_write_outside_allowlist_blocked(self, tmp_path):
        inside = tmp_path / "inside"
        outside = tmp_path / "outside"
        inside.mkdir()
        outside.mkdir()
        cfg = HostFilesConfig(
            allowed_read_paths=[str(inside)],
            allowed_write_paths=[str(inside)],
        )
        adapter = HostFilesAdapter(host_files_options=cfg)
        r = _run(adapter, ActionType.WRITE_HOST_FILE, {
            "path": str(outside / "escape.txt"),
            "content": "x",
        })
        assert not r.success
        assert "allowlist" in r.error.lower()

    def test_read_outside_allowlist_blocked(self, tmp_path):
        # Read allowlist is separate from write allowlist; a read outside
        # either list is rejected.
        inside = tmp_path / "inside"
        outside = tmp_path / "outside"
        inside.mkdir()
        outside.mkdir()
        cfg = HostFilesConfig(
            allowed_read_paths=[str(inside)],
            allowed_write_paths=[str(inside)],
        )
        adapter = HostFilesAdapter(host_files_options=cfg)
        (outside / "secret.txt").write_text("x")
        r = _run(adapter, ActionType.READ_HOST_FILE, {
            "path": str(outside / "secret.txt"),
        })
        assert not r.success

    def test_empty_write_allowlist_refuses_all_writes(self, tmp_path):
        # Zero-trust mode: empty list means *no* host-file writes permitted.
        cfg = HostFilesConfig(allowed_read_paths=[], allowed_write_paths=[])
        adapter = HostFilesAdapter(host_files_options=cfg)
        r = _run(adapter, ActionType.WRITE_HOST_FILE, {
            "path": str(tmp_path / "x.txt"),
            "content": "x",
        })
        assert not r.success

    def test_prefix_match_respects_separator_boundary(self, tmp_path):
        # /foo-evil must NOT match /foo as an allowlist prefix.
        allowed = tmp_path / "allowed"
        sibling = tmp_path / "allowed-evil"
        allowed.mkdir()
        sibling.mkdir()
        cfg = HostFilesConfig(
            allowed_read_paths=[str(allowed)],
            allowed_write_paths=[str(allowed)],
        )
        adapter = HostFilesAdapter(host_files_options=cfg)
        r = _run(adapter, ActionType.WRITE_HOST_FILE, {
            "path": str(sibling / "sneaky.txt"),
            "content": "x",
        })
        assert not r.success


# ═══════════════════════════════════════════════════════════════════════
# Input validation
# ═══════════════════════════════════════════════════════════════════════

class TestInputValidation:
    def test_missing_path_parameter(self, sandbox):
        adapter, _ = sandbox
        r = _run(adapter, ActionType.READ_HOST_FILE, {})
        assert not r.success
        assert "path" in r.error.lower()

    def test_write_non_string_content_rejected(self, sandbox):
        adapter, root = sandbox
        r = _run(adapter, ActionType.WRITE_HOST_FILE, {
            "path": str(root / "x.txt"),
            "content": 12345,
        })
        assert not r.success
        assert "content" in r.error.lower()

    def test_read_directory_rejected_with_hint(self, sandbox):
        adapter, root = sandbox
        sub = root / "sub"
        sub.mkdir()
        r = _run(adapter, ActionType.READ_HOST_FILE, {"path": str(sub)})
        assert not r.success
        assert "directory" in r.error.lower()

    def test_delete_directory_refused(self, sandbox):
        adapter, root = sandbox
        sub = root / "sub"
        sub.mkdir()
        r = _run(adapter, ActionType.DELETE_HOST_FILE, {"path": str(sub)})
        assert not r.success
        assert "directory" in r.error.lower()


class TestContentDecoding:
    """Parity with LocalVirtualFileSystem.read_file:

    - PDFs decode via pymupdf text extraction rather than raw bytes.
    - Known binary MIME types are refused with a readable reason.
    - Plain text is decoded as UTF-8 explicitly so a non-utf-8 byte
      sequence surfaces as "cannot read binary file" rather than the
      default-locale decoder's traceback.
    """

    def test_utf8_text_round_trips(self, sandbox):
        adapter, root = sandbox
        target = root / "utf8.txt"
        target.write_bytes("héllo — world\n".encode("utf-8"))
        r = _run(adapter, ActionType.READ_HOST_FILE, {"path": str(target)})
        assert r.success, r.error
        assert "héllo" in r.data["content"]

    def test_non_utf8_bytes_rejected_as_binary(self, sandbox):
        adapter, root = sandbox
        target = root / "latin1.txt"
        # 0xff is invalid as a leading UTF-8 byte; triggers UnicodeDecodeError.
        target.write_bytes(b"\xff\xfe\x00plain")
        r = _run(adapter, ActionType.READ_HOST_FILE, {"path": str(target)})
        assert not r.success
        assert "binary" in r.error.lower()

    def test_binary_mime_rejected_before_decode(self, sandbox):
        adapter, root = sandbox
        # .png is in _BINARY_UNSUPPORTED; refuse by MIME without reading.
        target = root / "pixel.png"
        target.write_bytes(b"\x89PNG\r\n\x1a\n")
        r = _run(adapter, ActionType.READ_HOST_FILE, {"path": str(target)})
        assert not r.success
        assert "binary" in r.error.lower()
        assert "image/png" in r.error

    def test_pdf_text_extraction(self, sandbox):
        pymupdf = pytest.importorskip("pymupdf")
        adapter, root = sandbox
        target = root / "sample.pdf"
        # Build a tiny single-page PDF with known text so the assertion
        # is independent of external fixtures / network state.
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hello from pymupdf")
        doc.save(str(target))
        doc.close()

        r = _run(adapter, ActionType.READ_HOST_FILE, {"path": str(target)})
        assert r.success, r.error
        assert "Hello from pymupdf" in r.data["content"]

    def test_pagination_still_applies_to_decoded_content(self, sandbox):
        # The MIME-aware decode path must not bypass offset/limit paging.
        adapter, root = sandbox
        target = root / "many.txt"
        target.write_text("\n".join(f"l{i}" for i in range(20)) + "\n")
        r = _run(adapter, ActionType.READ_HOST_FILE, {
            "path": str(target), "offset": 5, "limit": 3,
        })
        assert r.success, r.error
        assert r.data["offset"] == 5
        assert r.data["limit"] == 3
        assert r.data["total_lines"] == 20
        assert r.data["content"].splitlines() == ["l5", "l6", "l7"]


class TestManifest:
    def test_supported_actions_match_category(self, sandbox):
        adapter, _ = sandbox
        actions = set(adapter.supported_actions())
        assert actions == {
            ActionType.READ_HOST_FILE.value,
            ActionType.WRITE_HOST_FILE.value,
            ActionType.DELETE_HOST_FILE.value,
            ActionType.LIST_HOST_DIRECTORY.value,
        }

    def test_manifest_advertises_host_files_id(self, sandbox):
        adapter, _ = sandbox
        manifest = adapter.manifest()
        assert manifest.adapter_id == "host_files"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
