from rag.chunking import chunk_documents, split_text


def test_short_text_single_chunk():
    assert split_text("hello world") == ["hello world"]


def test_empty_text():
    assert split_text("   ") == []


def test_long_text_overlaps_and_covers():
    text = ". ".join(f"Sentence number {i} about villas in Riyadh" for i in range(200))
    chunks = split_text(text)
    assert len(chunks) > 1
    assert all(len(c) <= 1300 for c in chunks)
    # nothing lost: every 10th sentence appears somewhere
    joined = " ".join(chunks)
    for i in range(0, 200, 10):
        assert f"Sentence number {i} " in joined + " "


def test_chunk_documents_preserves_metadata_and_prefixes_title():
    docs = [{"source": "wasalt", "url": "https://x/1", "title": "Villa in Taif",
             "content_type": "listing-sale", "property_name": "", "location": "Taif",
             "date_scraped": "2026-11-18", "text": "A 300 sqm villa facing east."}]
    chunks = chunk_documents(docs)
    assert len(chunks) == 1
    c = chunks[0]
    assert c["source"] == "wasalt" and c["location"] == "Taif"
    assert c["chunk_id"] == "https://x/1#0"
    assert c["text"].startswith("Villa in Taif")
