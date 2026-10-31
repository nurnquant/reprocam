# ReproCam — Build Plan v2.1

Read `CLAUDE.md` first (rules, endpoints, model ids). This file is the work order.
Work milestone by milestone. After each one: run its acceptance check, commit
(`git commit -m "M<n>: ..."`), tick the boxes, and stop to report to Nur.

**Deadline:** Wed Nov 4, 9:00 PM ET. **Code freeze:** Wed 12:00 PM ET (afternoon = video + submit).

### What changed from v1 (old plan: `docs/BUILD_PLAN_v1.md`)
1. **Reasoning effort is a per-stage setting, default `low`.** Fireworks' own tests showed Muse Spark
   Open scored best at low effort (88.5) and worst at high (81.8). We measure it for our task (M4b).
2. **Frames, not video, for Muse Spark Open.** Fireworks serves it as text + image in. Video goes
   to SAM 3.1 only; Muse Spark always gets keyframes as images.
3. **Deterministic grading first.** The buggy/fixed toggle is our ground-truth oracle. LLM judging
   only where a rule can't decide.
4. **New stretch milestone M9: fine-tune Muse Glimmer 30B as the verification judge** (free LoRA SFT
   on Fireworks until Nov 30), trained on data our own system generates and labels. Gated.
5. **Judge training data is logged from day one** so M9 costs little extra.
6. **No non-Meta models in the product** (e.g. no DeepSeek router), even if cheaper.

### v2.1 review fixes
- M9 label table now covers all 9 buggy×fixed outcomes; ambiguous cells are dropped, not guessed.
- Bug registry entries are tagged `demo` or `training`; training bugs only switch on with `?train=1`.
- M4b repeats each cell 3× (27 runs); claims are worded "on our 3 bugs", never "best".
- `preflight.py` runs **first** in M2; if a provider ignores `reasoning_effort`, M4b runs only where it works.
- Demo script numbers come from a real recorded run, not from this plan.
- Eval rows are selected by rule, never by hand; Muse Spark Open's eval score is flagged as tuned-on.
- Fireworks facts (free LoRA cutoff, Glimmer id) come from Fireworks' Oct 30 workshop deck — confirm in
  Fireworks docs/console before M9 depends on them.
- **Rule judge fix:** a Playwright `expect()` timeout is an *assertion failure*, not a test error —
  otherwise `zip_hang` (a hang bug) can never be judged REPRODUCED.
- Always pass the build flag explicitly (`?fixed=0` or `?fixed=1`) — it persists in localStorage.

---

## 0. The product in one paragraph

A tester uploads a screen recording (or phone video) of a bug while narrating it.
ReproCam transcribes the narration, reads the video, works out the user's steps, finds the
broken UI element, writes a Playwright test, **runs it**, and only declares the bug reproduced
when the test fails *for the reason the tester described*. Otherwise it revises and retries
(max 3). Output: failing test + highlighted screenshot + bug ticket. Against the fixed build,
the same test passes. **The verify loop is the heart of the project.**

---

## 1. Architecture

```
video ──ffmpeg──► audio.wav ──► Muse Voice Transcribe ─────────► transcript
      └─ffmpeg──► keyframes/*.jpg (≤24) ───┐
store DOM map (Playwright) ────────────────┼─► Muse Spark [effort=low] ─► steps.json + bug_claim
video + bug_claim.element ─────────────────┴─► SAM 3.1 ─► boxes ─► evidence.png
steps + DOM map + feedback ──► Muse Spark Open [effort=low] ──► test_repro.py
test_repro.py ──► pytest subprocess (timeout) ──► raw result
raw result ──► rule judge ──(undecided)──► model judge (Muse Spark Open → or tuned Glimmer, M9)
   └─ NOT_REPRODUCED / TEST_ERROR → feedback → testgen (≤3 attempts)
REPRODUCED ──► ticket.md + evidence.png + test ──► re-run on ?fixed=1 → must PASS
every judge decision ──► data/judge_log.jsonl (training data for M9)
```

### Folder layout (target)
```
store/                 practice shop (static HTML/CSS/JS)
backend/
  llm.py               provider switch (exists) + chat() helper: logs model, provider, effort,
                       tokens, latency, cost estimate; backoff on 429/5xx only, never on 400
  prompts/*.md         all prompts live here
  media.py  transcribe.py  dom_snapshot.py  understand.py  segment.py
  testgen.py  runner.py  judge.py  agent.py  ticket.py  budget.py  api.py
web/                   ReproCam UI
scripts/               check_env.py, preflight.py, effort_sweep.py, gen_judge_data.py, train_glimmer.py
samples/               demo videos + cached runs
data/                  judge_log.jsonl, judge_sft_train.jsonl, judge_sft_eval.jsonl
runs/<id>/             per-run artifacts (gitignored)
tests/                 tests/store/ (ground truth), tests/unit/
docs/                  charts, architecture image, v1 plan
```

