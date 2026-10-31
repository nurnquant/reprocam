# ReproCam — Build Plan for Claude Code

Read `CLAUDE.md` first (rules, endpoints, model ids). This file is the work order.
Work milestone by milestone. After each milestone: run its acceptance check, commit
(`git commit -m "M<n>: ..."`), tick the boxes here, and stop to report to Nur.

**Deadline:** Wed Nov 4, 9:00 PM ET. Code freeze: Wed 12:00 PM ET (rest of the day = video + submission).

---

## 0. The product in one paragraph

A tester uploads a screen recording (or phone video) of a bug while narrating it.
ReproCam transcribes the narration, reads the video, works out the user's steps, finds the
broken UI element, writes a Playwright test, **runs it**, and only declares the bug
reproduced when the test fails *for the reason the tester described*. If the test passes or
errors, the agent revises and retries (max 3). Output: failing test + highlighted
screenshot + bug ticket. Against the fixed build, the same test passes.

The verify loop is the heart of the project. Everything else serves it.

---

## 1. Architecture

```
video.mp4 ──ffmpeg──► audio.wav ──► Muse Voice Transcribe ──► transcript
          └─ffmpeg──► keyframes/*.jpg ─┐
store DOM snapshot (Playwright) ───────┼─► Muse Spark (vision) ──► steps.json + bug_claim
                                       │
video.mp4 + bug_claim.element ─────────┴─► SAM 3.1 ──► boxes per frame ──► evidence.png
steps.json + DOM snapshot ──► Muse Spark ──► test_repro.py
test_repro.py ──► pytest (sandboxed subprocess, timeout) ──► result
result + bug_claim ──► Muse Spark "judge" ──► REPRODUCED | NOT_REPRODUCED | TEST_ERROR
   └─ not reproduced / error → feedback to generator → retry (≤3)
REPRODUCED ──► ticket.md + evidence.png + test file ──► run against ?fixed=1 → expect PASS
```

### Folder layout (target)
```
store/                 practice shop (static HTML/CSS/JS, no build step)
backend/
  llm.py               provider switch (exists)
  media.py             ffmpeg: audio extract (mono 16-bit WAV), keyframes (≤24)
  transcribe.py        Muse Voice Transcribe one-shot endpoint
  dom_snapshot.py      Playwright: visit store pages, emit compact element map
  understand.py        Muse Spark: frames + transcript + DOM map -> steps + bug_claim
  segment.py           SAM 3.1 video segmentation -> boxes; evidence.png
  testgen.py           Muse Spark: write pytest-playwright test
  runner.py            run test in subprocess w/ timeout, capture output + screenshot
  judge.py             Muse Spark: did it fail for the claimed reason?
  agent.py             orchestrates the loop, emits events
  ticket.py            bug report markdown
  budget.py            run cap + cache
  api.py               FastAPI app
web/                   ReproCam UI (single page)
samples/               3 demo videos + cached runs
runs/<id>/             per-run artifacts (gitignored except samples)
tests/                 our own unit tests for parsers/judge logic
```

### Data contracts (keep these stable; UI depends on them)

`steps.json`
```json
{
  "app_url": "http://localhost:5173",
  "steps": [
    {"n": 1, "action": "goto|click|fill|select|press|wait",
     "target": "human description", "selector_hint": "from DOM map or null",
     "value": "text or null", "frame_ref": 3}
  ],
  "bug_claim": {
    "summary": "Order total becomes negative after applying promo twice",
    "expected": "Total stays >= 0 and promo applies once",
    "actual": "Total shows -$12.40",
    "element": "order total",
    "frame_ref": 9
  }
}
```

Run events (Server-Sent Events, also saved to `runs/<id>/events.jsonl`)
```json
{"t": 1.82, "stage": "transcribe|frames|understand|segment|testgen|run|judge|ticket|fixcheck",
 "status": "start|ok|fail|retry", "model": "muse-spark-1.3", "provider": "baseten",
 "attempt": 1, "detail": "short human text", "artifact": "relative/path or null"}
```

