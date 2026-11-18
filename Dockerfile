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
    # model caches live under the writable home dir
    HF_HOME=/home/user/.cache/huggingface \
    FASTEMBED_CACHE_PATH=/home/user/.cache/fastembed

WORKDIR /home/user/app

# Dependencies as root (system site-packages). Playwright and pytest are
# dev/scrape-only and are stripped from the runtime install.
COPY requirements.txt .
RUN grep -viE '^(playwright|pytest)' requirements.txt > /tmp/req-runtime.txt \
 && pip install --no-cache-dir -r /tmp/req-runtime.txt

COPY . .

# Hand the home directory (app files + cache locations) to uid 1000 BEFORE
# dropping privileges, so every step below writes as its owner. Everything
# after this point runs as `user`, which is also how the container runs —
# so no build step can create a file the runtime user cannot read.
RUN mkdir -p /home/user/.cache && chown -R user:user /home/user
USER user

# Bake the embedding model in (as `user`, so the cache is correctly owned)
# to keep cold starts fast and offline.
RUN python -c "from fastembed import TextEmbedding; \
TextEmbedding('sentence-transformers/all-MiniLM-L6-v2')"

# Safety net: if no corpus was committed, collect Wasalt (sitemaps only —
# no browser needed) so the app never starts with an empty knowledge base.
RUN test -f data/corpus.jsonl || python -m scraper.run --skip-darglobal

# Build the vector + BM25 index from the corpus.
RUN python -m rag.index

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request as u; \
u.urlopen('http://127.0.0.1:7860/api/health').read()" || exit 1

# HF Spaces expects 7860; Render/Fly inject $PORT.
CMD ["sh", "-c", "uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
