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
