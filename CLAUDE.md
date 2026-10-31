# ReproCam — project memory for Claude Code

**Work order:** see `BUILD_PLAN.md` (v2: milestones, contracts, gates, acceptance checks). Follow it in order.

## What we're building
Hackathon entry (Meta Global AI Developer Hackathon, deadline **Wed Nov 4, 9:00 PM ET**).
A tester records a bug video + narration. The agent: transcribes (Muse Voice Transcribe),
reads frames and infers user steps (Muse Spark), locates/tracks the broken element (SAM 3.1),
writes a Playwright test, RUNS it, and only files a ticket when the test fails for the right
reason (retry loop otherwise). After the fix, the same test passes.

## Hard rules
- Every line in this repo is new hackathon work. Repo will be PUBLIC: never commit `.env` or keys.
- Product AI must run on Meta models. Use `backend/llm.py:get_client()`; never hardcode providers.
- Meta API: base `https://api.meta.ai/v1`, OpenAI SDK, key in `MODEL_API_KEY`, model `muse-spark-1.3`.
  Do NOT use the official Model API client package (out of date) — use the OpenAI SDK.
- Baseten model id: `meta-models/muse-spark-open-1026` (not the docs' default id).
- Voice Transcribe: one-shot `POST https://api.meta.ai/v1/asr/transcribe` (Authorization header),
  model `muse-voice-transcribe-1.0`, mono 16-bit WAV (convert with ffmpeg), max 10 min / 32 MB.
- SAM 3.1: model `sam-3.1` via Responses API through the OpenAI SDK; parse output ONLY with
  `meta_sam_parser`. Video: upload MP4 with `purpose=user_data`, stream events. One noun phrase per request.
  Reference: github.com/meta-models/meta-model-cookbook/tree/main/07_sam/01_api_basics
- Cost guard: public demo replays cached runs; live runs capped by MAX_RUNS_PER_DAY.
- Practice store must be an original fictional brand (not resembling any real retailer).

## Stack
Python 3.11+ (uv), FastAPI backend, Playwright (Python) for generated tests,
plain HTML/JS or a small React page for `web/` and `store/`.
