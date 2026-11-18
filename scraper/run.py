"""Build/refresh the knowledge corpus.

  python -m scraper.run                      # both sources
  python -m scraper.run --skip-wasalt        # refresh DarGlobal only
  python -m scraper.run --skip-darglobal     # refresh Wasalt only

Each source is written to its own shard (data/corpus_<source>.jsonl) and the
shards are merged into data/corpus.jsonl. Skipping a source therefore REUSES
its existing shard instead of dropping its documents. Rebuild the index after:
  python -m rag.index
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DATA = Path(__file__).resolve().parent.parent / "data"
SOURCES = ("wasalt", "darglobal")


def shard(source: str) -> Path:
    return DATA / f"corpus_{source}.jsonl"


def write_shard(source: str, docs: list[dict]) -> None:
    with open(shard(source), "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")


def read_shard(source: str) -> list[dict]:
    p = shard(source)
    if not p.exists():
        return []
    return [json.loads(line) for line in open(p, encoding="utf-8")]


def dedupe(docs: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for d in docs:
        key = hashlib.sha1((d["url"] + d["text"][:500]).encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=130,
                    help="darglobal crawl cap")
    ap.add_argument("--max-listing-docs", type=int, default=1500,
                    help="how many individual Wasalt listings to keep")
    ap.add_argument("--skip-darglobal", action="store_true")
    ap.add_argument("--skip-wasalt", action="store_true")
    args = ap.parse_args()

    DATA.mkdir(exist_ok=True)

    if not args.skip_wasalt:
        print("== Wasalt (public CDN sitemaps) ==")
        from scraper.wasalt import build_documents
        write_shard("wasalt", build_documents(
            max_listing_docs=args.max_listing_docs))

    if not args.skip_darglobal:
        print("== DarGlobal (headless browser crawl) ==")
        from scraper.darglobal import crawl
        write_shard("darglobal", crawl(max_pages=args.max_pages))

    docs: list[dict] = []
    for s in SOURCES:
        part = read_shard(s)
        print(f"  shard {s}: {len(part)} docs"
              f"{' (reused)' if getattr(args, f'skip_{s}') else ''}")
        docs += part

    if not docs:
        print("ERROR: no documents collected; refusing to write an empty corpus.")
        return 1

    docs = dedupe(docs)
    out = DATA / "corpus.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    stats = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "total_docs": len(docs),
        "by_source": {s: sum(1 for d in docs if d["source"] == s) for s in SOURCES},
        "by_type": {},
    }
    for d in docs:
        stats["by_type"][d["content_type"]] = stats["by_type"].get(d["content_type"], 0) + 1
    (DATA / "corpus_stats.json").write_text(json.dumps(stats, indent=2))
    print(f"\nWrote {len(docs)} docs -> {out}")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
