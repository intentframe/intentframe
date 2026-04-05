import AppKit
import Foundation
import SQLite3

actor NotesService {

    // NoteStore.sqlite lives in the Notes group container
    private static let notesDB: String = {
        let home = NSHomeDirectory()
        return "\(home)/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite"
    }()

    func execute(action: String, params: [String: AnyCodableValue]) async -> ExecuteResponse {
        switch action {
        case "LIST_NOTES":
            return listNotes(params)
        case "READ_NOTE":
            return await readNote(params)
        case "CREATE_NOTE":
            return await createNote(params)
        case "DELETE_NOTE":
            return await deleteNote(params)
        default:
            return .failure(.unknownAction(action, adapter: "notes"))
        }
    }

    func rollback(rollbackId: String) async -> ExecuteResponse {
        return .failure("Notes rollback not yet implemented")
    }

    // MARK: - List Notes (SQLite read)

    private func listNotes(_ params: [String: AnyCodableValue]) -> ExecuteResponse {
        let folder = params["folder"]?.stringValue
        let limit = params["limit"]?.intValue ?? 20

        var db: OpaquePointer?
        let flags = SQLITE_OPEN_READONLY | SQLITE_OPEN_URI
        guard sqlite3_open_v2(Self.notesDB, &db, flags, nil) == SQLITE_OK else {
            return .failure(.operationFailed(
                "Cannot open NoteStore.sqlite. Grant Full Disk Access in System Settings > Privacy & Security."
            ))
        }
        defer { sqlite3_close(db) }

        let sql: String
        let bindFolder: Bool

        if let folder, !folder.isEmpty {
            sql = """
                SELECT z.ZTITLE, f.ZTITLE as ZFOLDERNAME
                FROM ZICCLOUDSYNCINGOBJECT z
                LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON z.ZFOLDER = f.Z_PK
                WHERE z.ZTITLE IS NOT NULL
                  AND z.ZNOTEDATA IS NOT NULL
                  AND (z.ZISPASSWORDPROTECTED = 0 OR z.ZISPASSWORDPROTECTED IS NULL)
                  AND f.ZTITLE = ?
                ORDER BY z.ZMODIFICATIONDATE1 DESC
                LIMIT ?
            """
            bindFolder = true
        } else {
            sql = """
                SELECT z.ZTITLE, f.ZTITLE as ZFOLDERNAME
                FROM ZICCLOUDSYNCINGOBJECT z
                LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON z.ZFOLDER = f.Z_PK
                WHERE z.ZTITLE IS NOT NULL
                  AND z.ZNOTEDATA IS NOT NULL
                  AND (z.ZISPASSWORDPROTECTED = 0 OR z.ZISPASSWORDPROTECTED IS NULL)
                ORDER BY z.ZMODIFICATIONDATE1 DESC
                LIMIT ?
            """
            bindFolder = false
        }

        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else {
            return .failure(.operationFailed("Failed to prepare SQL query"))
        }
        defer { sqlite3_finalize(stmt) }

        if bindFolder, let folder {
            sqlite3_bind_text(stmt, 1, (folder as NSString).utf8String, -1, nil)
            sqlite3_bind_int(stmt, 2, Int32(limit))
        } else {
            sqlite3_bind_int(stmt, 1, Int32(limit))
        }

        var notes: [[String: AnyCodableValue]] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            let title = sqlite3_column_text(stmt, 0).map { String(cString: $0) } ?? ""
            let folderName = sqlite3_column_text(stmt, 1).map { String(cString: $0) } ?? "Notes"
            notes.append(["title": .string(title), "folder": .string(folderName)])
        }

        return .success(data: [
            "notes": .array(notes.map { .object($0) }),
            "count": .int(notes.count),
        ])
    }

    // MARK: - Read Note (SQLite + NSAppleScript fallback for body)

    private func readNote(_ params: [String: AnyCodableValue]) async -> ExecuteResponse {
        guard let title = params["title"]?.stringValue, !title.isEmpty else {
            return .failure(.invalidInput("title is required"))
        }

        // Get folder from SQLite
        var db: OpaquePointer?
        let flags = SQLITE_OPEN_READONLY | SQLITE_OPEN_URI
        let folderName: String
        if sqlite3_open_v2(Self.notesDB, &db, flags, nil) == SQLITE_OK {
            defer { sqlite3_close(db) }
            let sql = """
                SELECT f.ZTITLE as ZFOLDERNAME
                FROM ZICCLOUDSYNCINGOBJECT z
                LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON z.ZFOLDER = f.Z_PK
                WHERE z.ZTITLE = ?
                  AND z.ZNOTEDATA IS NOT NULL
                LIMIT 1
            """
            var stmt: OpaquePointer?
            if sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK {
                defer { sqlite3_finalize(stmt) }
                sqlite3_bind_text(stmt, 1, (title as NSString).utf8String, -1, nil)
                if sqlite3_step(stmt) == SQLITE_ROW {
                    folderName = sqlite3_column_text(stmt, 0).map { String(cString: $0) } ?? "Notes"
                } else {
                    return .failure(.notFound("Note not found: \(title)"))
                }
            } else {
                folderName = "Notes"
            }
        } else {
            folderName = "Notes"
        }

        // Body via NSAppleScript (stable across macOS versions)
        let body = await fetchNoteBody(title: title)

        return .success(data: [
            "title": .string(title),
            "folder": .string(folderName),
            "body": .string(body),
        ])
    }

    // MARK: - Create Note (NSAppleScript, in-process)

    private func createNote(_ params: [String: AnyCodableValue]) async -> ExecuteResponse {
        guard let title = params["title"]?.stringValue, !title.isEmpty else {
            return .failure(.invalidInput("title is required"))
        }
        let body = params["body"]?.stringValue ?? ""
        let folder = params["folder"]?.stringValue ?? ""

        let escapedTitle = title.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
        let escapedBody = body.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")

        let script: String
        if !folder.isEmpty {
            let escapedFolder = folder.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
            script = """
                tell application "Notes"
                    activate
                    set targetFolder to first folder whose name is "\(escapedFolder)"
                    set newNote to make new note at targetFolder with properties {name:"\(escapedTitle)", body:"\(escapedBody)"}
                    set noteId to id of newNote
                end tell
                return noteId
            """
        } else {
            script = """
                tell application "Notes"
                    activate
                    set newNote to make new note with properties {name:"\(escapedTitle)", body:"\(escapedBody)"}
                    set noteId to id of newNote
                end tell
                return noteId
            """
        }

        let (success, output) = runAppleScript(script)
        // Hide Notes.app immediately after creation
        await hideApp(bundleId: "com.apple.Notes")

        if !success {
            return .failure(.operationFailed("Failed to create note: \(output)"))
        }

        return .success(
            data: [
                "title": .string(title),
                "folder": .string(folder.isEmpty ? "Notes" : folder),
                "created": .bool(true),
                "note_id": .string(output.trimmingCharacters(in: .whitespacesAndNewlines)),
            ],
            rollbackId: "note:\(output.trimmingCharacters(in: .whitespacesAndNewlines))"
        )
    }

    // MARK: - Delete Note (NSAppleScript, in-process)

    private func deleteNote(_ params: [String: AnyCodableValue]) async -> ExecuteResponse {
        guard let title = params["title"]?.stringValue, !title.isEmpty else {
            return .failure(.invalidInput("title is required"))
        }

        let escapedTitle = title.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
        let script = """
            tell application "Notes"
                activate
                set noteToDelete to first note whose name is "\(escapedTitle)"
                delete noteToDelete
            end tell
        """

        let (success, output) = runAppleScript(script)
        await hideApp(bundleId: "com.apple.Notes")

        if !success {
            return .failure(.operationFailed("Failed to delete note: \(output)"))
        }

        return .success(data: ["title": .string(title), "deleted": .bool(true)])
    }

    // MARK: - Helpers

    private func fetchNoteBody(title: String) async -> String {
        let escapedTitle = title.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
        let script = """
            tell application "Notes"
                set theNote to first note whose name is "\(escapedTitle)"
                return body of theNote
            end tell
        """
        let (success, output) = runAppleScript(script)
        await hideApp(bundleId: "com.apple.Notes")
        if success {
            return stripHTML(output)
        }
        return ""
    }

    private func runAppleScript(_ source: String) -> (Bool, String) {
        var errorInfo: NSDictionary?
        let script = NSAppleScript(source: source)
        let result = script?.executeAndReturnError(&errorInfo)
        if let err = errorInfo {
            return (false, "\(err)")
        }
        return (true, result?.stringValue ?? "")
    }

    private func hideApp(bundleId: String) async {
        _ = await MainActor.run {
            NSRunningApplication.runningApplications(withBundleIdentifier: bundleId).first?.hide()
        }
    }

    private func stripHTML(_ html: String) -> String {
        // Simple HTML tag stripper — adequate for Notes body text
        var result = html
        while let range = result.range(of: "<[^>]+>", options: .regularExpression) {
            result.removeSubrange(range)
        }
        return result
            .replacingOccurrences(of: "&nbsp;", with: " ")
            .replacingOccurrences(of: "&amp;", with: "&")
            .replacingOccurrences(of: "&lt;", with: "<")
            .replacingOccurrences(of: "&gt;", with: ">")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
