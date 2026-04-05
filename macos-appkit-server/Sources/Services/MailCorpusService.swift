import AppKit
import Foundation

/// Thin data-access layer over Mail.app for bulk mail corpus export.
///
/// Three dumb-pipe actions that fetch raw data with basic Mail.app-native
/// filters. All aggregation, clustering, domain extraction, and intelligence
/// logic lives in Python — not here.
///
/// All operations are read-only. No rollback support.
actor MailCorpusService {

    private enum Timeout {
        static let single: TimeInterval = 30
        static let bulk: TimeInterval = 120
    }

    func execute(action: String, params: [String: AnyCodableValue]) async -> ExecuteResponse {
        switch action {
        case "LIST_MAILBOXES":
            return await listMailboxes(params)
        case "GET_HEADERS":
            return await getHeaders(params)
        case "GET_BODY":
            return await getBody(params)
        default:
            return .failure(.unknownAction(action, adapter: "mail_corpus"))
        }
    }

    func rollback(rollbackId: String) async -> ExecuteResponse {
        return .failure("mail_corpus is read-only")
    }

    // MARK: - LIST_MAILBOXES
    // Returns flat rows: (account_name, account_email, mailbox, message_count, unread_count)
    // Python groups/structures these however it wants.

    private func listMailboxes(_ params: [String: AnyCodableValue]) async -> ExecuteResponse {
        let script = """
            tell application "Mail"
                set output to ""
                repeat with acct in accounts
                    set acctName to name of acct
                    set acctEmail to email addresses of acct
                    set firstEmail to ""
                    if (count of acctEmail) > 0 then
                        set firstEmail to item 1 of acctEmail
                    end if
                    repeat with mbox in mailboxes of acct
                        set mboxName to name of mbox
                        set msgCount to count of messages of mbox
                        set unreadCount to unread count of mbox
                        set output to output & acctName & tab & firstEmail & tab & mboxName & tab & msgCount & tab & unreadCount & linefeed
                    end repeat
                end repeat
                return output
            end tell
        """

        let mailWasRunning = await MailScriptRunner.isMailRunning()
        let result = await MailScriptRunner.runOsascript(script, timeout: Timeout.single)
        if !mailWasRunning { await MailScriptRunner.hideMail() }

        switch result {
        case .success(let output):
            let rows = MailScriptRunner.parseTabDelimited(
                output,
                fields: ["account_name", "account_email", "mailbox", "message_count", "unread_count"]
            )
            return .success(data: [
                "rows": .array(rows.map { .object($0) }),
                "count": .int(rows.count),
            ])

        case .failure(let msg):
            return .failure(.operationFailed("Failed to list mailboxes: \(msg)"))
        }
    }

    // MARK: - GET_HEADERS
    // Unified search + pagination over the email corpus.
    // Mail.app applies whose-clause filters natively (fast).
    // Returns flat rows: (message_id, subject, sender, date, read, mailbox, account, body?)

    private func getHeaders(_ params: [String: AnyCodableValue]) async -> ExecuteResponse {
        let senderFilter = params["sender"]?.stringValue
        let subjectFilter = params["subject"]?.stringValue
        let dateFrom = params["date_from"]?.stringValue
        let dateTo = params["date_to"]?.stringValue
        let mailboxFilter = params["mailbox"]?.stringValue
        let accountFilter = params["account"]?.stringValue
        let offset = params["offset"]?.intValue ?? 0
        let limit = params["limit"]?.intValue ?? 50
        let includeBody = params["include_body"]?.boolValue ?? false

        var whoseClauses: [String] = []
        if let sender = senderFilter {
            whoseClauses.append("sender contains \"\(MailScriptRunner.escapeForAS(sender))\"")
        }
        if let subject = subjectFilter {
            whoseClauses.append("subject contains \"\(MailScriptRunner.escapeForAS(subject))\"")
        }
        if let from = dateFrom {
            whoseClauses.append("date received > date \"\(MailScriptRunner.escapeForAS(from))\"")
        }
        if let to = dateTo {
            whoseClauses.append("date received < date \"\(MailScriptRunner.escapeForAS(to))\"")
        }

        let whoseClause = whoseClauses.isEmpty ? "" : " whose \(whoseClauses.joined(separator: " and "))"

        let bodyLine = includeBody
            ? "set bodyText to content of m"
            : "set bodyText to \"\""

        let startIdx = offset + 1
        let endIdx = offset + limit

        let script = """
            tell application "Mail"
                set sep to character id 31
                set recSep to character id 30
                set output to ""
                set collected to 0
                repeat with acct in accounts
                    \(accountGuardOpen(accountFilter))
                    repeat with mbox in mailboxes of acct
                        set mboxName to name of mbox
                        set shouldProcess to true
                        \(mailboxGuard(mailboxFilter))
                        if shouldProcess then
                            try
                                set msgs to (messages of mbox\(whoseClause))
                                set msgCount to count of msgs
                                set safeEnd to \(endIdx)
                                if safeEnd > msgCount then set safeEnd to msgCount
                                if \(startIdx) > msgCount then
                                    -- nothing in this range
                                else
                                    set acctName to name of acct
                                    repeat with i from \(startIdx) to safeEnd
                                        set m to item i of msgs
                                        set mid to message id of m
                                        set subj to subject of m
                                        set sndr to sender of m
                                        set dt to (date received of m) as \u{00AB}class isot\u{00BB} as string
                                        \(bodyLine)
                                        set output to output & mid & sep & subj & sep & sndr & sep & dt & sep & mboxName & sep & acctName & sep & bodyText & recSep
                                        set collected to collected + 1
                                    end repeat
                                end if
                            end try
                        end if
                        if collected \u{2265} \(limit) then exit repeat
                    end repeat
                    \(accountGuardClose(accountFilter))
                    if collected \u{2265} \(limit) then exit repeat
                end repeat
                return output
            end tell
        """

        let mailWasRunning = await MailScriptRunner.isMailRunning()
        let result = await MailScriptRunner.runOsascript(script, timeout: Timeout.bulk)
        if !mailWasRunning { await MailScriptRunner.hideMail() }

        switch result {
        case .success(let output):
            var rows = parseUnitSeparated(output, fields: ["message_id", "subject", "sender", "date", "mailbox", "account", "body"])
            if !includeBody {
                rows = rows.map { row in
                    var r = row
                    r.removeValue(forKey: "body")
                    return r
                }
            }
            return .success(data: [
                "rows": .array(rows.map { .object($0) }),
                "count": .int(rows.count),
            ])

        case .failure(let msg):
            return .failure(.operationFailed("Failed to get headers: \(msg)"))
        }
    }

    // MARK: - GET_BODY
    // Fetch full content for a single message by message_id.
    // Returns: subject, sender, date, message_id, mailbox, account, body_plain, body_html, recipients

    private func getBody(_ params: [String: AnyCodableValue]) async -> ExecuteResponse {
        guard let messageId = params["message_id"]?.stringValue, !messageId.isEmpty else {
            return .failure(.invalidInput("message_id is required"))
        }

        let escapedId = MailScriptRunner.escapeForAS(messageId)
        let format = params["format"]?.stringValue ?? "plain"
        let wantHtml = format == "html" || format == "both"
        let wantPlain = format != "html"

        let contentLine = wantPlain
            ? "set bodyPlain to content of m"
            : "set bodyPlain to \"\""

        let sourceLine = wantHtml
            ? "set src to source of m"
            : "set src to \"\""

        let script = """
            tell application "Mail"
                set sep to character id 31
                repeat with acct in accounts
                    repeat with mbox in mailboxes of acct
                        try
                            set msgs to (messages of mbox whose message id is "\(escapedId)")
                            if (count of msgs) > 0 then
                                set m to item 1 of msgs
                                set subj to subject of m
                                set sndr to sender of m
                                set dt to (date received of m) as \u{00AB}class isot\u{00BB} as string
                                set mid to message id of m
                                set mboxName to name of mbox
                                set acctName to name of acct
                                \(contentLine)
                                \(sourceLine)
                                set recipList to ""
                                repeat with r in to recipients of m
                                    if recipList is not "" then set recipList to recipList & ","
                                    set recipList to recipList & address of r
                                end repeat
                                set hdrs to all headers of m
                                return subj & sep & sndr & sep & dt & sep & mid & sep & mboxName & sep & acctName & sep & bodyPlain & sep & src & sep & recipList & sep & hdrs
                            end if
                        end try
                    end repeat
                end repeat
                return ""
            end tell
        """

        let mailWasRunning = await MailScriptRunner.isMailRunning()
        let result = await MailScriptRunner.runOsascript(script, timeout: Timeout.single)
        if !mailWasRunning { await MailScriptRunner.hideMail() }

        switch result {
        case .success(let output):
            guard !output.isEmpty else {
                return .failure(.notFound("No email found with message_id: \(messageId)"))
            }

            let parts = output.components(separatedBy: "\u{1F}")

            var data: [String: AnyCodableValue] = [
                "subject": .string(parts.count > 0 ? parts[0] : ""),
                "sender": .string(parts.count > 1 ? parts[1] : ""),
                "date": .string(parts.count > 2 ? parts[2] : ""),
                "message_id": .string(parts.count > 3 ? parts[3] : ""),
                "mailbox": .string(parts.count > 4 ? parts[4] : ""),
                "account": .string(parts.count > 5 ? parts[5] : ""),
            ]

            if wantPlain {
                data["body_plain"] = .string(parts.count > 6 ? parts[6] : "")
            }
            if wantHtml {
                data["body_html"] = .string(parts.count > 7 ? parts[7] : "")
            }

            data["headers"] = .string(parts.count > 9 ? parts[9] : "")

            let recipStr = parts.count > 8 ? parts[8] : ""
            if !recipStr.isEmpty {
                data["recipients"] = .array(
                    recipStr.split(separator: ",").map {
                        AnyCodableValue.string(String($0).trimmingCharacters(in: .whitespaces))
                    }
                )
            } else {
                data["recipients"] = .array([])
            }

            return .success(data: data)

        case .failure(let msg):
            return .failure(.operationFailed("Failed to get body: \(msg)"))
        }
    }

    // MARK: - AppleScript Guard Helpers

    /// Generates if/else open for account filtering. Wraps the loop body so
    /// non-matching accounts are skipped without `exit repeat`.
    private func accountGuardOpen(_ accountFilter: String?) -> String {
        guard let acct = accountFilter else { return "" }
        return "if name of acct is \"\(MailScriptRunner.escapeForAS(acct))\" then"
    }

    private func accountGuardClose(_ accountFilter: String?) -> String {
        guard accountFilter != nil else { return "" }
        return "end if"
    }

    private func mailboxGuard(_ mailboxFilter: String?) -> String {
        guard let mbox = mailboxFilter else { return "" }
        return "if mboxName is not \"\(MailScriptRunner.escapeForAS(mbox))\" then set shouldProcess to false"
    }

    // MARK: - Parsing

    /// Parse output delimited by unit separator (field) and record separator (row).
    private func parseUnitSeparated(_ raw: String, fields: [String]) -> [[String: AnyCodableValue]] {
        guard !raw.isEmpty else { return [] }
        var records: [[String: AnyCodableValue]] = []
        let rows = raw.components(separatedBy: "\u{1E}")
        for row in rows {
            let trimmed = row.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { continue }
            let parts = trimmed.components(separatedBy: "\u{1F}")
            var record: [String: AnyCodableValue] = [:]
            for (idx, field) in fields.enumerated() {
                record[field] = .string(idx < parts.count ? parts[idx] : "")
            }
            records.append(record)
        }
        return records
    }
}
