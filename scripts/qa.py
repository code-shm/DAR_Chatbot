"""QA harness: run realistic questions through the full RAG pipeline.

Usage: python scripts/qa.py            (uses whatever LLM mode is configured)
Prints each answer with its cited sources for manual review.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rag.pipeline import Chatbot  # noqa: E402

QUESTIONS = [
    ("both", "What projects does DarGlobal currently have?"),
    ("darglobal", "Tell me about the Trump International projects"),
    ("darglobal", "Which luxury brands does DarGlobal partner with?"),
    ("darglobal", "What did DarGlobal report in its latest financial results?"),
    ("wasalt", "Which cities does Wasalt cover?"),
    ("wasalt", "What villas are for sale on Wasalt?"),
    ("wasalt", "Are there apartments with 3 bedrooms on Wasalt?"),
    ("both", "Compare what DarGlobal and Wasalt each offer"),
    ("both", "What is the price of a villa in Riyadh?"),  # should admit no price data
    ("both", "Who won the cricket world cup?"),           # should refuse / say unavailable
]


def main():
    bot = Chatbot()
    print(f"LLM mode: {bot.mode}\n" + "=" * 70)
    for source, q in QUESTIONS:
        r = bot.answer(q, source=source)
        print(f"\nQ [{source}]: {q}\nA: {r['answer'][:600]}")
        for s in r["sources"][:4]:
            print(f"   [{s['n']}] ({s['source']}) {s['url']}")
        print("-" * 70)


if __name__ == "__main__":
    main()
