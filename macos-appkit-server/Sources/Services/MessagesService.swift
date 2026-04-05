import AppKit
import Foundation
import SQLite3

/// Sends messages via Messages.app and reads history from chat.db (SQLite).
///
/// SEND_MESSAGE runs via `/usr/bin/osascript` as a subprocess so the Vapor
/// event loop is never blocked. READ_MESSAGES reads chat.db directly via
/// SQLite (no AppleScript needed).
actor MessagesService {

    private static let osascriptPath = "/usr/bin/osascript"
    private static let scriptTimeout: TimeInterval = 30
    private static let messagesBundleId = "com.apple.MobileSMS"

    private static let chatDB: String = {
        "\(NSHomeDirectory())/Library/Messages/chat.db"
    }()

    private static let appleEpochOffset: TimeInterval = 978307200

    func execute(action: String, params: [String: AnyCodableValue]) async -> ExecuteResponse {
        switch action {
        case "SEND_MESSAGE":
            return await sendMessage(params)
        case "READ_MESSAGES":
            return readMessages(params)
        default:
            return .failure(.unknownAction(action, adapter: "messages"))
        }
    }

    func rollback(rollbackId: String) async -> ExecuteResponse {
        return .failure("Message send is irreversible")
    }

    // MARK: - Send Message (osascript subprocess, non-blocking)

    private func sendMessage(_ params: [String: AnyCodableValue]) async -> ExecuteResponse {
        guard let to = params["to"]?.stringValue, !to.isEmpty else {
            return .failure(.invalidInput("to is required"))
        }
        guard let text = params["text"]?.stringValue, !text.isEmpty else {
            return .failure(.invalidInput("text is required"))
        }
        let service = params["service"]?.stringValue ?? "iMessage"

        let textExpr = Self.buildTextExpression(text)

        let script = """
            tell application "Messages"
                set targetService to first service whose service type is \(service)
                set targetBuddy to buddy "\(Self.escapeForAS(to))" of targetService
                send \(textExpr) to targetBuddy
            end tell
        """

        let msgsWasRunning = await Self.isMessagesRunning()
        let result = await Self.runOsascript(script)
        if !msgsWasRunning { await Self.hideMessages() }

        switch result {
        case .success:
            return .success(data: [
                "to": .string(to),
                "text": .string(text),
                "sent": .bool(true),
                "service": .string(service),
            ])
        case .failure(let msg):
            return .failure(.operationFailed("Failed to send message: \(msg)"))
        }
    }

    // MARK: - Read Messages (SQLite, no AppleScript needed)

    private func readMessages(_ params: [String: AnyCodableValue]) -> ExecuteResponse {
        let limit = params["limit"]?.intValue ?? 10
        let contact = params["contact"]?.stringValue

        var db: OpaquePointer?
        let flags = SQLITE_OPEN_READONLY | SQLITE_OPEN_URI
        guard sqlite3_open_v2(Self.chatDB, &db, flags, nil) == SQLITE_OK else {
            return .failure(.operationFailed(
                "Cannot open chat.db. Grant Full Disk Access in System Settings > Privacy & Security."
            ))
        }
        defer { sqlite3_close(db) }

        let sql: String
        let hasContact = contact != nil && !contact!.isEmpty

        if hasContact {
            sql = """
                SELECT
                    c.display_name,
                    h.id as handle_id,
                    m.text,
                    m.date as message_date,
                    m.is_from_me,
                    m.service
                FROM message m
                JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
                JOIN chat c ON cmj.chat_id = c.ROWID
                LEFT JOIN handle h ON m.handle_id = h.ROWID
                WHERE (c.display_name LIKE ? OR h.id LIKE ?)
                  AND m.text IS NOT NULL
                ORDER BY m.date DESC
                LIMIT ?
            """
        } else {
            sql = """
                SELECT
                    c.display_name,
                    c.chat_identifier,
                    m.text,
                    m.date as message_date,
                    m.is_from_me,
                    m.service
                FROM chat c
                JOIN chat_message_join cmj ON c.ROWID = cmj.chat_id
                JOIN message m ON cmj.message_id = m.ROWID
                WHERE m.text IS NOT NULL
                GROUP BY c.ROWID
                ORDER BY m.date DESC
                LIMIT ?
            """
        }

        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else {
            return .failure(.operationFailed("Failed to prepare SQL query"))
        }
        defer { sqlite3_finalize(stmt) }

        if hasContact, let contact {
            let pattern = "%\(contact)%"
            sqlite3_bind_text(stmt, 1, (pattern as NSString).utf8String, -1, nil)
            sqlite3_bind_text(stmt, 2, (pattern as NSString).utf8String, -1, nil)
            sqlite3_bind_int(stmt, 3, Int32(limit))
        } else {
            sqlite3_bind_int(stmt, 1, Int32(limit))
        }

        var messages: [[String: AnyCodableValue]] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            let nameOrId: String
            if hasContact {
                nameOrId = sqlite3_column_text(stmt, 0).map { String(cString: $0) }
                    ?? sqlite3_column_text(stmt, 1).map { String(cString: $0) }
                    ?? "Unknown"
            } else {
                nameOrId = sqlite3_column_text(stmt, 0).map { String(cString: $0) }
                    ?? sqlite3_column_text(stmt, 1).map { String(cString: $0) }
                    ?? "Unknown"
            }
            let text = sqlite3_column_text(stmt, 2).map { String(cString: $0) } ?? ""
            let appleTs = sqlite3_column_int64(stmt, 3)
            let unixTs = (Double(appleTs) / 1_000_000_000) + Self.appleEpochOffset
            let date = Date(timeIntervalSince1970: unixTs)
            let isoDate = ISO8601DateFormatter().string(from: date)
            let fromMe = sqlite3_column_int(stmt, 4) != 0
            let service = sqlite3_column_text(stmt, 5).map { String(cString: $0) } ?? ""

            messages.append([
                "name": .string(nameOrId),
                "text": .string(text),
                "date": .string(isoDate),
                "from_me": .bool(fromMe),
                "service": .string(service),
            ])
        }

        return .success(data: [
            "messages": .array(messages.map { .object($0) }),
            "count": .int(messages.count),
        ])
    }

    // MARK: - Script Execution (subprocess, non-blocking)

    private enum ScriptResult {
        case success(String)
        case failure(String)
    }

    private static func runOsascript(_ script: String) async -> ScriptResult {
        await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let process = Process()
                process.executableURL = URL(fileURLWithPath: osascriptPath)
                process.arguments = ["-e", script]

                let stdoutPipe = Pipe()
                let stderrPipe = Pipe()
                process.standardOutput = stdoutPipe
                process.standardError = stderrPipe

                do {
                    try process.run()
                } catch {
                    continuation.resume(returning: .failure("Failed to launch osascript: \(error.localizedDescription)"))
                    return
                }

                var stdoutData = Data()
                var stderrData = Data()
                let group = DispatchGroup()

                group.enter()
                DispatchQueue.global().async {
                    stdoutData = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
                    group.leave()
                }
                group.enter()
                DispatchQueue.global().async {
                    stderrData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
                    group.leave()
                }

                let timer = DispatchSource.makeTimerSource(queue: .global())
                timer.schedule(deadline: .now() + scriptTimeout)
                timer.setEventHandler {
                    if process.isRunning { process.terminate() }
                }
                timer.resume()

                process.waitUntilExit()
                timer.cancel()
                group.wait()

                let stdout = String(data: stdoutData, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                let stderr = String(data: stderrData, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""

                if process.terminationStatus == 0 {
                    continuation.resume(returning: .success(stdout))
                } else if process.terminationReason == .uncaughtSignal {
                    continuation.resume(returning: .failure("Script timed out after \(Int(scriptTimeout))s"))
                } else {
                    let msg = stderr.isEmpty ? "osascript exited with code \(process.terminationStatus)" : stderr
                    continuation.resume(returning: .failure(msg))
                }
            }
        }
    }

    // MARK: - Helpers

    private static func escapeForAS(_ s: String) -> String {
        s.replacingOccurrences(of: "\\", with: "\\\\")
         .replacingOccurrences(of: "\"", with: "\\\"")
         .replacingOccurrences(of: "\n", with: " ")
         .replacingOccurrences(of: "\r", with: " ")
    }

    /// Build an AppleScript expression for text that may contain newlines.
    private static func buildTextExpression(_ text: String) -> String {
        let lines = text.components(separatedBy: .newlines)
        if lines.count <= 1 {
            return "\"\(escapeForAS(text))\""
        }
        return lines
            .map { "\"\(escapeForAS($0))\"" }
            .joined(separator: " & return & ")
    }

    @MainActor
    private static func isMessagesRunning() -> Bool {
        !NSRunningApplication.runningApplications(withBundleIdentifier: messagesBundleId).isEmpty
    }

    @MainActor
    private static func hideMessages() {
        _ = NSRunningApplication.runningApplications(
            withBundleIdentifier: messagesBundleId
        ).first?.hide()
    }
}
