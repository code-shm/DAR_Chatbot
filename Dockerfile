# Runtime image — serving only. Deliberately WITHOUT Playwright browsers
# (~400MB of Chromium): the DarGlobal crawl runs on a dev machine and its
# output is committed as data/corpus_darglobal.jsonl. The container rebuilds
# only the embedding index, which is cheap and deterministic.
FROM python:3.12-slim

# Non-root uid 1000 — required by Hugging Face Spaces, harmless elsewhere.
RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # keep model caches inside the writable home dir
    HF_HOME=/home/user/.cache/huggingface \
    FASTEMBED_CACHE_PATH=/home/user/.cache/fastembed

WORKDIR $HOME/app

# Install only the serving dependencies (playwright is dev/scrape-only).
COPY --chown=user requirements.txt .
RUN grep -viE '^(playwright|pytest)' requirements.txt > /tmp/req-runtime.txt \
 && pip install --no-cache-dir -r /tmp/req-runtime.txt \
 # bake the embedding model into the image so cold starts don't download it
 && python -c "from fastembed import TextEmbedding; \
TextEmbedding('sentence-transformers/all-MiniLM-L6-v2')"

COPY --chown=user . .

# Build the vector index from the committed corpus shards. If no corpus was
# committed, collect Wasalt (sitemaps only — no browser needed) so the app
# never starts with an empty knowledge base.
USER user
RUN test -f data/corpus.jsonl || python -m scraper.run --skip-darglobal \
 && python -m rag.index

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request as u; \
u.urlopen('http://127.0.0.1:7860/api/health').read()" || exit 1

# HF Spaces expects 7860; Render/Fly inject $PORT.
CMD ["sh", "-c", "uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
