# ReproCam

Film a bug, say what went wrong, get a failing Playwright test that proves it.

> Built from scratch during the Meta Global AI Developer Hackathon (Oct 27 – Nov 4, 2026).
> No pre-existing code.

## Meta models used
- **Muse Voice Transcribe** — narration to text
- **Muse Spark / Muse Spark Open** (Meta API, Baseten, Fireworks) — understands frames, plans steps, writes the test
- **SAM 3.1** — finds the broken UI element on the bug frame (video tracking optional)

SAM proposes, Muse Spark decides: SAM 3.1 boxes the candidate elements (every price on the screen),
and Muse Spark picks the one the tester's claim is about.

## Layout
- `store/`   practice web shop with planted bugs (the app under test)
- `backend/` agent pipeline + API (FastAPI)
- `web/`     ReproCam UI
- `scripts/` setup and smoke tests
- `samples/` demo bug videos

## Setup
```bash
cp .env.example .env        # add your keys
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
playwright install chromium
python scripts/check_env.py
```

## Practice store (Lumen & Loom)
```bash
python scripts/serve_store.py          # http://localhost:5173  (buggy build)
```
Open any page with `?fixed=1` for the fixed build (`?fixed=0` to go back; the choice sticks in localStorage).
Planted bugs (registry in `store/bugs.js`, one test per id in `tests/store/test_<id>.py`):
- `neg_total`: promo `GLOW20` ($20 off) can be applied again and again; the total goes negative.
- `qty_stepper`: "−" on quantity 1 drops the line to 0 but still charges for it.
- `zip_hang`: ZIP codes starting with `0` leave the "Place order" spinner spinning forever.

Ground-truth tests assert the correct behaviour, so they fail on buggy and pass on fixed:
```bash
STORE_MODE=buggy pytest tests/store   # 3 failed
STORE_MODE=fixed pytest tests/store   # 3 passed
```

## Known limitations
- **Invariants can be shallow.** With a known-good build, testgen v2 prefers asserting that on-screen values
  agree with each other. On bug2 it got there on the retry, but with a weak form: an if/else on the basket count
  with a hard-coded `$18.50`, not a computed quantity × price. It fails on the buggy build and passes on the
  fixed one, yet a price change would break it. One run each, so no claim of reliability yet.
- **Expected behaviour is the tester's guess.** Without a known-good build there is nothing to check the claim's
  `expected` against; such runs end "REPRODUCED · not verified".
- **SAM finds things, not meanings.** "order total" returns no boxes; "price" returns every price. Muse Spark picks
  the claimed one, and the evidence image says so.
- **Generated code runs in a subprocess, not a sandbox.** Fine for a demo on a practice store; a real deployment
  needs container isolation.

## Run the app
```bash
python -m backend.api        # http://localhost:8000 (also serves the store on :5173)
```
- **Try a sample bug** replays a cached run with its original timing, at $0.
- **Upload video** starts a live run (25 MB / 90 s max; daily and per-visitor caps in `.env`).
- **Run against fixed build** re-runs the reproducing test on `?fixed=1` (Playwright only, no model calls).
- **Known-good build** (optional, `KNOWN_GOOD_URL` or `--known-good fixed`): the test must also pass on a
  build without the bug, or it's retried; a run that never passes there ends *REPRODUCED · NOT CONFIRMED*.

Cache a finished run as a sample: `python scripts/cache_sample.py bug1`.

![ReproCam replaying bug1](docs/screenshots/m6_replay.png)
