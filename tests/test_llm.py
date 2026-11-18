"""OpenRouter client behaviour — no network, responses are stubbed."""
import time

import pytest

import rag.llm as llm


class Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text or str(payload or "")

    def json(self):
        return self._payload


def ok(content):
    return Resp(200, {"choices": [{"message": {"content": content},
                                   "finish_reason": "stop"}]})


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(llm.OpenRouterLLM, "_available_free_models",
                        lambda self: ["m1", "m2", "m3"])
    monkeypatch.setattr(time, "sleep", lambda *_: None)  # no real backoff
    return llm.OpenRouterLLM()


def test_returns_content(client, monkeypatch):
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: ok("hello [1]"))
    assert client.chat([{"role": "user", "content": "hi"}]) == "hello [1]"


def test_daily_cap_fails_fast(client, monkeypatch):
    """An account-wide daily cap must not be retried across every model —
    that stalls the request for minutes before it can degrade."""
    calls = []

    def post(*a, **k):
        calls.append(k["json"]["model"])
        return Resp(429, text="Rate limit exceeded: free-models-per-day")

    monkeypatch.setattr(llm.requests, "post", post)
    with pytest.raises(llm.LLMError, match="daily quota"):
        client.chat([{"role": "user", "content": "hi"}])
    assert len(calls) == 1, f"should stop after one attempt, made {len(calls)}"


def test_per_model_throttle_falls_through_to_next_model(client, monkeypatch):
    """A single throttled model should be skipped, not abort the whole call."""
    seen = []

    def post(*a, **k):
        m = k["json"]["model"]
        seen.append(m)
        if m == client.model:
            return Resp(429, text="temporarily rate-limited upstream")
        return ok("answer from fallback")

    monkeypatch.setattr(llm.requests, "post", post)
    assert client.chat([{"role": "user", "content": "hi"}]) == "answer from fallback"
    assert len(set(seen)) > 1, "should have tried a second model"


def test_empty_content_tries_next_model(client, monkeypatch):
    """Reasoning models can return HTTP 200 with content=null."""
    def post(*a, **k):
        if k["json"]["model"] == client.model:
            return Resp(200, {"choices": [{"message": {"content": None},
                                           "finish_reason": "length"}]})
        return ok("real answer")

    monkeypatch.setattr(llm.requests, "post", post)
    assert client.chat([{"role": "user", "content": "hi"}]) == "real answer"


def test_402_raises_immediately(client, monkeypatch):
    monkeypatch.setattr(llm.requests, "post",
                        lambda *a, **k: Resp(402, text="insufficient credits"))
    with pytest.raises(llm.LLMError, match="credits"):
        client.chat([{"role": "user", "content": "hi"}])


def test_missing_key_raises(monkeypatch):
    monkeypatch.setattr(llm, "_api_key", lambda: "")
    with pytest.raises(llm.LLMError, match="OPENROUTER_API_KEY"):
        llm.OpenRouterLLM()


def test_llm_mode_reflects_key(monkeypatch):
    monkeypatch.setattr(llm, "_api_key", lambda: "")
    assert llm.llm_mode() == "mock"
    monkeypatch.setattr(llm, "_api_key", lambda: "sk-or-test")
    assert llm.llm_mode() == "openrouter"
