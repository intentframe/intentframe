"""
macOS Adapter Loading & Contract Test

Verifies every macOS adapter can:
  1. Be imported without errors
  2. Be instantiated (constructor succeeds, deps available)
  3. Declare supported_actions() — non-empty list of strings
  4. Declare manifest() — valid AdapterManifest with matching adapter_id
  5. Be a proper CapabilityAdapter subclass

Also tests:
  6. register_all_adapters() populates the plugin registry
  7. create_adapter() returns correct instances for all registered IDs
  8. No duplicate action strings across adapters (routing would break)
  9. pyobjc frameworks (EventKit, Contacts, Foundation) are importable

Usage:
    cd <project_root>
    .venv/bin/python demo/tests/test_adapters.py
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from executor.adapters.base import CapabilityAdapter
from executor.models import AdapterManifest

# All adapters declared in executor/platforms/macos/adapters/__init__.py
ADAPTER_SPECS: list[tuple[str, str, str]] = [
    ("files", "intentframe_executor_pack_macos.adapters.files", "FilesAdapter"),
    ("terminal", "intentframe_executor_pack_macos.adapters.terminal", "TerminalAdapter"),
    ("http_api", "intentframe_executor_pack_macos.adapters.http_api", "HttpApiAdapter"),
    ("user_io", "intentframe_executor_pack_macos.adapters.user_io", "UserIOAdapter"),
    ("notifications", "intentframe_executor_pack_macos.adapters.notifications", "NotificationsAdapter"),
    ("clipboard", "intentframe_executor_pack_macos.adapters.clipboard", "ClipboardAdapter"),
    ("shortcuts", "intentframe_executor_pack_macos.adapters.shortcuts", "ShortcutsAdapter"),
    ("spotlight", "intentframe_executor_pack_macos.adapters.spotlight", "SpotlightAdapter"),
    ("calendar", "intentframe_executor_pack_macos.adapters.calendar", "CalendarAdapter"),
    ("reminders", "intentframe_executor_pack_macos.adapters.reminders", "RemindersAdapter"),
    ("contacts", "intentframe_executor_pack_macos.adapters.contacts", "ContactsAdapter"),
    ("mail", "intentframe_executor_pack_macos.adapters.mail", "MailAdapter"),
    ("notes", "intentframe_executor_pack_macos.adapters.notes", "NotesAdapter"),
    ("messages", "intentframe_executor_pack_macos.adapters.messages", "MessagesAdapter"),
    ("browser", "intentframe_executor_pack_macos.adapters.browser", "BrowserAdapter"),
    ("system", "intentframe_executor_pack_macos.adapters.system", "SystemAdapter"),
]

# Adapters that rely on optional deps not in the default install
OPTIONAL_ADAPTERS = {"filesystem_watch"}


def header(title: str) -> None:
    print(f"\n{'─' * 72}")
    print(f"  {title}")
    print(f"{'─' * 72}")


def main() -> None:
    print("=" * 72)
    print("  macOS ADAPTER LOADING & CONTRACT TEST")
    print("=" * 72)

    results: list[tuple[str, bool, str]] = []
    all_instances: dict[str, CapabilityAdapter] = {}

    # ── Test 1-5: Per-adapter import, instantiation, and contract ─────
    header("PER-ADAPTER: import → instantiate → contract check")

    for adapter_id, module_path, class_name in ADAPTER_SPECS:
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)

            assert issubclass(cls, CapabilityAdapter), (
                f"{class_name} is not a CapabilityAdapter subclass"
            )

            instance = cls()
            all_instances[adapter_id] = instance

            actions = instance.supported_actions()
            assert isinstance(actions, list) and len(actions) > 0, (
                f"{adapter_id}.supported_actions() returned empty or non-list"
            )
            assert all(isinstance(a, str) for a in actions), (
                f"{adapter_id}.supported_actions() contains non-string elements"
            )

            manifest = instance.manifest()
            assert isinstance(manifest, AdapterManifest), (
                f"{adapter_id}.manifest() did not return AdapterManifest"
            )
            assert manifest.adapter_id == adapter_id, (
                f"manifest.adapter_id={manifest.adapter_id!r} != expected {adapter_id!r}"
            )

            print(f"  ✅ {adapter_id:<20} {class_name:<28} actions={actions}")
            results.append((adapter_id, True, ""))

        except Exception as exc:
            print(f"  ❌ {adapter_id:<20} {class_name:<28} {type(exc).__name__}: {exc}")
            results.append((adapter_id, False, f"{type(exc).__name__}: {exc}"))

    # ── Test 6: register_all_adapters() ───────────────────────────────
    header("REGISTRY: register_all_adapters()")

    from executor.adapters import _ADAPTER_REGISTRY, create_adapter
    _ADAPTER_REGISTRY.clear()

    from intentframe_executor_pack_macos.adapters import register_all_adapters
    register_all_adapters()

    registered_ids = sorted(_ADAPTER_REGISTRY.keys())
    expected_ids = sorted(aid for aid, _, _ in ADAPTER_SPECS)
    # filesystem_watch may also register if watchdog is installed
    for opt in OPTIONAL_ADAPTERS:
        if opt in registered_ids and opt not in expected_ids:
            expected_ids.append(opt)
            expected_ids.sort()

    missing = set(expected_ids) - set(registered_ids)
    extra = set(registered_ids) - set(expected_ids) - OPTIONAL_ADAPTERS

    if not missing and not extra:
        print(f"  ✅ {len(registered_ids)} adapters registered: {registered_ids}")
        results.append(("register_all_adapters", True, ""))
    else:
        msg = ""
        if missing:
            msg += f"Missing: {missing}. "
        if extra:
            msg += f"Unexpected: {extra}."
        print(f"  ❌ Registration mismatch. {msg}")
        results.append(("register_all_adapters", False, msg))

    # ── Test 7: create_adapter() round-trip ───────────────────────────
    header("FACTORY: create_adapter() for each registered ID")

    factory_ok = True
    for adapter_id in registered_ids:
        try:
            instance = create_adapter(adapter_id)
            assert isinstance(instance, CapabilityAdapter)
            print(f"  ✅ create_adapter({adapter_id!r})")
        except Exception as exc:
            if adapter_id in OPTIONAL_ADAPTERS:
                print(f"  ⚠️  create_adapter({adapter_id!r}): {exc} (optional — skipped)")
            else:
                print(f"  ❌ create_adapter({adapter_id!r}): {exc}")
                factory_ok = False

    results.append(("create_adapter_roundtrip", factory_ok, ""))

    # ── Test 8: No duplicate action strings ───────────────────────────
    header("UNIQUENESS: no duplicate action strings across adapters")

    action_owners: dict[str, str] = {}
    duplicates: list[str] = []

    for adapter_id, instance in all_instances.items():
        for action in instance.supported_actions():
            if action in action_owners:
                duplicates.append(
                    f"{action} claimed by both {action_owners[action]} and {adapter_id}"
                )
            else:
                action_owners[action] = adapter_id

    if not duplicates:
        print(f"  ✅ {len(action_owners)} unique actions across {len(all_instances)} adapters")
        results.append(("no_duplicate_actions", True, ""))
    else:
        for d in duplicates:
            print(f"  ❌ {d}")
        results.append(("no_duplicate_actions", False, "; ".join(duplicates)))

    # ── Test 9: pyobjc framework imports ──────────────────────────────
    header("PYOBJC: framework import verification")

    framework_tests = [
        ("EventKit", "import EventKit"),
        ("Contacts", "import Contacts"),
        ("Foundation (NSDate)", "from Foundation import NSDate"),
        ("Foundation (NSDateFormatter)", "from Foundation import NSDateFormatter"),
        ("Foundation (NSCalendar)", "from Foundation import NSCalendar"),
    ]

    for label, stmt in framework_tests:
        try:
            exec(stmt)  # noqa: S102 — test-only dynamic import
            print(f"  ✅ {label}")
            results.append((f"import_{label}", True, ""))
        except ImportError as exc:
            print(f"  ❌ {label}: {exc}")
            results.append((f"import_{label}", False, str(exc)))

    # ── Summary ───────────────────────────────────────────────────────
    header("SUMMARY")

    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)

    for name, ok, err in results:
        icon = "✅" if ok else "❌"
        status = "PASS" if ok else "FAIL"
        suffix = f"  ({err})" if err else ""
        print(f"  {icon} {status}  {name}{suffix}")

    print(f"\n  Results: {passed} passed, {failed} failed, {passed + failed} total")

    if failed:
        print("\n  ⚠️  Some tests failed — investigate above output")
        sys.exit(1)
    else:
        print("\n  All adapter tests passed.")


if __name__ == "__main__":
    main()