### Data contracts (stable — UI depends on them)

`steps.json`
```json
{
  "app_url": "http://localhost:5173",
  "steps": [{"n": 1, "action": "goto|click|fill|select|press|wait",
             "target": "human description", "selector_hint": "data-testid from DOM map or null",
             "value": null, "frame_ref": 3}],
  "bug_claim": {"summary": "...", "expected": "...", "actual": "...",
                "element": "order total", "frame_ref": 9}
}
```

Run event (SSE + `runs/<id>/events.jsonl`)
```json
{"t": 1.82, "stage": "transcribe|frames|understand|segment|testgen|run|judge|ticket|fixcheck",
 "status": "start|ok|fail|retry", "model": "muse-spark-open", "provider": "fireworks",
 "effort": "low", "attempt": 1, "detail": "short human text", "artifact": null}
```

Judge verdict
```json
{"verdict": "REPRODUCED|NOT_REPRODUCED|TEST_ERROR", "decided_by": "rule|model",
 "reason": "...", "feedback_for_generator": "..."}
```

Judge log row (`data/judge_log.jsonl`, one per judged run)
```json
{"bug_id": "neg_total", "bug_claim": {...}, "test_code": "...", "pytest_output": "...(trimmed 3k chars)",
 "verdict": "...", "decided_by": "...",
 "oracle": {"buggy": "pass|assert_fail|error", "fixed": "pass|assert_fail|error"}}
```

### Effort settings (`.env`)
```
EFFORT_UNDERSTAND=low
EFFORT_TESTGEN=low
EFFORT_JUDGE=low
```
Muse Spark Open does **not** accept `none`. `scripts/preflight.py` checks which effort levels and
input types (text, image) each configured provider accepts before any sweep spends money.

---

## 2. Schedule at a glance

| When | Milestones | Gate |
|---|---|---|
| Sat Oct 31 | M1 store · M2 media + transcribe | — |
| Sun Nov 1 | M3 understanding · M4 verify loop (start) | — |
| Mon Nov 2 | M4 finish · M4b effort sweep · M5 SAM | **M4 accepted by 11:59 PM → M9 allowed** |
| Tue Nov 3 | M6 API + UI · M7 deploy · M9 Glimmer (stretch, parallel) | **M9 hard stop 6:00 PM** |
| Wed Nov 4 | M8 polish, video, X post, submit | **Code freeze 12:00 PM** |

---

## 3. Milestones

### M1 — Practice store with planted bugs (Sat)
Original fictional brand **"Lumen & Loom"** (lamps and textiles). Must not resemble any real retailer.
Pages: list → detail → cart → checkout → confirmation. Plain HTML/JS on port 5173.
Stable `data-testid` on every interactive/asserted element.

Demo bugs (each switched off by `?fixed=1`, persisted in localStorage):
1. `neg_total` — promo `GLOW20` can be applied repeatedly; total goes below $0.
2. `qty_stepper` — "−" at quantity 1 gives 0 but still charges, or "+" adds 2.
3. `zip_hang` — ZIPs starting with `0` leave "Place order" spinning forever.

Bugs live in the registry `store/bugs.js` (done). When M9 starts, change entries to
`{id: {on: true, set: "demo"|"training"}}`; `training` bugs are active only with `?train=1`, so the
public demo store shows exactly the 3 demo bugs. Every test/run URL passes `?fixed=0|1` explicitly.

- [x] Store runs; 3 bugs reproducible by hand; `?fixed=1` removes each
- [x] `tests/store/`: hand-written test per bug — fails on buggy, passes on fixed (ground truth)

### M2 — Media + transcription (Sat)
- [x] **First:** `scripts/preflight.py` — for each provider: is image input accepted? which
      `reasoning_effort` values are accepted **and actually change behaviour** (compare reasoning
      tokens / output length low vs high on one prompt)? Print a table; record it in `docs/preflight.md`.
- [x] `media.py`: ffmpeg → `audio.wav` (mono 16-bit PCM; sample rate per cookbook) and keyframes
      (scene-change, fallback 1 fps, cap 24, ≤1280 px wide, JPEG)
