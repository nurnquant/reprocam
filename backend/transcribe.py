"""Muse Voice Transcribe, one-shot endpoint.

Request shape follows the Meta cookbook recipe
06_muse_voice/01_voice_api_fundamentals/utils.py::transcribe_recording:
multipart body with a JSON "request" part and the WAV as the "audio" part,
credential in a Bearer Authorization header.
"""
import json
import os
import re
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

URL = "https://api.meta.ai/v1/asr/transcribe"
MODEL = "muse-voice-transcribe-1.0"
MAX_BYTES = 32 * 1024 * 1024  # also a 10 minute cap, enforced server-side
RETRY_STATUS = {429, 500, 502, 503, 504}

STORE_APP = Path(__file__).resolve().parent.parent / "store" / "app.js"
DOMAIN_WORDS = ["Lumen & Loom", "promo", "promo code", "GLOW20", "basket", "checkout",
                "ZIP", "ZIP code", "place order", "quantity", "subtotal", "total"]


class TranscribeError(RuntimeError):
    pass


def store_keywords() -> list[str]:
    """Product names from the store + domain words, to bias recognition."""
    names = re.findall(r'name: "([^"]+)"', STORE_APP.read_text()) if STORE_APP.exists() else []
    return DOMAIN_WORDS + names


def transcribe(wav_path: str | Path, keywords: list[str] | None = None,
               mode: str = "PUSH_TO_TALK", timeout: int = 300, retries: int = 3) -> dict:
    """POST a mono 16-bit WAV. Returns the API JSON plus model, latency_s."""
    token = os.getenv("MODEL_API_KEY")
    if not token:
        raise TranscribeError("MODEL_API_KEY is not set in .env")
    wav_path = Path(wav_path)
    size = wav_path.stat().st_size
    if size > MAX_BYTES:
        raise TranscribeError(f"{wav_path} is {size / 2**20:.1f} MB; the limit is 32 MB")

    request = {"mode": mode, "model": MODEL, "audioEncoding": "WAV",
               "keywords": keywords if keywords is not None else store_keywords()}
    if not request["keywords"]:
        del request["keywords"]  # the server ignores empty fields silently

    for attempt in range(retries):
        started = time.time()
        with wav_path.open("rb") as audio:
            r = requests.post(
                URL,
                headers={"Authorization": f"Bearer {token}"},
                files={"request": (None, json.dumps(request), "application/json"),
                       "audio": (wav_path.name, audio, "audio/wav")},
                timeout=timeout,
            )
        if r.status_code == 200:
            return {**r.json(), "model": MODEL, "latency_s": round(time.time() - started, 2)}
        if r.status_code not in RETRY_STATUS or attempt == retries - 1:
            raise TranscribeError(f"[{r.status_code}] {r.text[:300]}")
        time.sleep(2 ** attempt)
