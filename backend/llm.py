"""One switch for which provider runs Muse Spark / Muse Spark Open.

All three providers are OpenAI-compatible, so only base_url, key and model change.
Voice Transcribe and SAM 3.1 are Meta-API-only and live in their own modules.
"""
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

PROVIDERS = {
    "meta": ("META_BASE_URL", "MODEL_API_KEY", "META_MODEL"),
    "baseten": ("BASETEN_BASE_URL", "BASETEN_API_KEY", "BASETEN_MODEL"),
    "fireworks": ("FIREWORKS_BASE_URL", "FIREWORKS_API_KEY", "FIREWORKS_MODEL"),
}


def get_client(provider: str | None = None) -> tuple[OpenAI, str]:
    provider = (provider or os.getenv("LLM_PROVIDER", "meta")).lower()
    url_var, key_var, model_var = PROVIDERS[provider]
    key = os.getenv(key_var)
    if not key:
        raise RuntimeError(f"{key_var} is not set in .env (provider={provider})")
    return OpenAI(base_url=os.environ[url_var], api_key=key), os.environ[model_var]
