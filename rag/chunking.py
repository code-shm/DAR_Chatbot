"""Split corpus documents into retrieval chunks, preserving metadata."""
from __future__ import annotations

CHUNK_CHARS = 1200
OVERLAP = 150
META_KEYS = ("source", "url", "title", "content_type", "property_name",
             "location", "date_scraped")


def split_text(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP) -> list[str]:
    """Greedy splitter that prefers paragraph, then sentence boundaries."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # back off to the last paragraph/sentence break in the window
            window = text[start:end]
            cut = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("۔"))
            if cut > size // 2:
                end = start + cut + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def chunk_documents(docs: list[dict]) -> list[dict]:
    chunks = []
    for d in docs:
        meta = {k: d.get(k, "") for k in META_KEYS}
        for i, piece in enumerate(split_text(d.get("text", ""))):
            # prefix title so short chunks stay self-describing for retrieval
            body = piece if piece.startswith(meta["title"] or "\0") else \
                f"{meta['title']}\n{piece}" if meta["title"] else piece
            chunks.append({**meta, "chunk_id": f"{meta['url']}#{i}", "text": body})
    return chunks
