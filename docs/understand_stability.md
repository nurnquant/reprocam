# Understanding stability

## Deployed: understand v1 on the Meta Model API, all frames (Sun Nov 1)

Understanding only (`UNDERSTAND_PROVIDER=meta`, Muse Spark 1.3, effort low, every distinct frame); test writing
and judging stay on Baseten. Same cached frames, transcript and check as below, 3 runs per bug.

| | bug1 | bug2 | bug3 | total |
|---|---|---|---|---|
| v1, Meta API, measure fixed before the runs | 3/3 | 0/3 | 3/3 | 6/9 |
| v1, Meta API, scored as the pipeline uses "not the app" | 3/3 | 0/3 | 3/3 | 6/9 |
| v1, Baseten (8 images), the same two measures | 3/3 | 0/3 | 2/3 · 3/3 | 5/9 · 6/9 |

**Decision: understanding moves to the Meta API.** The rule was "at least as good on every bug": it ties
Baseten on bug1 and bug2 and is better on bug3 on the first measure (no "not the app" answers in 9 runs), equal
on the second. bug2 still fails 3 of 3, the same way each time: "−" read right (no "Remove" misread, unlike
Baseten), but the start page loses its product id and "Add to basket" is skipped. Mean latency 7.5 s (Baseten
7.4 s). Cost not estimated: no Meta per-token price in `.env` yet. Live check after deploying: bug1 via the
owner link, REPRODUCED and confirmed on the known-good build, attempt 1, 65 s.

## Before: understand v1 on Baseten, 8-image limit (Sun Nov 1)

The live app serves Muse Spark Open from Baseten, which takes at most 8 images per request, so understanding
gets the first and last keyframes plus the 6 that changed most (`backend/understand.py::limit_frames`). Same
cached keyframes and transcript per bug as below, v1, 3 runs per bug, effort low, same check.

| | bug1 | bug2 | bug3 | total |
|---|---|---|---|---|
| v1, Baseten, measure fixed before the runs | 3/3 | 0/3 | 2/3 | 5/9 |
| v1, Baseten, scored as the pipeline uses "not the app" | 3/3 | 0/3 | 3/3 | 6/9 |

| | distinct frames | sent | dropped by the cap |
|---|---|---|---|
| bug1 | 13 | 8 | 4, 7, 8, 11, 12 |
| bug2 | 8 | 8 | none |
| bug3 | 11 | 8 | 2, 9, 17 |

What failed:
- **bug2, 3 of 3** with all its frames sent, so not the cap: twice "Remove" read where the tester pressed "−"
  (the bug-bash misread, which didn't occur in the 6 Fireworks v1/v2 runs below), once "−" right but the product
  missing; all 3 skip "Add to basket", and 2 of 3 drop the product id from the start page.
- **bug3, 1 of 3: "not the app"** with 8 grounded steps. The pipeline ignores the flag when the steps use ≥ 2
  element-map ids, so this run would have gone on (second row).
- bug1 lost 5 of 13 distinct frames to the cap and was still right 3 of 3.

Three runs per cell is too few to say Baseten is worse than Fireworks (5/9 vs 6/9 on the same measure);
bug2 is the weak spot on both. Cost: 9 calls, $0.16 (at the Baseten rates in `.env`, which come from a
third-party tracker and still need confirming on Baseten). Rows: `data/understand_stability.jsonl`
(`provider: baseten`).

## Earlier: understand v1, v2, v3 on Fireworks, all distinct frames (Sat Oct 31)

Same cached keyframes and transcript per bug, understanding run 3× per prompt version
(Muse Spark Open on Fireworks, effort low). "Correct" = the key actions each demo bug needs
(`scripts/understand_stability.py::check`), plus the recording recognised as the app.

| | bug1 | bug2 | bug3 | total |
|---|---|---|---|---|
| v1 (current prompt) | 2/3 | 1/3 | 3/3 | 6/9 |
| v2 (+ "trust the following frames over the narration") | 3/3 | 1/3 | 2/3 | 6/9 |
| v3 (v1, but "keep query parameters that select content; drop only flags like fixed") | 1/3 | 2/3 | 1/3 | 4/9 |

The same runs scored the way the pipeline now uses the "not the app" flag (ignored when the steps
use ≥ 2 element-map ids; see below):

| | bug1 | bug2 | bug3 | total |
|---|---|---|---|---|
| v1 | 2/3 | 1/3 | 3/3 | 6/9 |
| v2 | 3/3 | 1/3 | 3/3 | 7/9 |
| v3 | 3/3 | 3/3 | 3/3 | 9/9 |

**Decision: default stays v1.** The rule was "only if at least as good on every bug" on the measure fixed
before the runs (first table, which counts a wrong "not the app" as a miss): v2 is worse on bug3, v3 on bug1
and bug3. On the second table v3 would win 9/9, but switching measures after seeing the results isn't
done here. Three runs per cell is too few to call any version better.

v3 does what it was for: all 3 bug2 runs keep `product.html?id=pebble-light` (v1 and v2 dropped the id in
4 of 6 runs), and no start page carries `fixed=`. But it says "not the app" in 5 of 9 runs (v1: 1, v2: 1),
each time with 3–10 grounded steps, so it leans on the guard below. A v4 that keeps v3's sentence and
fixes the flag (or asks about the app in a separate, cheap call) is the next thing to try.

What failed:
- **bug2, 4 of 6 misses (both versions): the start page lost its product id** (`product.html` instead of
  `product.html?id=pebble-light`). The prompt itself says to give the start path "without query parameters".
  The "Remove instead of −" misread from the bug bash did not recur (all 6 bug2 runs click "−").
- **"Not the app", 2 of 18 runs** (bug1 v1, bug3 v2), each time with 7–9 steps grounded in the element map.
  The early stop now also requires the steps to agree (fewer than 2 element-map ids), which stops none
  of these 18 runs but still stops real non-app uploads (1 step, no ids).

Cost: 27 calls, $0.59 (v1 + v2 $0.39, v3 $0.20). Rows: `data/understand_stability.jsonl`.
