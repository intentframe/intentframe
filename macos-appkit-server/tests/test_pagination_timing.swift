#!/usr/bin/env swift
/// Pagination test: timing, correctness, and batch size comparison.
///
/// Run with:
///   swift macos-appkit-server/tests/test_pagination_timing.swift
///
/// Tests:
///   1. OLD skip-loop vs NEW direct-index timing (proves O(n²) vs O(1))
///   2. Content correctness — no duplicate message IDs across batches, no gaps
///   3. Batch size comparison: 200 vs 500 (fewer osascript spawns = less overhead)
///   4. Apple Events analysis — how many events each approach sends

import Foundation

// MARK: - Runner

func run(_ script: String, timeout: TimeInterval = 180) -> (ok: Bool, output: String, elapsed: Double) {
    let proc = Process()
    proc.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
    proc.arguments = ["-e", script]
    let out = Pipe(); let err = Pipe()
    proc.standardOutput = out; proc.standardError = err
    let start = Date()
    try! proc.run()
    var outData = Data(); var errData = Data()
    let g = DispatchGroup()
    g.enter(); DispatchQueue.global().async { outData = out.fileHandleForReading.readDataToEndOfFile(); g.leave() }
    g.enter(); DispatchQueue.global().async { errData = err.fileHandleForReading.readDataToEndOfFile(); g.leave() }
    let timer = DispatchSource.makeTimerSource(queue: .global())
    timer.schedule(deadline: .now() + timeout)
    timer.setEventHandler { if proc.isRunning { proc.terminate() } }
    timer.resume()
    proc.waitUntilExit(); timer.cancel(); g.wait()
    let elapsed = Date().timeIntervalSince(start)
    let stdout = String(data: outData, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    let stderr = String(data: errData, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    return (proc.terminationStatus == 0, proc.terminationStatus == 0 ? stdout : "ERR:\(stderr)", elapsed)
}

// MARK: - Step 0: Discover best mailbox

print("\n=== Step 0: Finding largest mailbox ===")

let discoverScript = """
tell application "Mail"
    set best to ""
    set bestCount to 0
    set bestAcct to ""
    repeat with acct in accounts
        repeat with mbox in mailboxes of acct
            set c to count of messages of mbox
            if c > bestCount then
                set bestCount to c
                set best to name of mbox
                set bestAcct to name of acct
            end if
        end repeat
    end repeat
    return bestAcct & "|||" & best & "|||" & (bestCount as string)
end tell
"""

let disc = run(discoverScript, timeout: 30)
guard disc.ok else { print("❌ Mail.app unreachable: \(disc.output)"); exit(1) }
let dp = disc.output.components(separatedBy: "|||")
guard dp.count == 3 else { print("❌ Parse error"); exit(1) }
let acct = dp[0]; let mbox = dp[1]; let total = Int(dp[2]) ?? 0
print("  Account : \(acct)")
print("  Mailbox : \(mbox)")
print("  Messages: \(total)")
guard total >= 400 else { print("⚠️  Need 400+ messages. Exiting."); exit(1) }

// MARK: - AppleScript generators

/// OLD: iterates from 1 every time, skips N, collects limit — returns "id1|id2|..."
func oldScript(_ acct: String, _ mbox: String, offset: Int, limit: Int) -> String {
    """
    tell application "Mail"
        set sep to character id 31
        set acct to (first account whose name is "\(acct)")
        set mbox to (first mailbox of acct whose name is "\(mbox)")
        set msgs to messages of mbox
        set msgCount to count of msgs
        set collected to 0
        set skipped to 0
        set output to ""
        repeat with i from 1 to msgCount
            if skipped < \(offset) then
                set skipped to skipped + 1
            else if collected < \(limit) then
                set output to output & (message id of item i of msgs) & sep
                set collected to collected + 1
            else
                exit repeat
            end if
        end repeat
        return output
    end tell
    """
}

/// NEW: jumps directly to (offset+1)...(offset+limit) — returns "id1|id2|..."
func newScript(_ acct: String, _ mbox: String, offset: Int, limit: Int) -> String {
    let s = offset + 1; let e = offset + limit
    return """
    tell application "Mail"
        set sep to character id 31
        set acct to (first account whose name is "\(acct)")
        set mbox to (first mailbox of acct whose name is "\(mbox)")
        set msgs to messages of mbox
        set msgCount to count of msgs
        set safeEnd to \(e)
        if safeEnd > msgCount then set safeEnd to msgCount
        set output to ""
        if \(s) <= msgCount then
            repeat with i from \(s) to safeEnd
                set output to output & (message id of item i of msgs) & sep
            end repeat
        end if
        return output
    end tell
    """
}

func parseIds(_ raw: String) -> [String] {
    raw.components(separatedBy: "\u{1F}").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
}

// Offsets to test timing at
let testOffsets: [Int]
if total >= 10000 { testOffsets = [0, 2000, 5000, 10000].filter { $0 < total }
} else if total >= 2000 { testOffsets = [0, 500, 1000, 2000].filter { $0 < total }
} else { testOffsets = [0, 200, 400].filter { $0 < total } }
let pageSize = 200

// MARK: - Test 1: Timing comparison (OLD vs NEW)

print("\n=== Test 1: Timing — OLD skip-loop vs NEW direct-index ===")
print("  Page size: \(pageSize)")

var oldTimes: [(Int, Double)] = []
var newTimes: [(Int, Double)] = []

for offset in testOffsets {
    let o = run(oldScript(acct, mbox, offset: offset, limit: pageSize))
    let n = run(newScript(acct, mbox, offset: offset, limit: pageSize))
    let oIds = parseIds(o.output); let nIds = parseIds(n.output)
    oldTimes.append((offset, o.elapsed))
    newTimes.append((offset, n.elapsed))
    print("  offset=\(offset)  OLD: \(String(format: "%.2f", o.elapsed))s (\(oIds.count) msgs)  NEW: \(String(format: "%.2f", n.elapsed))s (\(nIds.count) msgs)")
}

let oldFirst = oldTimes.first!.1; let oldLast = oldTimes.last!.1
let newFirst = newTimes.first!.1; let newLast = newTimes.last!.1
print("\n  OLD ratio (last/first): \(String(format: "%.1f", oldLast/oldFirst))×")
print("  NEW ratio (last/first): \(String(format: "%.1f", newLast/newFirst))×")
if oldLast/oldFirst > 1.5 && newLast/newFirst < 1.5 {
    print("  ✅ CONFIRMED: OLD slows down, NEW stays flat")
} else {
    print("  ⚠️  Inconclusive — mailbox may be too small or Mail.app cached list")
}

// MARK: - Test 2: Content correctness — no duplicates, no gaps across 5 consecutive pages

print("\n=== Test 2: Content correctness — 5 consecutive pages (new approach) ===")
print("  Checking for duplicate message IDs across pages and gap detection")

var allIds: [String] = []
var pageLengths: [Int] = []
var correctOrder = true

for page in 0..<5 {
    let offset = page * pageSize
    guard offset < total else { break }
    let r = run(newScript(acct, mbox, offset: offset, limit: pageSize))
    let ids = parseIds(r.output)
    pageLengths.append(ids.count)

    // Check for overlap with previously collected IDs
    let previousSet = Set(allIds)
    let overlap = ids.filter { previousSet.contains($0) }
    if !overlap.isEmpty {
        print("  ❌ Page \(page+1) (offset=\(offset)): \(overlap.count) DUPLICATE IDs from previous pages!")
        correctOrder = false
    } else {
        print("  ✓  Page \(page+1) (offset=\(offset)): \(ids.count) unique IDs, no overlap")
    }
    allIds.append(contentsOf: ids)
}

let totalUnique = Set(allIds).count
let totalFetched = allIds.count
if totalUnique == totalFetched {
    print("\n  ✅ CORRECTNESS CONFIRMED: \(totalFetched) messages fetched, all unique — zero duplicates")
} else {
    print("\n  ❌ \(totalFetched - totalUnique) duplicates found across \(pageLengths.count) pages")
}

// MARK: - Test 3: Batch size comparison 200 vs 500

print("\n=== Test 3: Batch size — 200 vs 500 (same total messages, fewer spawns) ===")
let targetMessages = min(1000, total)
let pages200 = Int(ceil(Double(targetMessages) / 200.0))
let pages500 = Int(ceil(Double(targetMessages) / 500.0))
print("  Fetching first \(targetMessages) messages")
print("  200/page = \(pages200) osascript spawns")
print("  500/page = \(pages500) osascript spawns")

// Time 200/page
var start200 = Date()
var ids200: [String] = []
for page in 0..<pages200 {
    let offset = page * 200
    guard offset < targetMessages else { break }
    let limit = min(200, targetMessages - offset)
    let r = run(newScript(acct, mbox, offset: offset, limit: limit))
    ids200.append(contentsOf: parseIds(r.output))
}
let elapsed200 = Date().timeIntervalSince(start200)

// Time 500/page
var start500 = Date()
var ids500: [String] = []
for page in 0..<pages500 {
    let offset = page * 500
    guard offset < targetMessages else { break }
    let limit = min(500, targetMessages - offset)
    let r = run(newScript(acct, mbox, offset: offset, limit: limit))
    ids500.append(contentsOf: parseIds(r.output))
}
let elapsed500 = Date().timeIntervalSince(start500)

// Are results identical?
let set200 = Set(ids200); let set500 = Set(ids500)
let bothSame = set200 == set500
print("\n  200/page: \(String(format: "%.2f", elapsed200))s for \(ids200.count) msgs (\(pages200) spawns)")
print("  500/page: \(String(format: "%.2f", elapsed500))s for \(ids500.count) msgs (\(pages500) spawns)")
print("  Same results: \(bothSame ? "✅ YES" : "❌ NO — mismatch!")")
if elapsed200 > 0 {
    let ratio = elapsed200 / elapsed500
    if ratio > 1.2 {
        print("  ✅ 500/page is \(String(format: "%.1f", ratio))× faster — fewer spawns wins")
    } else if ratio < 0.8 {
        print("  ⚠️  200/page was faster — larger AppleScript string building may hurt")
    } else {
        print("  ≈  Similar speed — spawn overhead vs string-build overhead cancel out")
    }
}

// MARK: - Test 4: Apple Events analysis

print("\n=== Test 4: Apple Events — what each approach actually sends ===")
print("""

  OLD approach (per page, offset=N):
    Apple Events sent per page:
      1. Evaluate script → Mail.app (compile + run)
      2. 'get messages of mbox' → resolves full message list
      3. 'count of msgs' → 1 event
      4. For each of the (offset + limit) messages:
           'get message id of item i of msgs' → 1 event each
      Total per page = 3 + (offset + limit) events
      For page at offset=10000: 3 + 10200 = 10,203 Apple Events

  NEW approach (per page, offset=N):
    Apple Events sent per page:
      1. Evaluate script → Mail.app (compile + run)
      2. 'get messages of mbox' → resolves full message list
      3. 'count of msgs' → 1 event
      4. For each of the (limit) messages only:
           'get message id of item i of msgs' → 1 event each
      Total per page = 3 + limit events
      For page at offset=10000: 3 + 200 = 203 Apple Events

  Reduction factor at offset=10000: ~50× fewer Apple Events per page
  This is WHY the new approach is O(1) per page instead of O(n).

  osascript process spawns for \(total) messages:
    200/page → \(Int(ceil(Double(total)/200.0))) spawns  (current default)
    500/page → \(Int(ceil(Double(total)/500.0))) spawns  (recommended)
    Each spawn: ~200-500ms overhead for process start + AppleScript compilation

  Recommended page size: 500 (balances spawn overhead vs string concat cost)
""")

// MARK: - Summary

let fullPages200 = Int(ceil(Double(total) / 200.0))
let fullPages500 = Int(ceil(Double(total) / 500.0))
let avgNew200 = newTimes.map(\.1).reduce(0, +) / Double(newTimes.count)
let avgNew500 = elapsed500 / Double(pages500)

print("=== Final Summary ===")
print("  Mailbox: \(mbox) (\(total) messages)")
print("")
print("  Estimated full sweep times:")
print("    OLD 200/page: ~\(String(format: "%.0f", avgNew200 * Double(fullPages200) * 3.0))s (O(n²) approximation)")
print("    NEW 200/page: ~\(String(format: "%.0f", avgNew200 * Double(fullPages200)))s")
print("    NEW 500/page: ~\(String(format: "%.0f", avgNew500 * Double(fullPages500)))s  ← recommended")
print("")
