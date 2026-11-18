"""Retrieval tests against a tiny synthetic index (no network, no real corpus)."""
import json

import numpy as np
import pytest

import rag.index as idx


@pytest.fixture
def tiny_index(tmp_path, monkeypatch):
    """Build a 6-chunk index by hand, with deterministic fake embeddings."""
    chunks = [
        # one long DarGlobal page split into 4 chunks (same url)
        *[{"source": "darglobal", "url": "https://dg/marea", "title": "Marea",
           "content_type": "project", "property_name": "Marea",
           "location": "Spain", "date_scraped": "2026-11-18",
           "chunk_id": f"https://dg/marea#{i}",
           "text": f"Marea villas Missoni Spain part {i}"} for i in range(4)],
        {"source": "wasalt", "url": "https://w/riyadh", "title": "Riyadh",
         "content_type": "location-directory", "property_name": "",
         "location": "Riyadh", "date_scraped": "2026-11-18",
         "chunk_id": "https://w/riyadh#0",
         "text": "Wasalt villas apartments Riyadh Saudi Arabia districts"},
        {"source": "wasalt", "url": "https://w/jeddah", "title": "Jeddah",
         "content_type": "location-directory", "property_name": "",
         "location": "Jeddah", "date_scraped": "2026-11-18",
         "chunk_id": "https://w/jeddah#0",
         "text": "Wasalt villas apartments Jeddah Saudi Arabia districts"},
    ]
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    with open(index_dir / "chunks.jsonl", "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c) + "\n")
    # all-ones embeddings => dense scores tie, so BM25/RRF ordering decides
    emb = np.ones((len(chunks), 4), dtype=np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)
    np.save(index_dir / "embeddings.npy", emb)
    (index_dir / "meta.json").write_text(json.dumps({"model": "fake", "dim": 4}))

    monkeypatch.setattr(idx, "INDEX", index_dir)
    class FakeEmbedder:
        @staticmethod
        def embed(texts, **kwargs):  # accepts batch_size like the real one
            return iter([np.ones(4, dtype=np.float32) for _ in texts])

    monkeypatch.setattr(idx, "_embedder", FakeEmbedder)
    return idx.Index()


def test_caps_chunks_per_url(tiny_index):
    """A single long page must not occupy every slot (regression)."""
    hits = tiny_index.search("Marea Missoni Spain", k=6)
    counts = {}
    for h in hits:
        counts[h["url"]] = counts.get(h["url"], 0) + 1
    assert max(counts.values()) <= idx.MAX_CHUNKS_PER_URL
    assert len(counts) > 1, "results should span more than one document"


def test_source_filter_darglobal(tiny_index):
    hits = tiny_index.search("villas", k=6, source="darglobal")
    assert hits and all(h["source"] == "darglobal" for h in hits)


def test_source_filter_wasalt(tiny_index):
    hits = tiny_index.search("villas", k=6, source="wasalt")
    assert hits and all(h["source"] == "wasalt" for h in hits)


def test_both_sources_by_default(tiny_index):
    hits = tiny_index.search("villas Saudi Spain", k=6)
    assert {h["source"] for h in hits} == {"darglobal", "wasalt"}


def test_respects_k(tiny_index):
    assert len(tiny_index.search("villas", k=2)) <= 2


def test_metadata_and_scores_present(tiny_index):
    h = tiny_index.search("Riyadh districts", k=1)[0]
    assert h["url"].startswith("https://")
    assert "score" in h and isinstance(h["score"], float)
    assert h["date_scraped"] == "2026-11-18"
