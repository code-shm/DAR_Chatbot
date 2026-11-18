"""Pipeline tests with a stubbed index — no model load, no network."""
import pytest

import rag.pipeline as pl


class StubIndex:
    """Returns hits whose dense score we control per test."""

    def __init__(self, dense):
        self._dense = dense

    def search(self, query, k=8, source=None):
        return [{"source": "darglobal", "url": f"https://dg/p{i}",
                 "title": f"Page {i}", "content_type": "project",
                 "text": f"Marea villas in Spain, detail {i}.",
                 "score": 1.0, "dense": self._dense}
                for i in range(3)]


class StubLLM:
    def chat(self, messages, **kw):
        return "Marea is a development in Spain [1]."


@pytest.fixture
def bot_factory(monkeypatch):
    def make(dense, mode="mock"):
        monkeypatch.setattr(pl, "Index", lambda: StubIndex(dense))
        monkeypatch.setattr(pl, "llm_mode", lambda: mode)
        # the real client raises when OPENROUTER_API_KEY is absent
        monkeypatch.setattr(pl, "OpenRouterLLM", StubLLM)
        return pl.Chatbot()
    return make


def test_off_topic_is_refused_without_calling_llm(bot_factory):
    bot = bot_factory(dense=0.10)
    r = bot.answer("Who won the cricket world cup?")
    assert r["off_topic"] is True
    assert r["sources"] == []
    assert "don't have information" in r["answer"]


def test_borderline_below_floor_refused(bot_factory):
    r = bot_factory(dense=pl.RELEVANCE_FLOOR - 0.01).answer("something odd")
    assert r.get("off_topic") is True


def test_on_topic_answers_with_sources(bot_factory):
    r = bot_factory(dense=0.70).answer("Tell me about Marea")
    assert not r.get("off_topic")
    assert r["sources"], "on-topic answers must cite sources"
    assert all(s["url"].startswith("https://") for s in r["sources"])
    assert all("n" in s for s in r["sources"])


def test_mock_mode_is_labeled(bot_factory):
    r = bot_factory(dense=0.70).answer("Tell me about Marea")
    assert r["mode"] == "mock"
    assert "demo mode" in r["answer"]


def test_llm_failure_degrades_gracefully(bot_factory, monkeypatch):
    bot = bot_factory(dense=0.70, mode="openrouter")

    class Boom:
        def chat(self, *a, **k):
            raise pl.LLMError("simulated outage")

    bot._llm = Boom()
    r = bot.answer("Tell me about Marea")
    assert r["mode"] == "error"
    assert "unavailable" in r["answer"]
    assert r["sources"], "sources should still be offered when the LLM fails"


def test_history_is_used_for_followups(bot_factory):
    """Follow-up questions fold recent user turns into the retrieval query."""
    bot = bot_factory(dense=0.70)
    seen = {}
    orig = bot.index.search

    def spy(query, **kw):
        seen["query"] = query
        return orig(query, **kw)

    bot.index.search = spy
    bot.answer("What about the price?",
               history=[{"role": "user", "content": "Tell me about Marea"},
                        {"role": "assistant", "content": "Marea is in Spain."}])
    assert "Marea" in seen["query"]
