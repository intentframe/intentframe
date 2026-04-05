#!/usr/bin/env swift
/// Batch size sweep — find the optimal page size for GET_HEADERS.
///
/// Run with:
///   swift macos-appkit-server/tests/test_batch_size.swift
///
/// What this finds:
///   - Time per message at each batch size (lower = better)
///   - Point where string concat O(n²) starts hurting
///   - Point where timeout kicks in
///   - Memory pressure indicators (slow last few batches)
///   - Cross-verify OLD vs NEW return identical content at each size

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

func parseIds(_ raw: String) -> [String] {
    raw.components(separatedBy: "\u{1F}").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
}

// MARK: - Step 0: Discover mailbox

print("\n=== Step 0: Finding largest mailbox ===")

let disc = run("""
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
""", timeout: 30)

guard disc.ok else { print("❌ Mail.app unreachable: \(disc.output)"); exit(1) }
let dp = disc.output.components(separatedBy: "|||")
guard dp.count == 3 else { print("❌ Parse error: \(disc.output)"); exit(1) }
let acct = dp[0]; let mbox = dp[1]; let total = Int(dp[2]) ?? 0
print("  Account : \(acct)")
print("  Mailbox : \(mbox)")
print("  Messages: \(total)")
guard total >= 500 else { print("⚠️  Need 500+ messages. Exiting."); exit(1) }

// MARK: - Script builders

/// NEW direct-index script — fetches all 6 fields, same as production GET_HEADERS
func fetchScript(_ acct: String, _ mbox: String, offset: Int, limit: Int) -> String {
    let s = offset + 1; let e = offset + limit
    return """
    tell application "Mail"
        set sep to character id 31
        set recSep to character id 30
        set output to ""
        set acct to (first account whose name is "\(acct)")
        set mbox to (first mailbox of acct whose name is "\(mbox)")
        set msgs to messages of mbox
        set msgCount to count of msgs
        set safeEnd to \(e)
        if safeEnd > msgCount then set safeEnd to msgCount
        if \(s) <= msgCount then
            set acctName to name of acct
            set mboxName to name of mbox
            repeat with i from \(s) to safeEnd
                set m to item i of msgs
                set mid to message id of m
                set subj to subject of m
                set sndr to sender of m
                set dt to (date received of m) as \u{00AB}class isot\u{00BB} as string
                set output to output & mid & sep & subj & sep & sndr & sep & dt & sep & mboxName & sep & acctName & recSep
            end repeat
        end if
        return output
    end tell
    """
}

/// OLD skip-loop script — same fields, skips from 1
func fetchScriptOld(_ acct: String, _ mbox: String, offset: Int, limit: Int) -> String {
    return """
    tell application "Mail"
        set sep to character id 31
        set recSep to character id 30
        set output to ""
        set acct to (first account whose name is "\(acct)")
        set mbox to (first mailbox of acct whose name is "\(mbox)")
        set msgs to messages of mbox
        set msgCount to count of msgs
        set collected to 0
        set skipped to 0
        set acctName to name of acct
        set mboxName to name of mbox
        repeat with i from 1 to msgCount
            if skipped < \(offset) then
                set skipped to skipped + 1
            else if collected < \(limit) then
                set m to item i of msgs
                set mid to message id of m
                set subj to subject of m
                set sndr to sender of m
                set dt to (date received of m) as \u{00AB}class isot\u{00BB} as string
                set output to output & mid & sep & subj & sep & sndr & sep & dt & sep & mboxName & sep & acctName & recSep
                set collected to collected + 1
            else
                exit repeat
            end if
        end repeat
        return output
    end tell
    """
}

func parseRows(_ raw: String) -> [[String]] {
    raw.components(separatedBy: "\u{1E}")
        .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        .filter { !$0.isEmpty }
        .map { $0.components(separatedBy: "\u{1F}") }
}

// MARK: - Test 1: Batch size sweep

print("\n=== Test 1: Batch size sweep — time/msg at different page sizes ===")
print("  (Finding the sweet spot: faster per-message = better)")
print("  (String concat O(n²) will show up as time/msg rising at large sizes)")
print("")
print("  \("Size".padding(toLength: 8, withPad: " ", startingAt: 0))" +
      "\("Got".padding(toLength: 8, withPad: " ", startingAt: 0))" +
      "\("Time".padding(toLength: 10, withPad: " ", startingAt: 0))" +
      "\("ms/msg".padding(toLength: 10, withPad: " ", startingAt: 0))" +
      "\("Output KB".padding(toLength: 12, withPad: " ", startingAt: 0))" +
      "Status")

