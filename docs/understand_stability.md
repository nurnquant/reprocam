# Understanding stability: understand v1 vs v2 (Sat Oct 31)

Same cached keyframes and transcript per bug, understanding run 3× per prompt version
(Muse Spark Open on Fireworks, effort low). "Correct" = the key actions each demo bug needs
(`scripts/understand_stability.py::check`), plus the recording recognised as the app.

| | bug1 | bug2 | bug3 | total |
|---|---|---|---|---|
| v1 (current prompt) | 2/3 | 1/3 | 3/3 | 6/9 |
| v2 (+ "trust the following frames over the narration") | 3/3 | 1/3 | 2/3 | 6/9 |

**Decision: default stays v1** (rule: v2 only if at least as good on all 3; it is worse on bug3).
Three runs per cell is too few to call either version better.

What failed:
- **bug2, 4 of 6 misses (both versions): the start page lost its product id** (`product.html` instead of
  `product.html?id=pebble-light`). The prompt itself says to give the start path "without query parameters".
  The "Remove instead of −" misread from the bug bash did not recur (all 6 bug2 runs click "−").
- **"Not the app", 2 of 18 runs** (bug1 v1, bug3 v2), each time with 7–9 steps grounded in the element map.
  The early stop now also requires the steps to agree (fewer than 2 element-map ids), which stops none
  of these 18 runs but still stops real non-app uploads (1 step, no ids).

Cost: 18 calls, $0.40. Rows: `data/understand_stability.jsonl`.
