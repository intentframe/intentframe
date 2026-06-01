"""
Executor Pipeline Test -- exercises the production executor directly.

No AI, no Guardian, no Analysis Engine. This test shows what happens
INSIDE the executor after Guardian says ALLOW:

    IntentFrame -> Bridge -> HMAC sign -> Gateway auth
    -> Dispatch -> Adapter -> VFS -> real I/O -> audit trail

Tests:
    1. LIST_DIRECTORY  -- list files via VFS
    2. READ_FILE       -- read file contents via VFS
    3. APPEND_ROW      -- write to expense tracker via VFS
    4. READ_FILE       -- verify the append actually wrote
    5. READ_FILE (bad) -- path traversal attempt (no mount)
    6. WRITE_FILE      -- attempt write on read-only mount
    7. Unknown action  -- SEND_EMAIL (no adapter registered)
    8. Bad HMAC        -- forged signature rejected by gateway
    9. Audit trail     -- dump all entries from SQLite
   10. Hash chain      -- verify tamper-evident integrity

Usage:
    cd demo && python tests/test_executor.py
"""

from __future__ import annotations

import hashlib
import hmac
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
DEMO_ROOT = Path(__file__).parent.parent.resolve()
PROJECT_ROOT = DEMO_ROOT.parent
sys.path.insert(0, str(DEMO_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from intentframe_native_kit.resource_registry import ResourceRegistry, ResourceMount

from intentframe_native_kit.action_registry import ActionType
from intentframe_core import IntentFrame
from intentframe_native_kit.extras.bridge import ExecutorBridge

# ── Config ────────────────────────────────────────────────────────────────────
DEMO_DATA = DEMO_ROOT / "demo_data"
DB_DIR = Path(tempfile.mkdtemp(prefix="intentframe_test_executor_"))
DB_PATH = str(DB_DIR / "test_executor.db")

_registry = ResourceRegistry()
_registry.create_workspace(
    workspace_id="test_executor",
    mounts=[
        ResourceMount(virtual_path="/invoices/", real_path="demo_data", file_filter="*.md"),
        ResourceMount(virtual_path="/expense_tracker.md", real_path="demo_data/expense_tracker.md", writable=True),
    ],
    base_path=DEMO_ROOT,
)
EXECUTOR_VIEW = _registry.executor_view("test_executor")

# ── Helpers ───────────────────────────────────────────────────────────────────

_SEQ = 0


def _next_seq() -> int:
    global _SEQ
    _SEQ += 1
    return _SEQ


def intent(
    action: ActionType,
    target: str,
    reason: str = "",
    data: dict | None = None,
) -> IntentFrame:
    """Build an IntentFrame with auto-incrementing sequence.

    ``path`` is the executable contract carried in ``data`` (the field file
    adapters read). ``target`` is display/audit only; the executor no longer
    translates it into ``params["path"]``. For these file-oriented demo cases
    the path equals the target, so it is mirrored into ``data["path"]``.
    """
    merged = dict(data or {})
    merged.setdefault("path", target)
    return IntentFrame(
        action=action,
        target=target,
        reason=reason,
        data=merged or None,
        agent_id="test-executor-agent",
        session_id="test-session-001",
        sequence_id=_next_seq(),
    )


def header(title: str) -> None:
    print(f"\n{'─' * 72}")
    print(f"  {title}")
    print(f"{'─' * 72}")


def result_block(label: str, result) -> None:
    icon = "✅" if result.success else "❌"
    print(f"  {icon} {label}")
    print(f"     success    = {result.success}")
    if result.data:
        # Truncate long values for readability
        for k, v in result.data.items():
            val_str = str(v)
            if len(val_str) > 120:
                val_str = val_str[:120] + "..."
            print(f"     data.{k:<10} = {val_str}")
    if result.error:
        print(f"     error      = {result.error}")
    if result.execution_id:
        print(f"     exec_id    = {result.execution_id}")


# ═════════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════════

def main():
    # Reset expense tracker so APPEND_ROW has a clean slate
    original = DEMO_DATA / "expense_tracker_original_locked.md"
    target = DEMO_DATA / "expense_tracker.md"
    if original.exists():
        shutil.copy(original, target)

    print("=" * 72)
    print("  EXECUTOR PIPELINE TEST")
    print("  (No AI, no Guardian -- raw executor internals)")
    print("=" * 72)
    print(f"  Demo root : {DEMO_ROOT}")
    print(f"  SQLite DB : {DB_PATH}")
    print(f"  Mounts    : {len(EXECUTOR_VIEW.mounts)}")
    for m in EXECUTOR_VIEW.mounts:
        rw = "RW" if m.writable else "RO"
        print(f"    {m.virtual_path:<25} -> {m.real_path:<35} [{rw}]")

    # ── Create bridge ────────────────────────────────────────────────────
    header("CREATING BRIDGE (wiring production gateway)")
    bridge = ExecutorBridge.create_for_demo(
        executor_view=EXECUTOR_VIEW,
        db_path=DB_PATH,
    )
    print("  Bridge created successfully.")
    print("  Pipeline: IntentFrame -> HMAC sign -> Gateway -> Auth verify")
    print("            -> Dispatch -> Adapter -> VFS -> real I/O -> audit")

    results = {}

    # ── Test 1: LIST_DIRECTORY ───────────────────────────────────────────
    header("TEST 1: LIST_DIRECTORY /invoices/")
    print("  Expected: list of .md files in demo_data/")
    r = bridge.forward(intent(ActionType.LIST_DIRECTORY, "/invoices/", "List invoice files"))
    result_block("LIST_DIRECTORY", r)
    results["list_dir"] = r

    # ── Test 2: READ_FILE ────────────────────────────────────────────────
    header("TEST 2: READ_FILE /invoices/office_depot.md")
    print("  Expected: markdown content of the Office Depot invoice")
    r = bridge.forward(intent(ActionType.READ_FILE, "/invoices/office_depot.md", "Read invoice"))
    result_block("READ_FILE", r)
    results["read_file"] = r

    # ── Test 3: APPEND_ROW ───────────────────────────────────────────────
    header("TEST 3: APPEND_ROW /expense_tracker.md")
    print("  Expected: new row appended to expense tracker")
    r = bridge.forward(intent(
        ActionType.APPEND_ROW,
        "/expense_tracker.md",
        "Record processed invoice",
        data={"vendor": "TestVendor Inc", "amount": 1234.56, "date": "2026-02-15", "status": "Processed"},
    ))
    result_block("APPEND_ROW", r)
    results["append_row"] = r

    # ── Test 4: READ_FILE (verify append) ────────────────────────────────
    header("TEST 4: READ_FILE /expense_tracker.md (verify append)")
    print("  Expected: expense tracker contains 'TestVendor Inc' row")
    r = bridge.forward(intent(ActionType.READ_FILE, "/expense_tracker.md", "Verify append"))
    result_block("READ_FILE (verify)", r)
    if r.success and "TestVendor" in r.data.get("content", ""):
        print("  ✅ APPEND VERIFIED -- 'TestVendor Inc' found in expense tracker")
    else:
        print("  ❌ APPEND NOT VERIFIED -- 'TestVendor Inc' not found")
    results["verify_append"] = r

    # ── Test 5: READ_FILE (path outside mounts) ──────────────────────────
    header("TEST 5: READ_FILE /etc/passwd (no mount -- should fail)")
    print("  Expected: failure -- no mount point for /etc/passwd")
    r = bridge.forward(intent(ActionType.READ_FILE, "/etc/passwd", "Path traversal attempt"))
    result_block("READ_FILE (bad path)", r)
    if not r.success:
        print("  ✅ CORRECTLY REJECTED -- VFS prevented path traversal")
    else:
        print("  ❌ SHOULD HAVE FAILED -- path traversal was not blocked!")
    results["bad_path"] = r

    # ── Test 6: WRITE_FILE on read-only mount ────────────────────────────
    header("TEST 6: WRITE_FILE /invoices/hacked.md (read-only mount)")
    print("  Expected: failure -- /invoices/ mount is read-only")
    r = bridge.forward(intent(
        ActionType.WRITE_FILE,
        "/invoices/hacked.md",
        "Try writing to read-only mount",
        data={"content": "This should not be written"},
    ))
    result_block("WRITE_FILE (read-only)", r)
    if not r.success:
        print("  ✅ CORRECTLY REJECTED -- read-only mount enforced by VFS")
    else:
        print("  ❌ SHOULD HAVE FAILED -- read-only was not enforced!")
    results["readonly_write"] = r

    # ── Test 7: Unknown action ───────────────────────────────────────────
    header("TEST 7: SEND_EMAIL (no adapter registered)")
    print("  Expected: failure -- no adapter handles SEND_EMAIL")
    r = bridge.forward(intent(ActionType.SEND_EMAIL, "ceo@example.com", "Send payment confirmation"))
    result_block("SEND_EMAIL (unknown)", r)
    if not r.success:
        print("  ✅ CORRECTLY REJECTED -- unknown action type")
    else:
        print("  ❌ SHOULD HAVE FAILED -- unregistered action was executed!")
    results["unknown_action"] = r

    # ── Test 8: Bad HMAC signature ───────────────────────────────────────
    header("TEST 8: FORGED HMAC SIGNATURE")
    print("  Expected: gateway rejects -- HMAC mismatch")

    # Manually build a request with a bad signature
    from executor_sdk.models import AuthorizationProof, ExecutionRequest, RequestMetadata

    bad_request = ExecutionRequest(
        action_type="LIST_DIRECTORY",
        target="/invoices/",
        params={"path": "/invoices/"},
        reason="Trying with forged HMAC",
        authorization=AuthorizationProof(
            scheme="guardian_hmac",
            token="test-session:99:LIST_DIRECTORY:definitely_not_a_valid_signature",
        ),
        metadata=RequestMetadata(
            agent_id="attacker",
            session_id="forged-session",
        ),
    )

    # Call gateway directly (bypass bridge translation)
    r_bad = bridge._run_async(bridge._gateway.handle(bad_request))
    icon = "✅" if not r_bad.success else "❌"
    print(f"  {icon} FORGED HMAC")
    print(f"     success = {r_bad.success}")
    print(f"     error   = {r_bad.error}")
    if not r_bad.success:
        print("  ✅ CORRECTLY REJECTED -- forged signature detected")
    else:
        print("  ❌ SHOULD HAVE FAILED -- forged signature was accepted!")

    # ── Test 9: Audit trail ──────────────────────────────────────────────
    header("TEST 9: AUDIT TRAIL (append-only SQLite dump)")
    print(f"  Database: {DB_PATH}")
    print(f"  Design: fully append-only -- 2 rows per execution (STARTED + outcome)")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT execution_id, action_type, adapter_id, status, "
        "result_summary, duration_ms, entry_hash "
        "FROM audit_log ORDER BY id"
    ).fetchall()

    print(f"  Entries: {len(rows)}  (expect 2 per dispatched execution)\n")
    print(f"  {'#':<3} {'ACTION':<16} {'ADAPTER':<18} {'STATUS':<10} {'ms':>5}  RESULT")
    print(f"  {'─'*3} {'─'*16} {'─'*18} {'─'*10} {'─'*5}  {'─'*20}")
    for i, row in enumerate(rows, 1):
        summary = (row["result_summary"] or "")[:30]
        ms = row["duration_ms"] if row["duration_ms"] is not None else ""
        ms_str = f"{ms:>5}" if ms != "" else "    -"
        print(f"  {i:<3} {row['action_type']:<16} {row['adapter_id']:<18} {row['status']:<10} {ms_str}  {summary}")

    # Security events
    sec_rows = conn.execute(
        "SELECT event_type, source_info, details, timestamp "
        "FROM security_events ORDER BY id"
    ).fetchall()

    if sec_rows:
        print(f"\n  Security Events: {len(sec_rows)}")
        print(f"  {'#':<3} {'EVENT TYPE':<20} {'SOURCE':<20} DETAILS")
        print(f"  {'─'*3} {'─'*20} {'─'*20} {'─'*30}")
        for i, row in enumerate(sec_rows, 1):
            details = (row["details"] or "")[:50]
            print(f"  {i:<3} {row['event_type']:<20} {row['source_info']:<20} {details}")

    conn.close()

    # ── Test 10: Hash chain integrity ────────────────────────────────────
    header("TEST 10: HASH CHAIN INTEGRITY")
    print("  Verifying tamper-evident audit trail...")

    from intentframe_native_kit.intentframe_executor_pack_macos.audit_logger import SQLiteAuditLogger
    logger = SQLiteAuditLogger(db_path=DB_PATH)
    chain_valid = bridge._run_async(logger.verify_chain_integrity())
    logger.close()

    if chain_valid:
        print("  ✅ HASH CHAIN VALID -- audit trail is tamper-free")
    else:
        print("  ❌ HASH CHAIN BROKEN -- audit trail may have been tampered with!")

    # ── Summary ──────────────────────────────────────────────────────────
    header("SUMMARY")
    tests = [
        ("LIST_DIRECTORY",         results["list_dir"].success,         True),
        ("READ_FILE",              results["read_file"].success,        True),
        ("APPEND_ROW",             results["append_row"].success,       True),
        ("Verify append",          "TestVendor" in results["verify_append"].data.get("content", ""), True),
        ("Path traversal blocked", not results["bad_path"].success,     True),
        ("Read-only enforced",     not results["readonly_write"].success, True),
        ("Unknown action rejected",not results["unknown_action"].success, True),
        ("Forged HMAC rejected",   not r_bad.success,                   True),
        ("Hash chain intact",      chain_valid,                         True),
    ]

    passed = 0
    failed = 0
    for name, actual, expected in tests:
        ok = actual == expected
        icon = "✅" if ok else "❌"
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"  {icon} {status}  {name}")

    print(f"\n  Results: {passed} passed, {failed} failed, {passed + failed} total")
    print(f"  Database: {DB_PATH}")

    if failed > 0:
        print("\n  ⚠️  Some tests failed -- investigate above output")
        sys.exit(1)
    else:
        print("\n  All executor pipeline tests passed.")

    # Restore expense tracker
    if original.exists():
        shutil.copy(original, target)


if __name__ == "__main__":
    main()
