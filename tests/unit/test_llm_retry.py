"""chat() rides out 503 overloads with jittered exponential backoff, and never retries a 400."""
from types import SimpleNamespace

import httpx2 as httpx
import pytest
from openai import APIStatusError

from backend import llm


def status_error(code: int, headers: dict | None = None) -> APIStatusError:
    req = httpx.Request("POST", "https://example.test/v1/chat/completions")
    return APIStatusError("boom", response=httpx.Response(code, headers=headers or {}, request=req), body=None)


def fake_client(failures: list):
    ok = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"), finish_reason="stop")],
                         usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, completion_tokens_details=None))
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if failures:
            raise failures.pop(0)
        return ok
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), calls


@pytest.fixture
def no_sleep(monkeypatch):
    waits = []
    monkeypatch.setattr(llm.time, "sleep", waits.append)
    monkeypatch.setattr(llm, "log_call", lambda row: None)
    return waits


def test_503s_are_retried_with_growing_waits(monkeypatch, no_sleep):
    client, calls = fake_client([status_error(503), status_error(503), status_error(503)])
    monkeypatch.setattr(llm, "get_client", lambda provider=None: (client, "m"))
    monkeypatch.setenv("LLM_RETRIES", "5")
    content, _ = llm.chat([{"role": "user", "content": "x"}], stage="judge", provider="fireworks", effort="low")
    assert content == "{}" and len(calls) == 4
    assert [int(w) for w in no_sleep] == [2, 4, 8]  # 2^n seconds plus under 1 s of jitter


def test_retry_after_header_is_respected_and_400_is_not_retried(monkeypatch, no_sleep):
    client, calls = fake_client([status_error(503, {"retry-after": "20"})])
    monkeypatch.setattr(llm, "get_client", lambda provider=None: (client, "m"))
    llm.chat([{"role": "user", "content": "x"}], stage="judge", provider="fireworks", effort="low")
    assert no_sleep[0] >= 20

    client, calls = fake_client([status_error(400)])
    monkeypatch.setattr(llm, "get_client", lambda provider=None: (client, "m"))
    with pytest.raises(APIStatusError):
        llm.chat([{"role": "user", "content": "x"}], stage="judge", provider="fireworks", effort="low")
    assert len(calls) == 1


def test_gives_up_after_the_last_attempt(monkeypatch, no_sleep):
    client, calls = fake_client([status_error(503)] * 3)
    monkeypatch.setattr(llm, "get_client", lambda provider=None: (client, "m"))
    with pytest.raises(APIStatusError):
        llm.chat([{"role": "user", "content": "x"}], stage="judge", provider="fireworks", effort="low", retries=3)
    assert len(calls) == 3 and len(no_sleep) == 2
