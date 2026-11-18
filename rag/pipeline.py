"""RAG orchestration: retrieve -> build cited context -> generate answer."""
from __future__ import annotations

import re

from rag.index import Index
from rag.llm import LLMError, MockLLM, OpenRouterLLM, llm_mode

# Measured on this corpus: on-topic queries score 0.50-0.78 dense cosine,
# off-topic ones 0.06-0.25. 0.35 sits in the gap, so anything below it is
# answered honestly instead of being passed to the LLM to guess from.
RELEVANCE_FLOOR = 0.35

NO_ANSWER = (
    "I don't have information about that. I can only answer from public "
    "**DarGlobal** (luxury property developer) and **Wasalt** (Saudi property "
    "marketplace) data — projects, locations, listings, amenities, partners, "
    "press and investment information. Try asking about a development, a "
    "Saudi city, or a property type."
)

SYSTEM_PROMPT = """You are a property-information assistant for two sources:
1. DarGlobal (darglobal.co.uk) — a London-listed international LUXURY REAL
   ESTATE DEVELOPER (projects in Dubai, Saudi Arabia, Qatar, Oman, Spain, UK...).
2. Wasalt (wasalt.sa) — a Saudi Arabian PROPERTY MARKETPLACE with
   sale/rental listings.

Rules:
- Answer ONLY from the numbered SOURCES below. Cite every claim like [1][2].
- If the sources don't contain the answer, say so plainly and suggest what
  to check instead. NEVER invent prices, availability, sizes or returns.
- Wasalt data here comes from public sitemaps (titles, types, sizes,
  locations, URLs). Prices/amenities are NOT in this knowledge base — for
  those, direct the user to the cited listing URL.
- Always make clear which source (DarGlobal or Wasalt) information comes from.
- Keep answers concise and conversational. Use the chat history for
  follow-up questions."""


class Chatbot:
    def __init__(self):
        self.index = Index()
        self.mode = llm_mode()
        self._llm = OpenRouterLLM() if self.mode == "openrouter" else None

    def answer(self, question: str, history: list[dict] | None = None,
               source: str = "both", k: int = 8) -> dict:
        history = history or []
        # retrieval query: fold in a little recent context for follow-ups
        recent = " ".join(m["content"] for m in history[-2:]
                          if m.get("role") == "user")
        hits = self.index.search(f"{recent} {question}".strip(), k=k, source=source)

        # Off-topic question: say so rather than letting the model improvise
        # from whatever happened to rank highest.
        if not hits or max(h["dense"] for h in hits) < RELEVANCE_FLOOR:
            return {"answer": NO_ANSWER, "sources": [], "mode": self.mode,
                    "off_topic": True}

        blocks, sources = [], []
        for n, h in enumerate(hits, 1):
            blocks.append({"n": n, "text": h["text"][:1100]})
            sources.append({"n": n, "title": h["title"] or h["url"],
                            "url": h["url"], "source": h["source"],
                            "type": h["content_type"]})

        if self.mode == "mock":
            return {"answer": MockLLM().answer(question, blocks),
                    "sources": sources, "mode": "mock"}

        ctx = "\n\n".join(f"[{b['n']}] {b['text']}" for b in blocks) \
              or "(no sources matched)"
        messages = ([{"role": "system", "content": SYSTEM_PROMPT}]
                    + [{"role": m["role"], "content": m["content"][:2000]}
                       for m in history[-6:]]
                    + [{"role": "user",
                        "content": f"SOURCES:\n{ctx}\n\nQUESTION: {question}"}])
        try:
            text = self._llm.chat(messages)
        except LLMError as e:
            return {"answer": f"The language model is unavailable right now "
                              f"({e}). Please try again shortly.",
                    "sources": sources, "mode": "error"}
        # keep only sources actually cited, but never drop all of them
        cited = {int(n) for n in re.findall(r"\[(\d+)\]", text)}
        shown = [s for s in sources if s["n"] in cited] or sources[:3]
        return {"answer": text, "sources": shown, "mode": "openrouter"}
