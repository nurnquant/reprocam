"""One switch for which provider runs Muse Spark / Muse Spark Open, and one helper for calls.

All three providers are OpenAI-compatible, so only base_url, key and model change.
Voice Transcribe and SAM 3.1 are Meta-API-only and live in their own modules.

Every text/vision model call goes through chat(): it applies the stage's reasoning effort
(EFFORT_<STAGE> in .env), retries 429/5xx with backoff (never 400), and logs model, provider,
effort, tokens, latency and cost estimate to data/llm_calls.jsonl.
"""
import json
import os
import random
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, OpenAI

load_dotenv()

PROVIDERS = {
    "meta": ("META_BASE_URL", "MODEL_API_KEY", "META_MODEL"),
    "baseten": ("BASETEN_BASE_URL", "BASETEN_API_KEY", "BASETEN_MODEL"),
    "fireworks": ("FIREWORKS_BASE_URL", "FIREWORKS_API_KEY", "FIREWORKS_MODEL"),
}

CALL_LOG = Path(__file__).resolve().parent.parent / "data" / "llm_calls.jsonl"
RETRY_STATUS = {429, 500, 502, 503, 504}
# One output budget for every stage and effort level (reasoning tokens count against it).
# 32,000: at high effort one test-writing call spent all of 16,000 on reasoning (M4b sweep).
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "32000"))


def get_client(provider: str | None = None) -> tuple[OpenAI, str]:
    provider = (provider or os.getenv("LLM_PROVIDER", "meta")).lower()
    url_var, key_var, model_var = PROVIDERS[provider]
    key = os.getenv(key_var)
    if not key:
        raise RuntimeError(f"{key_var} is not set in .env (provider={provider})")
    return OpenAI(base_url=os.environ[url_var], api_key=key, max_retries=0), os.environ[model_var]


def effort_for(stage: str) -> str:
    return os.getenv(f"EFFORT_{stage.upper()}", "low")


def cost_estimate(provider: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """USD from PRICE_<PROVIDER>_IN / _OUT (per 1M tokens) in .env; None when not set."""
    p_in = os.getenv(f"PRICE_{provider.upper()}_IN")
    p_out = os.getenv(f"PRICE_{provider.upper()}_OUT")
    if not (p_in and p_out):
        return None
    return round((prompt_tokens * float(p_in) + completion_tokens * float(p_out)) / 1e6, 6)


def chat(messages: list[dict], *, stage: str, provider: str | None = None, effort: str | None = None,
         response_format: dict | None = None, max_tokens: int | None = None, retries: int | None = None,
         log_extra: dict | None = None) -> tuple[str, dict]:
    """Returns (content, meta). meta = model, provider, effort, tokens, latency_s, cost_usd."""
    provider = (provider or os.getenv("LLM_PROVIDER", "meta")).lower()
    effort = effort or effort_for(stage)
    max_tokens = max_tokens or MAX_OUTPUT_TOKENS
    retries = retries or int(os.getenv("LLM_RETRIES", "3"))  # batch jobs raise it to ride out 503 overloads
    client, model = get_client(provider)
    kwargs = {"model": model, "messages": messages, "reasoning_effort": effort, "max_tokens": max_tokens}
    if response_format:
        kwargs["response_format"] = response_format

    for attempt in range(retries):
        started = time.time()
        wait = min(60.0, 2.0 ** (attempt + 1)) + random.uniform(0, 1)  # exponential backoff with jitter
        try:
            r = client.chat.completions.create(**kwargs)
            break
        except APIStatusError as e:
            if e.status_code not in RETRY_STATUS or attempt == retries - 1:
                raise
            after = e.response.headers.get("retry-after") if e.response is not None else None
            if after and after.replace(".", "", 1).isdigit():
                wait = max(wait, min(60.0, float(after)))
        except APIConnectionError:
            if attempt == retries - 1:
                raise
        time.sleep(wait)

    u = r.usage
    details = getattr(u, "completion_tokens_details", None)
    meta = {
        "stage": stage, "model": model, "provider": provider, "effort": effort,
        "prompt_tokens": u.prompt_tokens if u else None,
        "completion_tokens": u.completion_tokens if u else None,
        "reasoning_tokens": getattr(details, "reasoning_tokens", None) if details else None,
        "latency_s": round(time.time() - started, 2),
        "finish_reason": r.choices[0].finish_reason, "max_tokens": max_tokens,
    }
    meta["cost_usd"] = cost_estimate(provider, meta["prompt_tokens"] or 0, meta["completion_tokens"] or 0)
    log_call({**meta, **(log_extra or {})})
    content = r.choices[0].message.content or ""
    if meta["finish_reason"] == "length" and not content.strip():
        raise TruncatedAnswer(f"{stage}: the model used all {max_tokens} output tokens "
                              f"({meta['reasoning_tokens']} on reasoning) and returned no answer", meta)
    return content, meta


class TruncatedAnswer(RuntimeError):
    """The output budget ran out (typically on reasoning at high effort) before any answer.
    Carries the call's meta so its cost is still counted."""

    def __init__(self, message: str, meta: dict):
        super().__init__(message)
        self.meta = meta


def log_call(row: dict) -> None:
    """Append one model call to data/llm_calls.jsonl (also used for SAM calls)."""
    CALL_LOG.parent.mkdir(exist_ok=True)
    with CALL_LOG.open("a") as f:
        f.write(json.dumps({"ts": round(time.time(), 1), **row}, default=str) + "\n")