let batchSizes = [100, 200, 500, 1000, 2000, 3000, 5000]
var results: [(size: Int, count: Int, elapsed: Double, msPerMsg: Double, ok: Bool)] = []

for size in batchSizes {
    guard size <= total else {
        print("  \(size): skipped (mailbox only has \(total) messages)")
        continue
    }
    let r = run(fetchScript(acct, mbox, offset: 0, limit: size), timeout: 180)
    let rows = parseRows(r.output)
    let count = rows.count
    let msPerMsg = count > 0 ? r.elapsed / Double(count) * 1000.0 : 0
    let outputKB = Double(r.output.utf8.count) / 1024.0
    let status: String
    if !r.ok { status = "❌ ERROR" }
    else if count < size && size <= total { status = "⚠️  PARTIAL (timeout?)" }
    else { status = "✅" }

    results.append((size, count, r.elapsed, msPerMsg, r.ok && count >= size))

    print("  \(String(size).padding(toLength: 8, withPad: " ", startingAt: 0))" +
          "\(String(count).padding(toLength: 8, withPad: " ", startingAt: 0))" +
          "\(String(format: "%.2fs", r.elapsed).padding(toLength: 10, withPad: " ", startingAt: 0))" +
          "\(String(format: "%.1f", msPerMsg).padding(toLength: 10, withPad: " ", startingAt: 0))" +
          "\(String(format: "%.1f", outputKB).padding(toLength: 12, withPad: " ", startingAt: 0))" +
          status)
}

// Find optimal
if let best = results.filter({ $0.ok }).min(by: { $0.msPerMsg < $1.msPerMsg }) {
    print("\n  ✅ Optimal batch size: \(best.size) (\(String(format: "%.1f", best.msPerMsg))ms/msg)")
}

// Detect string concat degradation
let goodResults = results.filter { $0.ok }
if goodResults.count >= 3 {
    let first = goodResults.first!; let last = goodResults.last!
    if last.msPerMsg > first.msPerMsg * 1.5 {
        print("  ⚠️  String concat slowdown detected: \(first.size) → \(last.size) increased from \(String(format: "%.1f", first.msPerMsg))ms to \(String(format: "%.1f", last.msPerMsg))ms/msg")
    }
}

// MARK: - Test 2: OLD vs NEW content identity at 3 sizes

print("\n=== Test 2: OLD vs NEW — same content? (cross-verify) ===")
print("  At each size, both approaches should return identical message IDs in same order")
print("")

let verifyOffsets = [0, 500, 2000].filter { $0 < total }
let verifySize = 200

for offset in verifyOffsets {
    let newR = run(fetchScript(acct, mbox, offset: offset, limit: verifySize))
    let oldR = run(fetchScriptOld(acct, mbox, offset: offset, limit: verifySize))

    let newRows = parseRows(newR.output)
    let oldRows = parseRows(oldR.output)

    let newIds = newRows.map { $0.first ?? "" }
    let oldIds = oldRows.map { $0.first ?? "" }

    if newIds == oldIds {
        print("  ✅ offset=\(offset): identical (\(newIds.count) msgs, same order)")
    } else if Set(newIds) == Set(oldIds) {
        print("  ⚠️  offset=\(offset): same IDs but different order (\(newIds.count) msgs)")
    } else {
        let onlyNew = Set(newIds).subtracting(Set(oldIds))
        let onlyOld = Set(oldIds).subtracting(Set(newIds))
        print("  ❌ offset=\(offset): DIFFERENT — only-new: \(onlyNew.count), only-old: \(onlyOld.count)")
    }
}

// MARK: - Test 3: Multi-page sweep — validate no drift over time

print("\n=== Test 3: Multi-page continuity — does offset drift? ===")
print("  Fetch 10 consecutive pages, verify no gaps or overlaps")
print("  (Would catch mailbox changes mid-sweep)")

let contSize = 200
let numPages = 10
var allIds: [String] = []
var pageTimes: [Double] = []
var driftDetected = false

