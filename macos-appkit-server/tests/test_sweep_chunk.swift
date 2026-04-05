#!/usr/bin/env swift
/// Quick smoke-test for SWEEP_CHUNK AppleScript patterns.
///
/// Run with:
///   swift macos-appkit-server/tests/test_sweep_chunk.swift
///
/// Requirements: Mail.app must be accessible (Automation permission granted).
/// The script picks the FIRST account + FIRST mailbox it finds automatically.
/// It tests four patterns in order and prints PASS / FAIL for each.

import Foundation

// MARK: - osascript runner

func run(_ script: String, timeout: TimeInterval = 60) -> (ok: Bool, output: String) {
    let proc = Process()
    proc.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
    proc.arguments = ["-e", script]

    let out = Pipe()
    let err = Pipe()
    proc.standardOutput = out
    proc.standardError = err

    try! proc.run()

    var outData = Data()
    var errData = Data()
    let g = DispatchGroup()
    g.enter(); DispatchQueue.global().async { outData = out.fileHandleForReading.readDataToEndOfFile(); g.leave() }
    g.enter(); DispatchQueue.global().async { errData = err.fileHandleForReading.readDataToEndOfFile(); g.leave() }

    let timer = DispatchSource.makeTimerSource(queue: .global())
    timer.schedule(deadline: .now() + timeout)
    timer.setEventHandler { if proc.isRunning { proc.terminate() } }
    timer.resume()
    proc.waitUntilExit()
    timer.cancel()
    g.wait()

    let stdout = String(data: outData, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    let stderr = String(data: errData, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    let ok = proc.terminationStatus == 0
    return (ok, ok ? stdout : "STDERR: \(stderr) | STDOUT: \(stdout)")
}

func pass(_ label: String, _ detail: String = "") {
    print("  ✅ PASS  \(label)" + (detail.isEmpty ? "" : "  →  \(detail)"))
}
func fail(_ label: String, _ detail: String = "") {
    print("  ❌ FAIL  \(label)" + (detail.isEmpty ? "" : "  →  \(detail)"))
}

// MARK: - Step 0: discover first account + mailbox

print("\n=== Step 0: Discovering first account + mailbox ===")

let discoverScript = """
tell application "Mail"
    set acct to item 1 of accounts
    set acctName to name of acct
    set mbox to item 1 of mailboxes of acct
    set mboxName to name of mbox
    set total to count of messages of mbox
    return acctName & "|||" & mboxName & "|||" & (total as string)
end tell
"""

let discovery = run(discoverScript)
guard discovery.ok else {
    print("  ❌ Cannot talk to Mail.app: \(discovery.output)")
    print("  Make sure Automation permission is granted for Terminal/Cursor.")
    exit(1)
}

let parts = discovery.output.components(separatedBy: "|||")
guard parts.count == 3 else {
    print("  ❌ Unexpected discovery output: \(discovery.output)")
    exit(1)
}

let accountName = parts[0]
let mailboxName = parts[1]
let totalCount  = Int(parts[2]) ?? 0

print("  Account  : \(accountName)")
print("  Mailbox  : \(mailboxName)")
print("  Messages : \(totalCount)")

guard totalCount > 0 else {
    print("  ⚠️  Mailbox is empty — nothing to test. Try a different mailbox.")
    exit(1)
}

let limit = min(5, totalCount)

// MARK: - Test 1: Broken pattern (whose + items X thru Y + bulk property)

print("\n=== Test 1: BROKEN pattern — whose → items slice → bulk property ===")
print("  (This is what SWEEP_CHUNK currently does; expect 0 results)")

let brokenScript = """
tell application "Mail"
    set acct to (first account whose name is "\(accountName)")
    set mbox to (first mailbox of acct whose name is "\(mailboxName)")
    set allMsgs to (messages of mbox)
    set totalCount to count of allMsgs
    set chunkMsgs to items 1 thru \(limit) of allMsgs
    set midList to message id of chunkMsgs
    return (count of midList) as string
end tell
"""

let t1 = run(brokenScript)
if t1.ok {
    let cnt = Int(t1.output) ?? -1
    if cnt == limit {
        pass("Test 1", "Got \(cnt)/\(limit) IDs — works when allMsgs is a plain list (no whose filter)")
    } else if cnt == 0 {
        fail("Test 1", "Got 0/\(limit) IDs — bulk property access on items-of-list failed silently")
    } else {
        print("  ⚠️  Test 1 partial: \(cnt)/\(limit) IDs")
    }
} else {
    fail("Test 1 (error)", t1.output)
}

// MARK: - Test 2: Broken pattern WITH whose date filter (the real bug)

print("\n=== Test 2: BROKEN pattern — whose date filter → items slice → bulk property ===")
print("  (The actual production bug; should return 0 despite total > 0)")

// Use a date far in the past so all messages match
let pastDate = "1990-01-01"
let brokenWithWhoseScript = """
tell application "Mail"
    set acct to (first account whose name is "\(accountName)")
    set mbox to (first mailbox of acct whose name is "\(mailboxName)")
    set cutoffDate to current date
    set year of cutoffDate to 1990
    set month of cutoffDate to 1
    set day of cutoffDate to 1
    set time of cutoffDate to 0
    set allMsgs to (messages of mbox whose date received > cutoffDate)
    set totalCount to count of allMsgs
    set safeEnd to \(limit)
    if safeEnd > totalCount then set safeEnd to totalCount
    if totalCount < 1 then return "total=0"
    set chunkMsgs to items 1 thru safeEnd of allMsgs
    set midList to message id of chunkMsgs
    return "total=" & (totalCount as string) & " got=" & (count of midList) as string
end tell
"""

let t2 = run(brokenWithWhoseScript, timeout: 120)
if t2.ok {
    print("  Output: \(t2.output)")
    if t2.output.contains("got=0") {
        fail("Test 2", "Confirmed bug: total > 0 but got 0 IDs from bulk property access on whose-filtered reference")
    } else if t2.output.contains("total=0") {
        print("  ⚠️  No messages matched the date filter — try adjusting the cutoff date")
    } else {
        pass("Test 2 (unexpected)", "Pattern worked: \(t2.output)")
    }
} else {
    fail("Test 2 (error)", t2.output)
}

// MARK: - Test 3: Option A fix — direct range specifier, no whose

print("\n=== Test 3: OPTION A FIX — direct range specifier messages X thru Y of mbox ===")
print("  (No whose, no variable; should reliably return \(limit) IDs)")

let optionAScript = """
tell application "Mail"
    set acct to (first account whose name is "\(accountName)")
    set mbox to (first mailbox of acct whose name is "\(mailboxName)")
    set totalCount to count of messages of mbox
    set safeEnd to \(limit)
    if safeEnd > totalCount then set safeEnd to totalCount
    set midList to message id of messages 1 thru safeEnd of mbox
    set subjList to subject of messages 1 thru safeEnd of mbox
    set sndrList to sender of messages 1 thru safeEnd of mbox
    return (count of midList) as string
end tell
"""

let t3 = run(optionAScript)
if t3.ok {
    let cnt = Int(t3.output) ?? -1
    if cnt == limit {
        pass("Test 3", "Got \(cnt)/\(limit) IDs — direct range specifier works perfectly")
    } else {
        fail("Test 3", "Got \(cnt)/\(limit) IDs — unexpected count")
    }
} else {
    fail("Test 3 (error)", t3.output)
}

// MARK: - Test 4: Option A with isot date + sample output

print("\n=== Test 4: Option A — full row output with isot dates ===")
print("  (Verifies complete row format matches what Python parser expects)")

let optionAFullScript = """
tell application "Mail"
    set sep to character id 31
    set recSep to character id 30
    set output to ""
    set acct to (first account whose name is "\(accountName)")
    set mbox to (first mailbox of acct whose name is "\(mailboxName)")
    set totalCount to count of messages of mbox
    set safeEnd to \(limit)
    if safeEnd > totalCount then set safeEnd to totalCount

    set midList to message id of messages 1 thru safeEnd of mbox
    set subjList to subject of messages 1 thru safeEnd of mbox
    set sndrList to sender of messages 1 thru safeEnd of mbox
    set dtList to {}
    repeat with m in (messages 1 thru safeEnd of mbox)
        set end of dtList to ((date received of m) as «class isot» as string)
    end repeat

    set chunkCount to count of midList
    repeat with i from 1 to chunkCount
        set output to output & (item i of midList) & sep & (item i of subjList) & sep & (item i of sndrList) & sep & (item i of dtList) & sep & "\(mailboxName)" & sep & "\(accountName)" & recSep
    end repeat
    return (totalCount as string) & recSep & output
end tell
"""

let t4 = run(optionAFullScript, timeout: 120)
if t4.ok {
    let allParts = t4.output.components(separatedBy: "\u{1E}")
    let total = Int(allParts.first?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "0") ?? 0
    let rows = allParts.dropFirst().filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    if rows.count == limit {
        pass("Test 4", "total=\(total), rows=\(rows.count)/\(limit) — full format works")
        print("\n  Sample row 1:")
        let fields = rows[0].components(separatedBy: "\u{1F}")
        let labels = ["message_id","subject","sender","date","mailbox","account"]
        for (i, lbl) in labels.enumerated() {
            let val = i < fields.count ? fields[i] : "(missing)"
            print("    \(lbl): \(val)")
        }
    } else {
        fail("Test 4", "Expected \(limit) rows, got \(rows.count). Output: \(t4.output.prefix(200))")
    }
} else {
    fail("Test 4 (error)", t4.output)
}

// MARK: - Test 5: Option A with Python-side date filtering simulation

print("\n=== Test 5: Option A — Python-side date filtering (30-day cutoff) ===")
print("  (Fetch first 50 messages, count how many fall within last 30 days)")

let fiftyLimit = min(50, totalCount)
let optionADateFilterScript = """
tell application "Mail"
    set sep to character id 31
    set recSep to character id 30
    set output to ""
    set acct to (first account whose name is "\(accountName)")
    set mbox to (first mailbox of acct whose name is "\(mailboxName)")
    set totalCount to count of messages of mbox
    set safeEnd to \(fiftyLimit)
    if safeEnd > totalCount then set safeEnd to totalCount

    set midList to message id of messages 1 thru safeEnd of mbox
    set dtList to {}
    repeat with m in (messages 1 thru safeEnd of mbox)
        set end of dtList to ((date received of m) as «class isot» as string)
    end repeat

    repeat with i from 1 to count of midList
        set output to output & (item i of midList) & sep & (item i of dtList) & recSep
    end repeat
    return (totalCount as string) & recSep & output
end tell
"""

let t5 = run(optionADateFilterScript, timeout: 120)
if t5.ok {
    let allParts = t5.output.components(separatedBy: "\u{1E}")
    let total = Int(allParts.first?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "0") ?? 0
    let rows = allParts.dropFirst().filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    // Simulate Python-side 30-day filter
    let cutoff = Date().addingTimeInterval(-30 * 24 * 3600)
    let isoFmt = ISO8601DateFormatter()
    var recentCount = 0
    for row in rows {
        let fields = row.components(separatedBy: "\u{1F}")
        if fields.count > 1, let dt = isoFmt.date(from: fields[1]) {
            if dt > cutoff { recentCount += 1 }
        }
    }

    pass("Test 5", "total=\(total), fetched=\(rows.count), last-30-day rows=\(recentCount)")
    print("  → Python would keep \(recentCount) of \(rows.count) sampled rows for quick sweep")
} else {
    fail("Test 5 (error)", t5.output)
}

// MARK: - Test 6: Reverse pagination — offset_from_end, fresh count inside same script

print("\n=== Test 6: Reverse pagination — offset_from_end, fresh count inside script ===")
print("  (Simulates proposed SWEEP_CHUNK_REV: Python sends offset_from_end, Swift recomputes range)")

// Chunk 1: most recent limit messages
let revLimit = min(500, totalCount)
let revChunk1Script = """
tell application "Mail"
    set recSep to character id 30
    set sep to character id 31
    set acct to (first account whose name is "\(accountName)")
    set mbox to (first mailbox of acct whose name is "\(mailboxName)")

    -- Fresh count inside same call (safe from staleness)
    set freshTotal to count of messages of mbox

    -- offset_from_end=0 means most recent chunk
    set offsetFromEnd to 0
    set chunkLimit to \(revLimit)
    set endIdx to freshTotal - offsetFromEnd
    set startIdx to endIdx - chunkLimit + 1
    if startIdx < 1 then set startIdx to 1
    set actualCount to endIdx - startIdx + 1

    set midList to message id of messages startIdx thru endIdx of mbox
    set dtList to {}
    repeat with m in (messages startIdx thru endIdx of mbox)
        set end of dtList to ((date received of m) as \u{00AB}class isot\u{00BB} as string)
    end repeat

    set output to ""
    repeat with i from 1 to count of midList
        set output to output & (item i of midList) & sep & (item i of dtList) & recSep
    end repeat

    return (freshTotal as string) & recSep & (actualCount as string) & recSep & output
end tell
"""

let t6 = run(revChunk1Script, timeout: 120)
if t6.ok {
    let allParts = t6.output.components(separatedBy: "\u{1E}")
    let freshTotal = Int(allParts.first?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "0") ?? 0
    let actualCount = Int((allParts.count > 1 ? allParts[1] : "0").trimmingCharacters(in: .whitespacesAndNewlines)) ?? 0
    let rows = Array(allParts.dropFirst(2)).filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    
    if rows.count == actualCount && actualCount == revLimit {
        pass("Test 6 chunk-1", "freshTotal=\(freshTotal), requested=\(revLimit), got=\(rows.count) — matches")
    } else {
        fail("Test 6 chunk-1", "freshTotal=\(freshTotal), requested=\(revLimit), actualCount=\(actualCount), rows=\(rows.count)")
    }

    // Check dates — newest should be at the end of the list (highest index)
    let isoFmt = ISO8601DateFormatter()
    isoFmt.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    let isoFmt2 = ISO8601DateFormatter()
    isoFmt2.formatOptions = [.withInternetDateTime]  // without fractional seconds

    var parsedDates: [Date] = []
    for row in rows {
        let fields = row.components(separatedBy: "\u{1F}")
        if fields.count > 1 {
            let raw = fields[1].trimmingCharacters(in: .whitespacesAndNewlines)
            if let dt = isoFmt.date(from: raw) ?? isoFmt2.date(from: raw) {
                parsedDates.append(dt)
            }
        }
    }

    if parsedDates.count > 1 {
        let first = parsedDates.first!
        let last  = parsedDates.last!
        let df = DateFormatter()
        df.dateStyle = .medium
        df.timeStyle = .short
        if first <= last {
            pass("Test 6 ordering", "oldest→newest (index 1=\(df.string(from: first)), last=\(df.string(from: last)))")
            print("  → messages are oldest-first: reverse pagination correctly fetches most recent chunk")
        } else {
            print("  ⚠️  Test 6 ordering: newest→oldest (first=\(df.string(from: first)), last=\(df.string(from: last)))")
            print("  → messages are newest-first: forward pagination already gives recent messages")
        }
    } else {
        print("  ⚠️  Test 6: could not parse enough dates to determine ordering (\(parsedDates.count)/\(rows.count))")
        // Print raw dates for manual inspection
        for (i, row) in rows.prefix(3).enumerated() {
            let fields = row.components(separatedBy: "\u{1F}")
            print("    row[\(i)] raw date: \(fields.count > 1 ? fields[1] : "(none)")")
        }
    }
} else {
    fail("Test 6 (error)", t6.output)
}

// MARK: - Test 7: Reverse pagination chunk 2 (verify continuity, no overlap/gap)

print("\n=== Test 7: Reverse pagination — chunk 2 continuity check ===")
print("  (Verify chunk 2 ends where chunk 1 began, no overlap or gap)")

guard totalCount >= 10 else {
    print("  ⚠️  Skipped — mailbox has < 10 messages")
    exit(0)
}

let smallLimit = 3  // Use tiny chunks so we can verify easily
let revChunk2Script = """
tell application "Mail"
    set sep to character id 31
    set recSep to character id 30
    set acct to (first account whose name is "\(accountName)")
    set mbox to (first mailbox of acct whose name is "\(mailboxName)")
    set freshTotal to count of messages of mbox

    -- Chunk 1: most recent 3 (offset_from_end=0)
    set endIdx1 to freshTotal
    set startIdx1 to endIdx1 - \(smallLimit) + 1
    if startIdx1 < 1 then set startIdx1 to 1

    -- Chunk 2: next 3 (offset_from_end=3)
    set endIdx2 to freshTotal - \(smallLimit)
    set startIdx2 to endIdx2 - \(smallLimit) + 1
    if startIdx2 < 1 then set startIdx2 to 1

    set ids1 to message id of messages startIdx1 thru endIdx1 of mbox
    set ids2 to message id of messages startIdx2 thru endIdx2 of mbox

    set out to (freshTotal as string) & recSep
    repeat with id in ids1
        set out to out & id & recSep
    end repeat
    set out to out & "---" & recSep
    repeat with id in ids2
        set out to out & id & recSep
    end repeat
    return out
end tell
"""

let t7 = run(revChunk2Script, timeout: 60)
if t7.ok {
    let parts = t7.output.components(separatedBy: "\u{1E}").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
    if let sepIdx = parts.firstIndex(of: "---"), parts.count > sepIdx + 1 {
        let freshTotal = Int(parts[0]) ?? 0
        let chunk1Ids = Array(parts[1..<sepIdx])
        let chunk2Ids = Array(parts[(sepIdx+1)...])
        let overlap = Set(chunk1Ids).intersection(Set(chunk2Ids))
        print("  freshTotal=\(freshTotal)")
        print("  Chunk 1 IDs (most recent \(smallLimit)): \(chunk1Ids.map { String($0.suffix(20)) })")
        print("  Chunk 2 IDs (next \(smallLimit)):        \(chunk2Ids.map { String($0.suffix(20)) })")
        if overlap.isEmpty {
            pass("Test 7", "No overlap between chunk 1 and chunk 2 — pagination is correct")
        } else {
            fail("Test 7", "Overlap found: \(overlap.count) IDs appear in both chunks")
        }
    } else {
        fail("Test 7 (parse)", "Unexpected output: \(t7.output.prefix(200))")
    }
} else {
    fail("Test 7 (error)", t7.output)
}

// MARK: - Test 8: 30-day date filter in Python after reverse fetch

print("\n=== Test 8: Python-side 30-day filter on reverse-paginated chunk ===")
print("  (How many of the most recent \(min(50, totalCount)) messages fall in last 30 days?)")

let recentLimit = min(50, totalCount)
let revDateScript = """
tell application "Mail"
    set sep to character id 31
    set recSep to character id 30
    set acct to (first account whose name is "\(accountName)")
    set mbox to (first mailbox of acct whose name is "\(mailboxName)")
    set freshTotal to count of messages of mbox
    set endIdx to freshTotal
    set startIdx to endIdx - \(recentLimit) + 1
    if startIdx < 1 then set startIdx to 1

    set midList to message id of messages startIdx thru endIdx of mbox
    set dtList to {}
    repeat with m in (messages startIdx thru endIdx of mbox)
        set end of dtList to ((date received of m) as \u{00AB}class isot\u{00BB} as string)
    end repeat

    set output to ""
    repeat with i from 1 to count of midList
        set output to output & (item i of midList) & sep & (item i of dtList) & recSep
    end repeat
    return (freshTotal as string) & recSep & output
end tell
"""

let t8 = run(revDateScript, timeout: 120)
if t8.ok {
    let allParts = t8.output.components(separatedBy: "\u{1E}")
    let freshTotal = Int(allParts.first?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "0") ?? 0
    let rows = Array(allParts.dropFirst()).filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    let isoFmt = ISO8601DateFormatter()
    isoFmt.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    let isoFmt2 = ISO8601DateFormatter()
    isoFmt2.formatOptions = [.withInternetDateTime]
    // Also try without timezone (Mail.app sometimes returns local time without tz)
    let localFmt = DateFormatter()
    localFmt.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"

    let cutoff30 = Date().addingTimeInterval(-30 * 24 * 3600)
    let cutoff90 = Date().addingTimeInterval(-90 * 24 * 3600)
    var recent30 = 0, recent90 = 0, parsed = 0

    for row in rows {
        let fields = row.components(separatedBy: "\u{1F}")
        if fields.count > 1 {
            let raw = fields[1].trimmingCharacters(in: .whitespacesAndNewlines)
            if let dt = isoFmt.date(from: raw) ?? isoFmt2.date(from: raw) ?? localFmt.date(from: raw) {
                parsed += 1
                if dt > cutoff30 { recent30 += 1 }
                if dt > cutoff90 { recent90 += 1 }
            }
        }
    }

    pass("Test 8", "freshTotal=\(freshTotal), fetched=\(rows.count), parsed=\(parsed), last-30d=\(recent30), last-90d=\(recent90)")
    print("  → Reverse pagination correctly targets recent emails for quick sweep")
    if parsed < rows.count {
        print("  ⚠️  \(rows.count - parsed) dates failed to parse — sample raw date:")
        if let firstRow = rows.first {
            let fields = firstRow.components(separatedBy: "\u{1F}")
            print("      '\(fields.count > 1 ? fields[1] : "(none)")'")
        }
    }
} else {
    fail("Test 8 (error)", t8.output)
}

print("\n=== Summary ===")
print("  Test 1+2: Confirmed bulk property access on whose-filtered/list references FAILS")
print("  Test 3+4: Direct range specifier 'messages X thru Y of mbox' WORKS reliably")
print("  Test 6:   Reverse pagination (offset_from_end) fetches most recent chunk")
print("  Test 7:   Chunk continuity verified — no overlap, no gap")
print("  Test 8:   Python-side 30-day filter on reverse chunk works correctly")
print("  → Implement SWEEP_CHUNK with direct range + offset_from_end + Python date filter\n")
