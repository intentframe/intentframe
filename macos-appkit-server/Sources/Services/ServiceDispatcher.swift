import ApplicationServices
import Foundation
import SQLite3

actor ServiceDispatcher {
    let calendar: CalendarService
    let reminders: RemindersService
    let contacts: ContactsService
    let system: SystemService
    let notes: NotesService
    let notifications: NotificationsService
    let messages: MessagesService
    let mail: MailService
    let mailCorpus: MailCorpusService

    init() {
        self.calendar = CalendarService()
        self.reminders = RemindersService()
        self.contacts = ContactsService()
        self.system = SystemService()
        self.notes = NotesService()
        self.notifications = NotificationsService()
        self.messages = MessagesService()
        self.mail = MailService()
        self.mailCorpus = MailCorpusService()
    }

    func requestAllAccess() async {
        async let calOk = calendar.requestAccess()
        async let remOk = reminders.requestAccess()
        async let conOk = contacts.requestAccess()
        async let notifOk = notifications.requestAccess()

        let results = await (calOk, remOk, conOk, notifOk)
        print("[platform-server] TCC access — calendar: \(results.0), reminders: \(results.1), contacts: \(results.2), notifications: \(results.3)")

        let fdaOk = Self.checkFullDiskAccess()
        let axOk = Self.checkAccessibility()
        print("[platform-server] Manual grants — full_disk_access: \(fdaOk), accessibility: \(axOk)")

        if !fdaOk {
            print("[platform-server] ⚠ Full Disk Access not granted — Notes reads and Messages reads will fail.")
            print("[platform-server]   Grant in: System Settings > Privacy & Security > Full Disk Access")
        }
        if !axOk {
            print("[platform-server] ⚠ Accessibility not granted.")
            print("[platform-server]   Grant in: System Settings > Privacy & Security > Accessibility")
        }
        print("[platform-server] ℹ Dark mode toggle also requires Automation permission for System Events.")
        print("[platform-server]   Grant in: System Settings > Privacy & Security > Automation")
    }

    // MARK: - Manual permission checks

    /// Full Disk Access: try opening Messages chat.db (most reliably TCC-gated file).
    static func checkFullDiskAccess() -> Bool {
        let chatDB = NSHomeDirectory() + "/Library/Messages/chat.db"
        var db: OpaquePointer?
        let rc = sqlite3_open_v2(chatDB, &db, SQLITE_OPEN_READONLY | SQLITE_OPEN_URI, nil)
        defer { sqlite3_close(db) }
        return rc == SQLITE_OK
    }

    /// Accessibility: AXIsProcessTrustedWithOptions does a fresh check (no stale cache).
    static func checkAccessibility() -> Bool {
        let opts = [kAXTrustedCheckOptionPrompt.takeUnretainedValue(): false] as CFDictionary
        return AXIsProcessTrustedWithOptions(opts)
    }

    // MARK: - Dispatch

    func execute(adapter: String, action: String, params: [String: AnyCodableValue]) async -> ExecuteResponse {
        switch adapter {
        case "calendar":
            return await calendar.execute(action: action, params: params)
        case "reminders":
            return await reminders.execute(action: action, params: params)
        case "contacts":
            return await contacts.execute(action: action, params: params)
        case "system":
            return await system.execute(action: action, params: params)
        case "notes":
            return await notes.execute(action: action, params: params)
        case "notifications":
            return await notifications.execute(action: action, params: params)
        case "messages":
            return await messages.execute(action: action, params: params)
        case "mail":
            return await mail.execute(action: action, params: params)
        case "mail_corpus":
            return await mailCorpus.execute(action: action, params: params)
        default:
            return .failure(.unknownAdapter(adapter))
        }
    }

    func rollback(adapter: String, rollbackId: String) async -> ExecuteResponse {
        switch adapter {
        case "calendar":
            return await calendar.rollback(rollbackId: rollbackId)
        case "reminders":
            return await reminders.rollback(rollbackId: rollbackId)
        case "contacts":
            return await contacts.rollback(rollbackId: rollbackId)
        case "notes":
            return await notes.rollback(rollbackId: rollbackId)
        case "mail":
            return await mail.rollback(rollbackId: rollbackId)
        default:
            return .failure(.unknownAdapter(adapter))
        }
    }

    // MARK: - Permission reporting

    func checkPermissions() async -> PermissionStatus {
        let calOk = await calendar.checkAccess()
        let remOk = await reminders.checkAccess()
        let conOk = await contacts.checkAccess()
        let notifOk = await notifications.checkAccess()
        let fdaOk = Self.checkFullDiskAccess()
        let axOk = Self.checkAccessibility()

        return PermissionStatus(
            calendar: PermissionDetail(
                granted: calOk,
                hint: calOk ? nil : "Grant in System Settings > Privacy & Security > Calendars"
            ),
            reminders: PermissionDetail(
                granted: remOk,
                hint: remOk ? nil : "Grant in System Settings > Privacy & Security > Reminders"
            ),
            contacts: PermissionDetail(
                granted: conOk,
                hint: conOk ? nil : "Grant in System Settings > Privacy & Security > Contacts"
            ),
            notifications: PermissionDetail(
                granted: notifOk,
                hint: notifOk ? nil : "Grant in System Settings > Notifications > IntentFrame Platform Server"
            ),
            full_disk_access: PermissionDetail(
                granted: fdaOk,
                hint: fdaOk ? nil : "Grant in System Settings > Privacy & Security > Full Disk Access"
            ),
            accessibility: PermissionDetail(
                granted: axOk,
                hint: axOk ? nil : "Grant in System Settings > Privacy & Security > Accessibility"
            )
        )
    }
}