Judge verdict
```json
{"verdict": "REPRODUCED|NOT_REPRODUCED|TEST_ERROR", "reason": "...", "feedback_for_generator": "..."}
```

---

## 2. Milestones

### M1 — Practice store with planted bugs  (Sat)
Original fictional brand: **"Lumen & Loom"** (lamps and textiles). Must not resemble any real retailer.
Pages: product list → product detail → cart → checkout → confirmation. Plain HTML/JS, served
by `python -m http.server` or a tiny script on port 5173. Stable `data-testid` on key elements.

Planted bugs, each toggled off by `?fixed=1` (persist the flag in localStorage):
1. **Negative total:** promo `GLOW20` can be applied repeatedly; total goes below $0.
2. **Quantity stepper:** "−" on quantity 1 sets 0 and the line still charges.
3. **Checkout hang:** ZIP codes starting with `0` leave the "Place order" spinner forever.

- [x] Store runs locally; all 3 bugs reproducible by hand; `?fixed=1` removes each
- [x] Hand-written Playwright test per bug that fails on buggy, passes on fixed (`tests/store/`)
      — these are our ground truth for judging ReproCam's output

### M2 — Media + transcription  (Sat)
- [ ] `media.py`: ffmpeg → `audio.wav` (mono, 16-bit PCM; check cookbook for sample rate) and
      keyframes (scene-change detection, fallback 1 fps, cap 24, max 1280px wide)
- [ ] `transcribe.py`: POST `https://api.meta.ai/v1/asr/transcribe`, `Authorization` header,
      model `muse-voice-transcribe-1.0`. Port the request shape from cookbook
      `06_muse_voice/01_voice_api_fundamentals/utils.py::transcribe_recording`.
      Pass `keywords` = product names + "promo", "checkout", "ZIP".
- [ ] Record 3 sample videos of the bugs with narration (Nur records; QuickTime screen + mic)
- [ ] Acceptance: `python -m backend.media samples/bug1.mov` and transcript printed

### M3 — Understanding: video → steps  (Sun)
- [ ] `dom_snapshot.py`: crawl store pages, emit compact map
      `[{page, testid, role, name, text}]` (≤ 4k tokens). This grounds selectors — the model
      must pick selectors from this map, never invent them.
- [ ] `understand.py`: Muse Spark with keyframes (base64 images) + transcript + DOM map,
      **structured output** (JSON schema) → `steps.json`. See cookbook
      `01_api_fundamentals/04_structured_output` and `07_vision_input`.
- [ ] Acceptance: for all 3 samples, steps match the real flow (compare to M1 tests)

### M4 — Test generation + runner + verify loop  (Sun → Mon)  ← the core
- [ ] `testgen.py`: steps + DOM map + bug_claim → `test_repro.py` (pytest + playwright sync API).
      Assertion must encode `expected`. Base URL from env. No sleeps > 2s; use expect().
- [ ] `runner.py`: subprocess `pytest -x -q`, 60s timeout, capture stdout, failure message,
      final screenshot; never run generated code outside this subprocess.
- [ ] `judge.py`: classify result vs bug_claim (rules first: pass → NOT_REPRODUCED;
      selector/timeout error unrelated to claim → TEST_ERROR; assertion failure → ask
      Muse Spark whether it matches the claim).
- [ ] `agent.py`: loop ≤3 attempts, feeding judge feedback into testgen. Emit events.
- [ ] Fix check: run the final test with `?fixed=1` → must PASS.
- [ ] Acceptance: ≥2 of 3 samples reach REPRODUCED and pass on fixed build, end-to-end, one command:
      `python -m backend.agent samples/bug1.mov`
- [ ] Demo-worthy moment: make sure at least one sample shows a retry (first test passes
      wrongly → judge catches it → second attempt reproduces). Don't fake it; tune prompts or
      pick the sample where it naturally happens, and log it honestly.

### M5 — SAM 3.1 evidence  (Mon)
- [ ] `segment.py`: upload video (`purpose=user_data`), concept = `bug_claim.element`,
      parse with `meta_sam_parser` only (port from cookbook `07_sam/01_api_basics/python`).
