"""Vector + keyword index: build (python -m rag.index) and load.

Embeddings: fastembed (ONNX MiniLM-L6-v2, no torch — small enough for free
hosting). Keyword: BM25. Persisted under data/index/.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

DATA = Path(__file__).resolve().parent.parent / "data"
INDEX = DATA / "index"
EMB_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
MAX_CHUNKS_PER_URL = 2


def _embedder():
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=EMB_MODEL)


EMB_BATCH = 256        # outer loop: progress reporting granularity
ENCODE_BATCH = 16      # fastembed's internal batch; its default (256)
                       # over-allocates and fails with "bad allocation"


def build() -> dict:
    from rag.chunking import chunk_documents

    docs = [json.loads(line) for line in
            open(DATA / "corpus.jsonl", encoding="utf-8")]
    chunks = chunk_documents(docs)
    print(f"{len(docs)} docs -> {len(chunks)} chunks; embedding with {EMB_MODEL}...")

    # Batch the encoder: one big call allocates a tensor for every chunk at
    # once and dies with "bad allocation" on modest RAM (and on free hosting).
    model = _embedder()
    parts: list[np.ndarray] = []
    for start in range(0, len(chunks), EMB_BATCH):
        batch = [c["text"] for c in chunks[start:start + EMB_BATCH]]
        parts.append(np.asarray(
            list(model.embed(batch, batch_size=ENCODE_BATCH)), dtype=np.float32))
        print(f"  embedded {min(start + EMB_BATCH, len(chunks))}/{len(chunks)}",
              flush=True)
    emb = np.vstack(parts)
    emb /= (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9)

    INDEX.mkdir(parents=True, exist_ok=True)
    np.save(INDEX / "embeddings.npy", emb)
    with open(INDEX / "chunks.jsonl", "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    meta = {"model": EMB_MODEL, "chunks": len(chunks), "dim": int(emb.shape[1])}
    (INDEX / "meta.json").write_text(json.dumps(meta))
    print(f"index built: {meta}")
    return meta


class Index:
    """Loaded search index: dense cosine + BM25, fused with RRF."""

    def __init__(self):
        from rank_bm25 import BM25Okapi
        self.chunks = [json.loads(line) for line in
                       open(INDEX / "chunks.jsonl", encoding="utf-8")]
        self.emb = np.load(INDEX / "embeddings.npy")
        self.meta = json.loads((INDEX / "meta.json").read_text())
        self._bm25 = BM25Okapi([c["text"].lower().split() for c in self.chunks])
        self._embedder = _embedder()

    def search(self, query: str, k: int = 8, source: str | None = None) -> list[dict]:
        qv = np.asarray(list(self._embedder.embed([query], batch_size=1)),
                        dtype=np.float32)[0]
        qv /= (np.linalg.norm(qv) + 1e-9)
        dense = self.emb @ qv
        sparse = np.array(self._bm25.get_scores(query.lower().split()))

        def rrf(ranks: np.ndarray) -> np.ndarray:
            order = np.argsort(-ranks)
            rr = np.empty(len(ranks))
            rr[order] = 1.0 / (60 + np.arange(len(ranks)))
            return rr

        score = rrf(dense) + rrf(sparse)
        if source and source != "both":
            mask = np.array([c["source"] == source for c in self.chunks])
            score = np.where(mask, score, -1.0)
        top = np.argsort(-score)[: k * 3]
        out: list[dict] = []
        per_url: Counter[str] = Counter()
        for i in top:
            if score[i] <= 0:
                continue
            c = self.chunks[i]
            if per_url[c["url"]] >= MAX_CHUNKS_PER_URL:
                continue  # keep one long page from crowding out other sources
            per_url[c["url"]] += 1
            out.append({**c, "score": float(score[i]), "dense": float(dense[i])})
            if len(out) >= k:
                break
        return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    build()
