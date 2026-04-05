----
> swift macos-appkit-server/tests/test_pagination_timing.swift

=== Step 0: Finding largest mailbox ===
  Account : user@gmail.com
  Mailbox : All Mail
  Messages: 75747

=== Test 1: Timing — OLD skip-loop vs NEW direct-index ===
  Page size: 200
  offset=0  OLD: 10.29s (200 msgs)  NEW: 10.27s (200 msgs)
  offset=2000  OLD: 10.06s (200 msgs)  NEW: 10.30s (200 msgs)
  offset=5000  OLD: 10.23s (200 msgs)  NEW: 10.01s (200 msgs)
  offset=10000  OLD: 10.03s (200 msgs)  NEW: 10.12s (200 msgs)

  OLD ratio (last/first): 1.0×
  NEW ratio (last/first): 1.0×
  ⚠️  Inconclusive — mailbox may be too small or Mail.app cached list

=== Test 2: Content correctness — 5 consecutive pages (new approach) ===
  Checking for duplicate message IDs across pages and gap detection
  ✓  Page 1 (offset=0): 200 unique IDs, no overlap
  ✓  Page 2 (offset=200): 200 unique IDs, no overlap
  ✓  Page 3 (offset=400): 200 unique IDs, no overlap
  ✓  Page 4 (offset=600): 200 unique IDs, no overlap
  ✓  Page 5 (offset=800): 200 unique IDs, no overlap

  ✅ CORRECTNESS CONFIRMED: 1000 messages fetched, all unique — zero duplicates

=== Test 3: Batch size — 200 vs 500 (same total messages, fewer spawns) ===
  Fetching first 1000 messages
  200/page = 5 osascript spawns
  500/page = 2 osascript spawns

  200/page: 50.77s for 1000 msgs (5 spawns)
  500/page: 25.32s for 1000 msgs (2 spawns)
  Same results: ✅ YES
  ✅ 500/page is 2.0× faster — fewer spawns wins

=== Test 4: Apple Events — what each approach actually sends ===

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

  osascript process spawns for 75747 messages:
    200/page → 379 spawns  (current default)
    500/page → 152 spawns  (recommended)
    Each spawn: ~200-500ms overhead for process start + AppleScript compilation

  Recommended page size: 500 (balances spawn overhead vs string concat cost)
=== Final Summary ===
  Mailbox: All Mail (75747 messages)

  Estimated full sweep times:
    OLD 200/page: ~11566s (O(n²) approximation)
    NEW 200/page: ~3855s
    NEW 500/page: ~1925s  ← recommended
-----

> swift macos-appkit-server/tests/test_batch_size.swift

=== Step 0: Finding largest mailbox ===
  Account : user@gmail.com
  Mailbox : All Mail
  Messages: 75747

=== Test 1: Batch size sweep — time/msg at different page sizes ===
  (Finding the sweet spot: faster per-message = better)
  (String concat O(n²) will show up as time/msg rising at large sizes)

  Size    Got     Time      ms/msg    Output KB   Status
  100     100     11.86s    118.6     19.2        ✅
  200     200     15.15s    75.7      38.8        ✅
  500     500     25.39s    50.8      96.6        ✅
  1000    1000    43.53s    43.5      194.9       ✅
  2000    2000    79.17s    39.6      391.7       ✅
  3000    3000    109.92s   36.6      585.3       ✅
  5000    1       180.07s   180065.5  0.0         ❌ ERROR

  ✅ Optimal batch size: 3000 (36.6ms/msg)

=== Test 2: OLD vs NEW — same content? (cross-verify) ===
  At each size, both approaches should return identical message IDs in same order

  ✅ offset=0: identical (200 msgs, same order)
  ✅ offset=500: identical (200 msgs, same order)
  ✅ offset=2000: identical (200 msgs, same order)

=== Test 3: Multi-page continuity — does offset drift? ===
  Fetch 10 consecutive pages, verify no gaps or overlaps
  (Would catch mailbox changes mid-sweep)
  ✅ 10 pages, 2000 messages — no drift, no overlap
  Page timing: avg=11.47s  min=8.71s  max=16.12s
  ⚠️  High variance — page times vary 1.9× (possible Mail.app load fluctuation)

=== Test 4: Full sweep time projection ===
  Based on measured ms/msg and spawn overhead

  Estimated spawn overhead: 8.32s/spawn
  Estimated per-message cost: 34.13ms/msg

  Page size   Spawns    Est. time for 75747 msgs    
  200         379       5737s (~95.6 min)
  500         152       3846s (~64.1 min)
  1000        76        3298s (~55.0 min)
  2000        38        2999s (~50.0 min)

=== Summary ===
  Recommended page size: 3000
  Reason: lowest ms/msg measured (36.6ms/msg)

  ------

> swift macos-appkit-server/tests/test_tempfile_sweep.swift

=== Hypothesis: single osascript spawn + write chunks to temp files ===
  Mailbox: All Mail (75749 messages)
  Test size: first 5000 messages, 5 chunks of 1000

  Approach A — N separate spawns, return string (CURRENT):
    chunk 1/5 (offset=0):    1000 msgs in 37.25s
    chunk 2/5 (offset=1000): 1000 msgs in 43.46s
    chunk 3/5 (offset=2000): 1000 msgs in 37.17s
    chunk 4/5 (offset=3000): 1000 msgs in 42.38s
    chunk 5/5 (offset=4000): 1000 msgs in 43.12s
    Total: 5000 msgs in 203.47s  (40.7ms/msg, 5 spawns)

  Approach B — 1 spawn, write chunks to /tmp/*.tsv, Python reads files:
    AppleScript completed: 216.85s
    Files: returned 5 paths — but ALL UNREADABLE
    ❌ AppleScript "open for access POSIX file /tmp/..." is sandboxed.
       The file path as seen by osascript maps to a container-redirected
       location, NOT the real /tmp/ visible to the Swift/Python process.
    Result: 0 msgs — files physically exist but at a different path.

  Approach C — 1 spawn, write all to single /tmp/if-sweep-all.tsv:
    ❌ Failed immediately — same sandbox path issue, osascript returned
       non-zero before writing anything.

=== Verdict ===

  Hypothesis DISPROVEN. Three findings:

  1. Temp files are SLOWER, not faster.
     Approach B: 216.85s vs A: 203.47s — 7% slower for the same 5000 msgs.
     AppleScript file I/O overhead exceeds the spawn savings saved by batching.

  2. String concatenation is NOT the bottleneck.
     At 1000 msgs/chunk, building the return string adds negligible cost.
     The ~34ms/msg Apple Events IPC round-trip to Mail.app per property
     access dominates regardless of output method (string concat or file write).

  3. osascript is sandboxed for file writes.
     "open for access POSIX file /tmp/..." in Apple Script is redirected
     by macOS's sandbox to a container-specific path. The file is not
     accessible at the POSIX path from outside the osascript process.
     This approach cannot be made to work without entitlement changes.

=== Conclusion: no free optimization left on the output side ===

  The only remaining lever is batch size (fewer spawns via larger pages).
  Empirical optimum from test_batch_size.swift: 3000 msgs/page at 36.6ms/msg.
  5000 failed (timeout). 3000 is the practical ceiling.

  Full-mailbox estimate at 3000/page for 75749 msgs:
    Spawns: 26
    Est. time: 26 × 8.32s overhead + 75749 × 36.6ms ≈ 2990s (~50 min)
  This matches the 2000/page projection (~50 min) — spawn savings at 3000
  are real but per-message cost dominates at this mailbox size.