for page in 0..<numPages {
    let offset = page * contSize
    guard offset < total else { break }
    let r = run(fetchScript(acct, mbox, offset: offset, limit: contSize))
    let rows = parseRows(r.output)
    let ids = rows.map { $0.first ?? "" }.filter { !$0.isEmpty }
    pageTimes.append(r.elapsed)

    let prevSet = Set(allIds)
    let overlapping = ids.filter { prevSet.contains($0) }
    if !overlapping.isEmpty {
        print("  ❌ Page \(page+1) (offset=\(offset)): \(overlapping.count) IDs already seen!")
        driftDetected = true
    }
    allIds.append(contentsOf: ids)
}

if !driftDetected {
    print("  ✅ \(numPages) pages, \(allIds.count) messages — no drift, no overlap")
}
let avgPageTime = pageTimes.reduce(0, +) / Double(pageTimes.count)
let minPageTime = pageTimes.min() ?? 0
let maxPageTime = pageTimes.max() ?? 0
print("  Page timing: avg=\(String(format: "%.2f", avgPageTime))s  min=\(String(format: "%.2f", minPageTime))s  max=\(String(format: "%.2f", maxPageTime))s")
if maxPageTime / minPageTime > 1.5 {
    print("  ⚠️  High variance — page times vary \(String(format: "%.1f", maxPageTime/minPageTime))× (possible Mail.app load fluctuation)")
} else {
    print("  ✅ Consistent page times (low variance)")
}

// MARK: - Test 4: Extrapolate full sweep times

print("\n=== Test 4: Full sweep time projection ===")
print("  Based on measured ms/msg and spawn overhead")
print("")

if !results.isEmpty {
    // Fixed spawn overhead = intercept of time vs messages line
    // Use two data points to estimate fixed overhead
    let r200 = results.first(where: { $0.size == 200 })
    let r500 = results.first(where: { $0.size == 500 })

    var spawnOverhead: Double = 8.0  // default estimate
    var msPerMsgVar: Double = 8.0

    if let a = r200, let b = r500, a.ok && b.ok {
        // a.elapsed = overhead + a.count * perMsg
        // b.elapsed = overhead + b.count * perMsg
        // => perMsg = (b.elapsed - a.elapsed) / (b.count - a.count)
        let perMsg = (b.elapsed - a.elapsed) / Double(b.count - a.count)
        let overhead = a.elapsed - Double(a.count) * perMsg
        spawnOverhead = max(0, overhead)
        msPerMsgVar = perMsg * 1000.0
        print("  Estimated spawn overhead: \(String(format: "%.2f", spawnOverhead))s/spawn")
        print("  Estimated per-message cost: \(String(format: "%.2f", msPerMsgVar))ms/msg")
        print("")
    }

    print("  \("Page size".padding(toLength: 12, withPad: " ", startingAt: 0))" +
          "\("Spawns".padding(toLength: 10, withPad: " ", startingAt: 0))" +
          "\("Est. time for \(total) msgs".padding(toLength: 28, withPad: " ", startingAt: 0))")

    for size in [200, 500, 1000, 2000] {
        guard size <= total else { continue }
        let spawns = Int(ceil(Double(total) / Double(size)))
        // Use measured ms/msg if available, else estimate
        let msMsg: Double
        if let measured = results.first(where: { $0.size == size }), measured.ok {
            msMsg = measured.msPerMsg
        } else {
            msMsg = (msPerMsgVar + spawnOverhead * 1000.0 / Double(size))
        }
        let estSeconds = Double(total) * msMsg / 1000.0
        let estMin = estSeconds / 60.0
        print("  \(String(size).padding(toLength: 12, withPad: " ", startingAt: 0))" +
              "\(String(spawns).padding(toLength: 10, withPad: " ", startingAt: 0))" +
              "\(String(format: "%.0fs (~%.1f min)", estSeconds, estMin))")
    }
}

print("\n=== Summary ===")
if let best = results.filter({ $0.ok }).min(by: { $0.msPerMsg < $1.msPerMsg }) {
    print("  Recommended page size: \(best.size)")
    print("  Reason: lowest ms/msg measured (\(String(format: "%.1f", best.msPerMsg))ms/msg)")
}
print("")
