"""LLM layer: OpenRouter client with graceful degradation, plus a clearly
labeled extractive mock used ONLY when no OPENROUTER_API_KEY is configured.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _api_key() -> str:
    """Read the key, loading .env first so every entry point agrees.

    (The server loads .env itself, but scripts and tests import this module
    directly — without this they would silently fall back to demo mode.)
    """
    if not os.environ.get("OPENROUTER_API_KEY"):
        load_dotenv(_ENV_FILE)
    return os.environ.get("OPENROUTER_API_KEY", "").strip()

# Probed live on 2026-11-18 (scripts/probe_models.py): of the 14 free models,
# these 8 answered a RAG-style prompt correctly AND emitted citations. The
# Gemma models were rate-limited upstream, and the two reasoning models
# (nemotron-3.5-lightning, dots-3-note-preview) returned content=None because
# they spend the whole token budget on hidden reasoning — so neither is listed.
DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
PREFERRED_FREE = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",   # 550B, ~1.3s, 1M ctx
    "nvidia/nemotron-3.5-super-vl:free",        # ~1.2s
    "particle-ai/particle-1:free",              # ~1.5s, 1M ctx
    "inclusionai/ling-3.2-flash:free",          # ~2.3s, 1M ctx
    "baidu/ernie-5.5-flash-preview:free",       # ~1.7s
    "recursive/flint-v1.0:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
]


# OpenRouter reports an account-wide daily cap as "free-models-per-day";
# per-model throttling reads "temporarily rate-limited upstream".
DAILY_CAP_RE = re.compile(r"per-day|daily limit|free-models-per-day", re.I)


class LLMError(RuntimeError):
    pass


class OpenRouterLLM:
    def __init__(self):
        self.key = _api_key()
        self.base = os.environ.get("OPENROUTER_BASE_URL",
                                   "https://openrouter.ai/api/v1").rstrip("/")
        self.model = os.environ.get("OPENROUTER_MODEL") or DEFAULT_MODEL
        if not self.key:
            raise LLMError("OPENROUTER_API_KEY is not set")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.environ.get("APP_PUBLIC_URL", "http://localhost:8000"),
            "X-Title": "DAR & Wasalt Property Assistant",
        }

    def _available_free_models(self) -> list[str]:
        try:
            r = requests.get(f"{self.base}/models", timeout=20)
            ids = {m["id"] for m in r.json().get("data", [])}
            return [m for m in PREFERRED_FREE if m in ids] or \
                   sorted(i for i in ids if i.endswith(":free"))[:3]
        except Exception:
            return PREFERRED_FREE

    def chat(self, messages: list[dict], max_tokens: int = 900) -> str:
        models = [self.model] + [m for m in self._available_free_models()
                                 if m != self.model]
        last_err = "no model attempted"
        for model in models[:6]:   # widen the net; the free pool throttles often
            for attempt in range(3):
                try:
                    r = requests.post(
                        f"{self.base}/chat/completions", headers=self._headers(),
                        json={"model": model, "messages": messages,
                              "max_tokens": max_tokens, "temperature": 0.2},
                        timeout=90,
                    )
                except requests.RequestException as e:
                    last_err = f"network: {e}"
                    time.sleep(2 ** attempt)
                    continue
                if r.status_code == 200:
                    try:
                        choice = r.json()["choices"][0]
                        content = (choice.get("message") or {}).get("content")
                    except (KeyError, IndexError, ValueError):
                        last_err = f"malformed response from {model}"
                        break
                    # A 200 does not guarantee text: reasoning models can burn
                    # the whole budget on hidden reasoning and return null.
                    if isinstance(content, str) and content.strip():
                        return content
                    last_err = (f"{model} returned empty content "
                                f"(finish_reason={choice.get('finish_reason')})")
                    break  # a different model will do better than a retry
                if r.status_code == 429:
                    body = r.text[:400]
                    # An account-level daily cap ("free-models-per-day")
                    # applies to EVERY free model, so retrying others just
                    # stalls the request for minutes. Give up at once and let
                    # the caller degrade to cited excerpts.
                    if DAILY_CAP_RE.search(body):
                        raise LLMError(
                            "OpenRouter free-tier daily quota exhausted for "
                            "this key — all free models are blocked until it "
                            f"resets. ({body[:120]})")
                    time.sleep(2 * (attempt + 1))   # per-model throttle
                    last_err = f"429 from {model}"
                    continue
                if r.status_code in (402, 403):
                    raise LLMError(
                        "OpenRouter refused the request (credits/permissions). "
                        f"HTTP {r.status_code}: {r.text[:200]}")
                if r.status_code in (404, 400):  # model gone / ctx too long
                    last_err = f"{r.status_code} from {model}: {r.text[:150]}"
                    break  # try next model
                last_err = f"{r.status_code} from {model}: {r.text[:150]}"
                time.sleep(2 ** attempt)
        raise LLMError(f"All model attempts failed. Last error: {last_err}")


class MockLLM:
    """No-key fallback: honest extractive answers from the retrieved chunks.

    Never invents text; it quotes the sources, so the full RAG path (retrieval,
    citations, UI) works end-to-end before an API key exists.
    """

    BANNER = ("**[demo mode — no LLM key configured]** Showing the most "
              "relevant source excerpts instead of a generated answer:\n\n")
    BUSY_BANNER = ("**[I can't write a full answer right now — the free "
                   "models are rate-limited.]** Here are the most relevant "
                   "excerpts I found, so you're not left empty-handed. Try "
                   "again shortly for a written answer:\n\n")

    def __init__(self, banner: str | None = None):
        self.banner = banner or self.BANNER

    def answer(self, question: str, context_blocks: list[dict]) -> str:
        q_terms = {w for w in re.findall(r"\w+", question.lower()) if len(w) > 3}
        picked = []
        for b in context_blocks[:4]:
            sents = re.split(r"(?<=[.!?])\s+", b["text"])
            sents.sort(key=lambda s: -len(q_terms & set(re.findall(r"\w+", s.lower()))))
            excerpt = " ".join(sents[:2])[:400]
            picked.append(f"- {excerpt} [{b['n']}]")
        if not picked:
            return (self.banner +
                    "No relevant information found in the knowledge base for this question.")
        return self.banner + "\n".join(picked)


def llm_mode() -> str:
    return "openrouter" if _api_key() else "mock"