- [x] `transcribe.py`: POST `https://api.meta.ai/v1/asr/transcribe`, `Authorization` header,
      model `muse-voice-transcribe-1.0`; port from cookbook `06_muse_voice/01_voice_api_fundamentals/utils.py`.
      `keywords` = product names + "promo", "checkout", "ZIP".
- [ ] Nur records 3 narrated sample videos (QuickTime screen + mic) → `samples/` — bug1 done; bug2, bug3 pending
- [x] Acceptance: `python -m backend.media samples/bug1.mov` prints transcript + frame count

### M3 — Understanding: video → steps (Sun)
- [x] `dom_snapshot.py`: crawl store, compact map `[{page, testid, role, name, text}]` (≤4k tokens).
      The model must choose selectors from this map, never invent them.
- [x] `understand.py`: keyframes (base64 images) + transcript + DOM map → structured output
      (JSON schema) → `steps.json`. Cookbook refs: `01_api_fundamentals/04_structured_output`, `07_vision_input`.
- [ ] Acceptance: all 3 samples produce steps matching the real flow (compare to `tests/store/`) — bug1 matches (2 runs); bug2, bug3 wait for recordings

### M4 — Test generation + runner + verify loop (Sun → Mon) ← core
- [x] `testgen.py`: steps + DOM map + bug_claim (+ judge feedback) → `test_repro.py`
      (pytest + Playwright sync API, `expect()`, no sleeps > 2 s, base URL from env, `?fixed=0|1` always explicit).
      Hang/never-finishes bugs must be asserted with `expect(...).to_be_visible(timeout=8000)`, never by waiting on an action
- [x] `runner.py`: subprocess `pytest -x -q`, 60 s timeout, capture output, failure message,
      final screenshot. Generated code only ever runs inside this subprocess.
- [x] `judge.py`, rule layer first:
      - passed → `NOT_REPRODUCED`
      - error that isn't an assertion (selector not found, action timeout like `page.click`,
        syntax/import error) → `TEST_ERROR`
      - assertion failure — **including `expect()` timeouts** (Playwright raises `AssertionError`)
        and plain `assert` → model judge: does the failure match `bug_claim`? (Muse Spark Open, effort low)
- [x] `agent.py`: ≤3 attempts, judge feedback into testgen, events emitted, every verdict logged to
      `data/judge_log.jsonl` **including the oracle** (re-run the same test on `?fixed=1`).
- [x] Fix check: final test on `?fixed=1` must PASS.
- [x] `ticket.py`: markdown bug report (steps, claim, failing test + failure line, fixed-build result,
      evidence.png if present) → `runs/<id>/ticket.md` at the end of every REPRODUCED run.
- [ ] Acceptance: ≥2 of 3 samples reach REPRODUCED and pass on fixed, via
      `python -m backend.agent samples/bug1.mov` — bug1 REPRODUCED on attempt 1 + passes fixed (2/2 runs); bug2, bug3 pending
- [ ] Honest retry moment: at least one sample naturally shows judge catching a wrong first test.
      Never fake it.

### M4b — Effort sweep (Mon, ~1 h)
- [ ] `scripts/effort_sweep.py`: 3 samples × efforts {low, medium, high} × **3 repeats = 27 runs**,
      from cached `steps.json` (skip transcription/understanding to save money). Only for providers where
      preflight showed effort actually changes behaviour.
      Deterministic score: REPRODUCED **and** passes on fixed. Record attempts, tokens, cost, seconds.
- [ ] Cache to `data/effort_sweep.jsonl` (resume on rerun). Chart → `docs/effort_sweep.png`.
- [ ] Chart shows mean and spread per effort. Set `.env` defaults from the result. Read 10 outputs by hand.
- [ ] Wording everywhere: "on our 3 bugs, <effort> reproduced N/9 at $X" — no general "best effort" claims.

### M5 — SAM 3.1 evidence (Mon)
- [x] `segment.py`: upload video (`purpose=user_data`), concept = `bug_claim.element`, parse with
      `meta_sam_parser` only (port from cookbook `07_sam/01_api_basics/python`).
- [x] Draw box/mask on frame `bug_claim.frame_ref` → `evidence.png`.
      Spike result (bug1): SAM finds no box for "order total" / "price total" / "discount", but "price"
      boxes every price tightly; Muse Spark Open picks the claimed one from a numbered overlay.
      Fallback (no SAM boxes): Muse Spark box in 0-1000 coords, within ~6 px of SAM's on bug1.
- [x] Risk: UI text may segment poorly. Tested Sat (see spike result above). Fallback: Muse Spark returns a box on
      the frame; UI labels which model produced it. Never block M4 on this.

