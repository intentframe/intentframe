import AppKit
import Foundation

/// Shared infrastructure for running AppleScript against Mail.app.
/// Used by both MailService (basic ops) and MailCorpusService (intelligence primitives).
enum MailScriptRunner {

    static let osascriptPath = "/usr/bin/osascript"
    static let defaultTimeout: TimeInterval = 30

    enum ScriptResult {
        case success(String)
        case failure(String)
    }

    /// Run an AppleScript via /usr/bin/osascript as a subprocess.
    /// Fully non-blocking — runs in its own process, doesn't touch the Vapor event loop.
    static func runOsascript(_ script: String, timeout: TimeInterval = defaultTimeout) async -> ScriptResult {
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

                // Read pipes on background threads BEFORE waitUntilExit to avoid
                // deadlock when output exceeds the pipe buffer (~16 KB).
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
                timer.schedule(deadline: .now() + timeout)
                timer.setEventHandler {
                    if process.isRunning {
                        process.terminate()
                    }
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
                    continuation.resume(returning: .failure("Script timed out after \(Int(timeout))s"))
                } else {
                    let msg = stderr.isEmpty ? "osascript exited with code \(process.terminationStatus)" : stderr
                    continuation.resume(returning: .failure(msg))
                }
            }
        }
    }

    // MARK: - String Helpers

    /// Escape a string for embedding in an AppleScript double-quoted literal.
    /// Replaces newlines with spaces since AS string literals passed via
    /// osascript -e must be single-line. Use `buildBodyExpression` for
    /// multi-line content that should preserve line breaks.
    static func escapeForAS(_ s: String) -> String {
        s.replacingOccurrences(of: "\\", with: "\\\\")
         .replacingOccurrences(of: "\"", with: "\\\"")
         .replacingOccurrences(of: "\n", with: " ")
         .replacingOccurrences(of: "\r", with: " ")
    }

    /// Build an AppleScript expression for a string that may contain newlines.
    /// Splits on \n and \r, joins with `& return &` so each segment is a
    /// single-line string literal (required by osascript -e source parsing).
    static func buildBodyExpression(_ text: String) -> String {
        let lines = text.components(separatedBy: .newlines)
        if lines.count <= 1 {
            return "\"\(escapeForAS(text))\""
        }
        return lines
            .map { "\"\(escapeForAS($0))\"" }
            .joined(separator: " & return & ")
    }

    // MARK: - Mail.app State

    @MainActor
    static func isMailRunning() -> Bool {
        !NSRunningApplication.runningApplications(withBundleIdentifier: "com.apple.mail").isEmpty
    }

    @MainActor
    static func hideMail() {
        _ = NSRunningApplication.runningApplications(
            withBundleIdentifier: "com.apple.mail"
        ).first?.hide()
    }

    // MARK: - Output Parsing

    /// Parse tab-delimited output from osascript into an array of dicts.
    static func parseTabDelimited(_ raw: String?, fields: [String]) -> [[String: AnyCodableValue]] {
        guard let raw, !raw.isEmpty else { return [] }
        var records: [[String: AnyCodableValue]] = []
        for line in raw.components(separatedBy: .newlines) where !line.isEmpty {
            let parts = line.components(separatedBy: "\t")
            var record: [String: AnyCodableValue] = [:]
            for (idx, field) in fields.enumerated() {
                let value = idx < parts.count ? parts[idx] : ""
                if field == "read" {
                    record[field] = .bool(value == "true")
                } else {
                    record[field] = .string(value)
                }
            }
            records.append(record)
        }
        return records
    }
}
