import AppKit
import Foundation

/// Sends and reads email via Mail.app's AppleScript dictionary.
///
/// Mail.app handles all authentication (OAuth, app passwords, etc.) using
/// the accounts already configured in System Settings > Internet Accounts.
/// No SMTP credentials are needed from the executor.
///
/// Scripts run via `/usr/bin/osascript` as a subprocess so the Vapor event
/// loop is never blocked. Each script gets a 30-second timeout.
actor MailService {

    func execute(action: String, params: [String: AnyCodableValue]) async -> ExecuteResponse {
        switch action {
        case "SEND_EMAIL":
            return await sendEmail(params)
        case "READ_EMAIL":
            return await readEmail(params)
        case "SEARCH_EMAIL":
            return await searchEmail(params)
        default:
            return .failure(.unknownAction(action, adapter: "mail"))
        }
    }

    func rollback(rollbackId: String) async -> ExecuteResponse {
        return .failure("Email send is irreversible")
    }

    // MARK: - Send Email

    private func sendEmail(_ params: [String: AnyCodableValue]) async -> ExecuteResponse {
        let to: [String]
        if let single = params["to"]?.stringValue {
            to = [single]
        } else if case .array(let arr) = params["to"] {
            to = arr.compactMap(\.stringValue)
        } else {
            return .failure(.invalidInput("to is required (string or array of strings)"))
        }
        guard !to.isEmpty else {
            return .failure(.invalidInput("to is required"))
        }

        let subject = params["subject"]?.stringValue ?? ""
        let body = params["body"]?.stringValue ?? ""

        let recipientLines = to.map { addr in
            let escaped = MailScriptRunner.escapeForAS(addr)
            return "make new to recipient at end of to recipients with properties {address:\"\(escaped)\"}"
        }.joined(separator: "\n                ")

        let bodyExpr = MailScriptRunner.buildBodyExpression(body)

        let script = """
            tell application "Mail"
                set bodyText to \(bodyExpr)
                set newMsg to make new outgoing message with properties {subject:"\(MailScriptRunner.escapeForAS(subject))", visible:false}
                set content of newMsg to bodyText
                tell newMsg
                    \(recipientLines)
                    send
                end tell
            end tell
        """

        let mailWasRunning = await MailScriptRunner.isMailRunning()
        let result = await MailScriptRunner.runOsascript(script)
        if !mailWasRunning { await MailScriptRunner.hideMail() }

        switch result {
        case .success:
            return .success(data: [
                "to": .array(to.map { .string($0) }),
                "subject": .string(subject),
                "sent": .bool(true),
            ])
        case .failure(let msg):
            return .failure(.operationFailed("Failed to send email via Mail.app: \(msg)"))
        }
    }

    // MARK: - Read Email

    private func readEmail(_ params: [String: AnyCodableValue]) async -> ExecuteResponse {
        let mailbox = MailScriptRunner.escapeForAS(params["mailbox"]?.stringValue ?? "INBOX")
        let limit = params["limit"]?.intValue ?? 10
        let unreadOnly = params["unread_only"]?.boolValue ?? false

        let filterClause = unreadOnly ? " whose read status is false" : ""

        let script = """
            tell application "Mail"
                set output to ""
                set acct to first account
                set mbox to mailbox "\(mailbox)" of acct
                set msgs to (a reference to messages of mbox\(filterClause))
                set msgCount to count of msgs
                if msgCount > \(limit) then set msgCount to \(limit)
                repeat with i from 1 to msgCount
                    set m to item i of msgs
                    set subj to subject of m
                    set sndr to sender of m
                    set dt to (date received of m) as \u{00AB}class isot\u{00BB} as string
                    set rd to read status of m
                    set mid to message id of m
                    set output to output & subj & tab & sndr & tab & dt & tab & rd & tab & mid & linefeed
                end repeat
                return output
            end tell
        """

        let mailWasRunning = await MailScriptRunner.isMailRunning()
        let result = await MailScriptRunner.runOsascript(script)
        if !mailWasRunning { await MailScriptRunner.hideMail() }

        switch result {
        case .success(let output):
            let messages = MailScriptRunner.parseTabDelimited(
                output,
                fields: ["subject", "sender", "date", "read", "message_id"]
            )
            return .success(data: [
                "messages": .array(messages.map { .object($0) }),
                "count": .int(messages.count),
            ])
        case .failure(let msg):
            return .failure(.operationFailed("Failed to read email: \(msg)"))
        }
    }

    // MARK: - Search Email

    private func searchEmail(_ params: [String: AnyCodableValue]) async -> ExecuteResponse {
        let query = params["query"]?.stringValue ?? ""
        guard !query.isEmpty else {
            return .failure(.invalidInput("query is required"))
        }
        let mailbox = MailScriptRunner.escapeForAS(params["mailbox"]?.stringValue ?? "INBOX")
        let limit = params["limit"]?.intValue ?? 10
        let escapedQuery = MailScriptRunner.escapeForAS(query)

        let script = """
            tell application "Mail"
                set output to ""
                set acct to first account
                set mbox to mailbox "\(mailbox)" of acct
                set msgs to (a reference to messages of mbox whose subject contains "\(escapedQuery)")
                set msgCount to count of msgs
                if msgCount > \(limit) then set msgCount to \(limit)
                repeat with i from 1 to msgCount
                    set m to item i of msgs
                    set subj to subject of m
                    set sndr to sender of m
                    set dt to (date received of m) as \u{00AB}class isot\u{00BB} as string
                    set mid to message id of m
                    set output to output & subj & tab & sndr & tab & dt & tab & mid & linefeed
                end repeat
                return output
            end tell
        """

        let mailWasRunning = await MailScriptRunner.isMailRunning()
        let result = await MailScriptRunner.runOsascript(script)
        if !mailWasRunning { await MailScriptRunner.hideMail() }

        switch result {
        case .success(let output):
            let results = MailScriptRunner.parseTabDelimited(
                output,
                fields: ["subject", "sender", "date", "message_id"]
            )
            return .success(data: [
                "results": .array(results.map { .object($0) }),
                "query": .string(query),
                "count": .int(results.count),
            ])
        case .failure(let msg):
            return .failure(.operationFailed("Failed to search email: \(msg)"))
        }
    }
}
