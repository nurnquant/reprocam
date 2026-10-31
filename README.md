# ReproCam

Film a bug, say what went wrong, get a failing Playwright test that proves it.

> Built from scratch during the Meta Global AI Developer Hackathon (Oct 27 – Nov 4, 2026).
> No pre-existing code.

## Meta models used
- **Muse Voice Transcribe** — narration to text
- **Muse Spark / Muse Spark Open** (Meta API, Baseten, Fireworks) — understands frames, plans steps, writes the test
- **SAM 3.1** — finds and tracks the broken UI element across the video

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
Planted bugs:
1. Promo `GLOW20` ($20 off) can be applied again and again; the total goes negative.
2. "−" on quantity 1 drops the line to 0 but still charges for it.
3. ZIP codes starting with `0` leave the "Place order" spinner spinning forever.

Ground-truth tests assert the correct behaviour, so they fail on buggy and pass on fixed:
```bash
STORE_MODE=buggy pytest tests/store   # 3 failed
STORE_MODE=fixed pytest tests/store   # 3 passed
```
