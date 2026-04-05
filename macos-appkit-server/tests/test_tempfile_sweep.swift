#!/usr/bin/env swift
/// Test: single osascript spawn, write chunks to temp files, Python reads directly.
///
/// Hypothesis: one spawn + file writes is faster than N spawns + string returns
/// because:
///   1. Spawn overhead paid only once (8.3s fixed)
///   2. No AppleScript string concat (O(n²)) — write each line immediately
///   3. No return value size limit
///   4. Python reads files in parallel if it wants
///
/// Run with:
///   swift macos-appkit-server/tests/test_tempfile_sweep.swift

import Foundation

// MARK: - Runner

func run(_ script: String, timeout: TimeInterval = 600) -> (ok: Bool, output: String, elapsed: Double) {
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

func parseRows(_ raw: String) -> [[String]] {
    raw.components(separatedBy: "\u{1E}")
        .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        .filter { !$0.isEmpty }
        .map { $0.components(separatedBy: "\u{1F}") }
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
guard dp.count == 3 else { print("❌ Parse error"); exit(1) }
let acct = dp[0]; let mbox = dp[1]; let total = Int(dp[2]) ?? 0
print("  Account : \(acct)")
print("  Mailbox : \(mbox)")
print("  Messages: \(total)")
guard total >= 1000 else { print("⚠️  Need 1000+ messages."); exit(1) }

// How many messages to test with — cap at 5000 so test completes in reasonable time
let testMsgs = min(5000, total)
let chunkSize = 1000
let numChunks = Int(ceil(Double(testMsgs) / Double(chunkSize)))

print("  Testing with: first \(testMsgs) messages in \(numChunks) chunks of \(chunkSize)")

// MARK: - Approach A: Baseline — N separate osascript spawns (current approach)

print("\n=== Approach A: N separate spawns (current approach) ===")
print("  \(numChunks) osascript processes, each returns \(chunkSize) messages as string")

func currentApproachScript(_ acct: String, _ mbox: String, offset: Int, limit: Int) -> String {
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

let startA = Date()
var allIdsA: [String] = []
var pageTimesA: [Double] = []

for chunk in 0..<numChunks {
    let offset = chunk * chunkSize
    let limit = min(chunkSize, testMsgs - offset)
    let r = run(currentApproachScript(acct, mbox, offset: offset, limit: limit))
    pageTimesA.append(r.elapsed)
    if r.ok {
        let ids = parseRows(r.output).compactMap { $0.first }
        allIdsA.append(contentsOf: ids)
        print("  chunk \(chunk+1)/\(numChunks) (offset=\(offset)): \(ids.count) msgs in \(String(format: "%.2f", r.elapsed))s")
    } else {
        print("  chunk \(chunk+1)/\(numChunks): ❌ \(r.output.prefix(80))")
    }
}
let elapsedA = Date().timeIntervalSince(startA)
print("  Total: \(allIdsA.count) msgs in \(String(format: "%.2f", elapsedA))s  (\(String(format: "%.1f", elapsedA/Double(allIdsA.count)*1000))ms/msg)")

// MARK: - Approach B: Single spawn, all chunks written to temp files

print("\n=== Approach B: Single spawn, chunks → temp files ===")
print("  1 osascript process, \(numChunks) temp files, Python reads files")

// Build the AppleScript dynamically for N chunks
// Each chunk: open file, loop startIdx..endIdx, write each line, close file
var chunkBlocks = ""
var filePathLines = ""
for chunk in 0..<numChunks {
    let startIdx = chunk * chunkSize + 1
    let endIdx = min((chunk + 1) * chunkSize, testMsgs)
    let tmpPath = "/tmp/if-sweep-chunk-\(chunk).tsv"
    chunkBlocks += """
    
                        -- Chunk \(chunk+1): messages \(startIdx)–\(endIdx)
                        set chunkFile to open for access POSIX file "\(tmpPath)" with write permission
                        set eof of chunkFile to 0
                        set safeEnd to \(endIdx)
                        if safeEnd > msgCount then set safeEnd to msgCount
                        repeat with i from \(startIdx) to safeEnd
                            set m to item i of msgs
                            set mid to message id of m
                            set subj to subject of m
                            set sndr to sender of m
                            set dt to (date received of m) as \u{00AB}class isot\u{00BB} as string
                            write (mid & tab & subj & tab & sndr & tab & dt & tab & mboxName & tab & acctName & linefeed) to chunkFile
                        end repeat
                        close access chunkFile
    """
    filePathLines += (chunk > 0 ? "," : "") + tmpPath
}

let singleSpawnScript = """
tell application "Mail"
    set acct to (first account whose name is "\(acct)")
    set mbox to (first mailbox of acct whose name is "\(mbox)")
    set msgs to messages of mbox
    set msgCount to count of msgs
    set acctName to name of acct
    set mboxName to name of mbox
    \(chunkBlocks)
    return "\(filePathLines)"
end tell
"""

let startB = Date()
let resultB = run(singleSpawnScript, timeout: 600)
let elapsedB = Date().timeIntervalSince(startB)

var allIdsB: [String] = []
var totalBytesB: Int = 0

if resultB.ok {
    print("  AppleScript completed in \(String(format: "%.2f", elapsedB))s")
    print("  Files written: \(resultB.output)")
    print("  Reading files...")

    let filePaths = resultB.output.components(separatedBy: ",").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
    let fileReadStart = Date()

    for path in filePaths {
        guard let content = try? String(contentsOfFile: path, encoding: .utf8) else {
            print("  ❌ Could not read \(path)")
            continue
        }
        totalBytesB += content.utf8.count
        let lines = content.components(separatedBy: "\n").filter { !$0.isEmpty }
        let ids = lines.compactMap { $0.components(separatedBy: "\t").first }.filter { !$0.isEmpty }
        allIdsB.append(contentsOf: ids)

        // Cleanup
        try? FileManager.default.removeItem(atPath: path)
    }

    let fileReadElapsed = Date().timeIntervalSince(fileReadStart)
    let msPerMsg = allIdsB.count > 0 ? elapsedB / Double(allIdsB.count) * 1000.0 : 0
    print("  Messages read: \(allIdsB.count)")
    print("  Total file size: \(String(format: "%.1f", Double(totalBytesB)/1024.0)) KB")
    print("  File read time: \(String(format: "%.3f", fileReadElapsed))s")
    print("  Total: \(allIdsB.count) msgs in \(String(format: "%.2f", elapsedB))s  (\(String(format: "%.1f", msPerMsg))ms/msg)")
} else {
    print("  ❌ Single-spawn script failed: \(resultB.output.prefix(200))")
}

// MARK: - Approach C: Single spawn, ALL messages one file (no chunking)

print("\n=== Approach C: Single spawn, single file (no chunking) ===")
print("  1 osascript process, 1 temp file, write line-by-line")

let singleFilePath = "/tmp/if-sweep-all.tsv"
let singleFileScript = """
tell application "Mail"
    set acct to (first account whose name is "\(acct)")
    set mbox to (first mailbox of acct whose name is "\(mbox)")
    set msgs to messages of mbox
    set msgCount to count of msgs
    set acctName to name of acct
    set mboxName to name of mbox
    set outFile to open for access POSIX file "\(singleFilePath)" with write permission
    set eof of outFile to 0
    set safeEnd to \(testMsgs)
    if safeEnd > msgCount then set safeEnd to msgCount
    repeat with i from 1 to safeEnd
        set m to item i of msgs
        set mid to message id of m
        set subj to subject of m
        set sndr to sender of m
        set dt to (date received of m) as \u{00AB}class isot\u{00BB} as string
        write (mid & tab & subj & tab & sndr & tab & dt & tab & mboxName & tab & acctName & linefeed) to outFile
    end repeat
    close access outFile
    return "\(singleFilePath)"
end tell
"""

let startC = Date()
let resultC = run(singleFileScript, timeout: 600)
let elapsedC = Date().timeIntervalSince(startC)

var allIdsC: [String] = []
if resultC.ok {
    if let content = try? String(contentsOfFile: singleFilePath, encoding: .utf8) {
        let lines = content.components(separatedBy: "\n").filter { !$0.isEmpty }
        allIdsC = lines.compactMap { $0.components(separatedBy: "\t").first }.filter { !$0.isEmpty }
        let fileSize = Double((try? FileManager.default.attributesOfItem(atPath: singleFilePath)[.size] as? Int ?? 0) ?? 0) / 1024.0
        try? FileManager.default.removeItem(atPath: singleFilePath)
        let msPerMsg = allIdsC.count > 0 ? elapsedC / Double(allIdsC.count) * 1000.0 : 0
        print("  Messages: \(allIdsC.count)")
        print("  File size: \(String(format: "%.1f", fileSize)) KB")
        print("  Total: \(allIdsC.count) msgs in \(String(format: "%.2f", elapsedC))s  (\(String(format: "%.1f", msPerMsg))ms/msg)")
    }
} else {
    print("  ❌ Failed: \(resultC.output.prefix(200))")
}

// MARK: - Comparison

print("\n=== Comparison ===")
print("")

let countA = allIdsA.count
let countB = allIdsB.count
let countC = allIdsC.count

print("  \("Approach".padding(toLength: 40, withPad: " ", startingAt: 0))\("Msgs".padding(toLength: 8, withPad: " ", startingAt: 0))\("Time".padding(toLength: 10, withPad: " ", startingAt: 0))\("ms/msg".padding(toLength: 10, withPad: " ", startingAt: 0))Spawns")
print("  \("─".padding(toLength: 80, withPad: "─", startingAt: 0))")

func row(_ label: String, _ count: Int, _ elapsed: Double, _ spawns: Int) -> String {
    let ms = count > 0 ? elapsed / Double(count) * 1000 : 0
    return "  \(label.padding(toLength: 40, withPad: " ", startingAt: 0))\(String(count).padding(toLength: 8, withPad: " ", startingAt: 0))\(String(format: "%.2fs", elapsed).padding(toLength: 10, withPad: " ", startingAt: 0))\(String(format: "%.1f", ms).padding(toLength: 10, withPad: " ", startingAt: 0))\(spawns)"
}

print(row("A: \(numChunks) separate spawns (current)", countA, elapsedA, numChunks))
if countB > 0 { print(row("B: 1 spawn + \(numChunks) temp files", countB, elapsedB, 1)) }
if countC > 0 { print(row("C: 1 spawn + 1 temp file (all msgs)", countC, elapsedC, 1)) }

// Content identity check
print("")
if countA > 0 && countB > 0 {
    let setA = Set(allIdsA); let setB = Set(allIdsB)
    if setA == setB {
        print("  ✅ A vs B: identical message IDs")
    } else {
        let onlyA = setA.subtracting(setB); let onlyB = setB.subtracting(setA)
        print("  ⚠️  A vs B: only-in-A=\(onlyA.count) only-in-B=\(onlyB.count)")
    }
}
if countA > 0 && countC > 0 {
    let setA = Set(allIdsA); let setC = Set(allIdsC)
    if setA == setC {
        print("  ✅ A vs C: identical message IDs")
    } else {
        let onlyA = setA.subtracting(setC); let onlyC = setC.subtracting(setA)
        print("  ⚠️  A vs C: only-in-A=\(onlyA.count) only-in-C=\(onlyC.count)")
    }
}

// Speedup
if countA > 0 && countB > 0 && elapsedB > 0 {
    let speedup = elapsedA / elapsedB
    print("")
    if speedup > 1.1 {
        print("  ✅ B is \(String(format: "%.1f", speedup))× faster than A (temp file wins)")
    } else if speedup < 0.9 {
        print("  ⚠️  A is \(String(format: "%.1f", 1/speedup))× faster than B (current approach wins)")
    } else {
        print("  ≈  A and B are similar speed")
    }
}

// Extrapolate to full mailbox
print("")
print("  Extrapolated to full mailbox (\(total) msgs):")
if countA > 0 {
    let estA = elapsedA / Double(countA) * Double(total)
    print("  A (current \(numChunks) spawns): \(String(format: "%.0f", estA))s  (~\(String(format: "%.0f", estA/60))min)")
}
if countB > 0 {
    let estB = elapsedB / Double(countB) * Double(total)
    print("  B (1 spawn, chunked files): \(String(format: "%.0f", estB))s  (~\(String(format: "%.0f", estB/60))min)")
}
if countC > 0 {
    let estC = elapsedC / Double(countC) * Double(total)
    print("  C (1 spawn, single file): \(String(format: "%.0f", estC))s  (~\(String(format: "%.0f", estC/60))min)")
}
print("")