### M6 — API + UI (Tue)
- [x] `api.py`: `POST /runs` (multipart) → id; `GET /runs/{id}/events` (SSE); `GET /runs/{id}`;
      `GET /samples`; `POST /samples/{id}/replay` (replays cached events with original timing, $0).
- [x] `budget.py`: `MAX_RUNS_PER_DAY`, per-IP limit, 25 MB / 90 s upload cap. (Meta's Spend Limit is only an alert.)
- [x] `web/`: one page. Left: video. Right: live stage timeline with badges "model · provider · effort".
      Bottom: test code red/green, evidence image, ticket. Buttons: Upload · Try a sample bug ·
      Run against fixed build. Mobile upload: `<input type="file" accept="video/*" capture>`.
      Distinctive design, not a template look.
      Done Sat: bug1 sample replays end to end in the browser (docs/screenshots/m6_replay.png).
      Live upload path covered by API tests for rejections only; a real browser upload run is still to do.

### M7 — Deploy (Tue)
- [ ] Store → Vercel or GitHub Pages. Backend → Modal (Chromium + ffmpeg in image).
- [ ] Public URL works on a phone; "Try a sample bug" works with zero API spend.
- [ ] README: what/why, architecture image, model map (section 4), effort chart, M9 results if done,
      run instructions, "100% built during the hackathon", demo link.

### M8 — Polish + video (Wed AM → submit)
- [ ] Bug bash: 3 samples + 1 fresh recording. Freeze at noon.
- [ ] Record video (section 6). Post on X. Submit with repo, video, X link.

### M9 — STRETCH: Muse Glimmer as a trained verification judge (Tue, gated)
**Gate:** start only if M4 is accepted by Mon 11:59 PM. **Hard stop:** Tue 6:00 PM — if not done,
ship without it and list it in the roadmap. Runs in parallel with M6/M7.

Why: deciding "did this test fail for the claimed reason?" is the hardest call in the product.
In development we have a perfect oracle (buggy vs fixed build). In real use there's no fixed build —
so we distill the oracle into a small specialized Meta open-weight model.

Labels from the oracle (deterministic, no LLM):
All 9 outcome pairs (`assert_fail` includes `expect()` timeouts; `error` = non-assertion error):

| buggy run | fixed run | label | why |
|---|---|---|---|
| assert_fail | pass | REPRODUCED | fails only when the bug is present |
| assert_fail | assert_fail | NOT_REPRODUCED | fails for a reason unrelated to the bug |
| assert_fail | error | **drop row** | ambiguous: test breaks on the fixed build |
| pass | pass | NOT_REPRODUCED | never exercises the bug |
| pass | assert_fail | NOT_REPRODUCED | asserts the opposite of the claim |
| pass | error | NOT_REPRODUCED | doesn't reproduce on buggy |
| error | pass | TEST_ERROR | broken on buggy |
| error | assert_fail | TEST_ERROR | broken on buggy |
| error | error | TEST_ERROR | broken test |

`gen_judge_data.py` implements exactly this table as a lookup (with a unit test) and logs dropped rows.

Steps:
- [ ] Add 5 **training-only** bugs to the store registry (e.g. wrong tax rounding, sale badge on
      full-price item, cart count off by one after removal, sort-by-price ignores sale price,
      wishlist heart doesn't persist). Demo bugs 1–3 are **never** in training data (held out → honest eval).
- [ ] `scripts/gen_judge_data.py`: for each training bug, have Muse Spark Open write test variants on
      purpose: correct repro · wrong assertion · missing step · broken selector · asserts unrelated
      thing · passes trivially. Run each on buggy + fixed, label via table. Target ~600 rows, balanced.
      Resume-safe, cached, cost-capped.
- [ ] Format: chat JSONL `{"messages":[system, user, assistant]}`; assistant = compact JSON verdict.
      System prompt gives the schema, not the rules. No near-duplicates across train/eval.
- [ ] Eval set, selected by rule only (never hand-picked): **every** logged run on demo bugs 1–3
      (M4/M4b) with a non-dropped oracle label, de-duplicated by test code hash, + 40 held-out generated
      rows (random, fixed seed). Note in README: Muse Spark Open's judge prompt was tuned on demo-bug runs,
      so its score there is optimistic; Glimmer never saw them.
- [ ] Before training: confirm in Fireworks docs/console the Glimmer base id, that LoRA SFT is still
      free for jobs started before Dec 1, and current deployment pricing. If any differs, stop and report.
- [ ] `scripts/train_glimmer.py`: Fireworks serverless training, `muse-glimmer-30b` + LoRA rank 8,
      SFT (free for jobs started before Dec 1). Follow `github.com/fw-ai/cookbook` SFT router notebook.
- [ ] Eval: exact-match accuracy of base Glimmer vs tuned Glimmer vs Muse Spark Open judge, same
      decoding. Chart → `docs/judge_eval.png`. Read 10 predictions by hand.
- [ ] Serving: on-demand deployment is billed (not covered by the free promo). Deploy only for the
      eval and video recording; replay cached runs on the public site; delete deployment after
      (`--ignore-checks` if it served in the last hour). Add `JUDGE_PROVIDER=glimmer` switch.
- [ ] Acceptance: tuned Glimmer beats base Glimmer on held-out demo bugs; numbers in README, honest
      even if it doesn't beat Muse Spark Open.

---

## 4. Model usage map (README + video)

| Stage | Model | Provider | Notes |
|---|---|---|---|
| Narration → text | Muse Voice Transcribe | Meta Model API | keywords biasing |
| Frames → steps & bug claim | Muse Spark (vision) | Meta API or Muse Spark Open on Fireworks/Baseten | images only, effort per M4b |
| Find broken element | SAM 3.1 | Meta Model API | video tracking |
| Write test | Muse Spark Open | Fireworks / Baseten | effort per M4b |
| Judge | Muse Spark Open → **tuned Muse Glimmer 30B** (M9) | Fireworks | rules first |

Provider ids: Fireworks `accounts/fireworks/models/muse-spark-open` · Baseten `meta-models/muse-spark-open` (guide's `-1026` id 404s)
· Glimmer training base `accounts/fireworks/models/muse-glimmer-30b` (training only, not serverless) —
source: Fireworks Oct 30 workshop deck; verify before M9.

## 5. Prize map

| Prize | What earns it |
|---|---|
| Indie track (Impact, Tooling, Depth, Demo) | M4 loop + M6 UI + M8 video |
| Best Agentic Use-Case ($5K) | self-correcting verify loop, retries, real actions |
| Best Open-Weight Build ($10K) | Muse Spark Open on Fireworks/Baseten everywhere + tuned Glimmer judge (M9) |
| Most Viral ($20K) | X post of the "phone video → red test" moment, through Nov 8 |
| Community Vote ($10K) | Discord + X push when voting opens Nov 9 |

## 6. Working rules for Claude Code
- Small commits, ≥1 per milestone. Never commit `.env`, keys, `runs/`. Commit `data/*.jsonl` only if < 5 MB.
- Read the matching cookbook recipe before each integration (clone outside the repo):
  Meta `github.com/meta-models/meta-model-cookbook` · Fireworks `github.com/fw-ai/cookbook`.
- Measure before tuning: deterministic graders, held-out data, read outputs by hand. Loss ≠ accuracy.
- Every paid sweep: cached to JSONL, resumable, prints projected cost before running.
- Blocked > 30 min → stop and report options.

## 7. Demo video script (3:00)
- 0:00 "Everything shown was built during this hackathon."
- 0:05 Phone films laptop: promo applied twice, "the total just went negative."
- 0:15 Upload → timeline lights up with "model · provider · effort" badges.
- 0:50 First test passes → judge: NOT_REPRODUCED, "never applied promo twice" → retry.
- 1:15 Second test fails red (show the **real** failure line from the recorded run) → REPRODUCED. SAM evidence box.
- 1:35 "Run against fixed build" → green. "Every bug report becomes a regression test."
- 1:50 Second bug, sped up.
- 2:10 Under the hood: effort chart ("on our 3 bugs, low effort reproduced N/9 at the lowest cost") and, if M9 done,
  "we trained Muse Glimmer into our judge: X% → Y% on bugs it never saw."
- 2:40 Architecture: Voice Transcribe · Muse Spark · SAM 3.1 · Muse Spark Open · Glimmer.
- 2:50 Who it's for + next: CI integration, native mobile.

## 8. Next prompt to give Claude Code (M1 is done)

> Read the v2.1 changes at the top of BUILD_PLAN.md. M1 is committed. Start M2, beginning with
> `scripts/preflight.py` and `docs/preflight.md`, then media + transcription. Stop after preflight
> and show me the table before continuing.

## (Original first prompt)

> Read CLAUDE.md and BUILD_PLAN.md (v2). Start M1: build the Lumen & Loom practice store in
> `store/` with the 3 demo bugs behind a bug registry and the `?fixed=1` toggle, plus hand-written
> Playwright tests in `tests/store/` that fail on buggy and pass on fixed. Run them to prove it,
> commit, tick the M1 boxes, and report back.