- [ ] Draw box/mask on the frame at `bug_claim.frame_ref` → `evidence.png`.
- [ ] **Risk:** SAM is trained on natural images; UI text elements may segment poorly. Try it
      first thing Monday. Fallback: ask Muse Spark for a bounding box on the frame (vision
      grounding) and label it honestly in the UI. Do not block M4 on this.

### M6 — API + UI  (Mon → Tue)
- [ ] `api.py`: `POST /runs` (multipart video) → id; `GET /runs/{id}/events` (SSE);
      `GET /runs/{id}` (final artifacts); `GET /samples`; `POST /samples/{id}/replay`
      (replays cached events with original timing — zero API cost).
- [ ] `budget.py`: `MAX_RUNS_PER_DAY` from env, per-IP limit, 25 MB / 90 s upload cap.
- [ ] `web/`: one page. Left: video player. Right: live timeline of stages, each showing
      model + provider badge (e.g. "Muse Spark Open · Baseten"). Bottom: test code with red/green
      result, evidence image, ticket. Buttons: Upload video · Try a sample bug · Run against fixed build.
      Mobile: upload uses `<input type="file" accept="video/*" capture>`.
- [ ] Use the frontend-design approach: distinctive, not template-looking.

### M7 — Deploy  (Tue)
- [ ] Store → static host (Vercel or GitHub Pages).
- [ ] Backend → Modal (Playwright + ffmpeg in the image) or any host that runs Chromium.
- [ ] Public URL works from a phone; "Try a sample bug" works with no keys spent.
- [ ] README: what it is, architecture diagram, Meta models used and where, how to run,
      "100% built during the hackathon", demo link.

### M8 — Polish + video  (Wed AM, freeze at noon)
- [ ] Bug bash on the 3 samples + 1 fresh recording
- [ ] Record the 3-min video (script below). Post on X. Submit.

---

## 3. Model usage map (show this in README + video)

| Stage | Model | Provider |
|---|---|---|
| Narration → text | Muse Voice Transcribe | Meta Model API |
| Frames → steps & bug claim | Muse Spark (vision) | Meta API, or Muse Spark Open via Baseten if it accepts images |
| Find broken element in video | SAM 3.1 | Meta Model API |
| Write test, judge result | Muse Spark Open | Baseten (default) / Fireworks |

`LLM_PROVIDER` switches the text stages. Log provider on every event so the open-weight
bonus is provable.

---

## 4. Working rules for Claude Code
- Small commits, one per milestone minimum. Never commit `.env`, keys, or `runs/` (except samples).
- Before writing an integration, read the matching cookbook recipe:
  https://github.com/meta-models/meta-model-cookbook (clone to a scratch dir outside the repo).
- Retries with backoff on 429/5xx only; never retry 400.
- Every model call goes through one helper that logs model, provider, tokens, latency, and cost estimate.
- Keep prompts in `backend/prompts/*.md`, not inline strings.
- If something is blocked > 30 min, stop and report with options instead of hacking around it.

---

## 5. Demo video script (3:00)
- 0:00 One line: "Everything shown was built during the hackathon."
- 0:05 Phone films a laptop: tester applies promo twice, says "the total just went negative."
- 0:15 Cut to ReproCam: upload → live timeline lights up stage by stage with model badges.
- 0:50 First test passes → judge: "NOT_REPRODUCED — test never applied promo twice" → retry.
- 1:20 Second test fails red: `expected total >= 0, got -12.40` → REPRODUCED. Evidence image with SAM box.
- 1:45 Click "Run against fixed build" → green. "Every bug report is now a regression test."
- 2:10 Second bug, sped up.
- 2:30 Architecture slide: 3 Meta models, open weights on Baseten, verify loop.
- 2:50 Who it's for + next: native mobile, CI integration.

---

## 6. First prompt to give Claude Code

> Read CLAUDE.md and BUILD_PLAN.md. Start M1: build the Lumen & Loom practice store in
> `store/` with the 3 planted bugs and the `?fixed=1` toggle, plus hand-written Playwright
> tests in `tests/store/` that fail on buggy and pass on fixed. Run the tests to prove it,
> commit, tick the M1 boxes, and report back.
