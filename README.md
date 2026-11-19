# DAR & Wasalt Property Assistant

**Release 1.0** · [Live demo → dar-wasalt-chatbot.onrender.com](https://dar-wasalt-chatbot.onrender.com)

A retrieval-augmented chatbot that answers questions about **DarGlobal**
(London-listed luxury real-estate developer) and **Wasalt** (Saudi property
marketplace), grounded in publicly available data and answering with clickable
source citations on every claim.

Ask it about a development, a city, a property type or a price bracket and it
retrieves the relevant pages, writes an answer from them, and shows you exactly
which sources it used.

---

## Highlights

- **Two voiced advisors.** Choose Maria or Ben; each answers in the first
  person with a distinct voice and avatar.
- **Full voice loop.** Speak your question, get a spoken answer — browser-native
  speech recognition and synthesis, no API keys, no server cost.
- **Every claim cited.** Answers carry numbered citations that render as
  clickable chips linking back to the source page.
- **Refuses what it doesn't know.** A measured relevance threshold rejects
  off-topic questions before the language model is ever called.
- **Source filtering.** Scope any question to DarGlobal, Wasalt, or both.
- **Conversational.** Follow-ups resolve against earlier turns, so "what about
  its location?" works.
- **Light and dark themes**, keyboard accessible, and laid out to work from
  390 px phone width upward.
- **Deploys free.** Runs in a 512 MB container with the knowledge index baked
  into the image.

---

## What's in this release

### Conversational layer

Two personas, Maria and Ben, selectable from the chat header. The persona name
is injected into the system prompt, so the assistant's self-reference, voice and
avatar stay consistent across a conversation. Answers can be read aloud through
the Web Speech API with voice matching per persona, and questions can be spoken
instead of typed — dictation fills the composer live as you speak and sends on
completion. Speech output pauses the moment the microphone opens.

### Retrieval

Hybrid search over the corpus: dense embeddings (`fastembed`, ONNX MiniLM-L6)
fused with BM25 sparse retrieval via Reciprocal Rank Fusion, capped at two
chunks per source URL so one long page can't crowd out the rest of the results.
Retrieved chunks become a numbered, cited context block for the language model,
and the answer's citations are mapped back to real URLs before display.

Off-topic questions are caught by a relevance floor calibrated against measured
scores — on-topic queries score 0.497–0.777 dense cosine, off-topic ones
0.057–0.248 — so the floor sits at 0.35 and the model is never asked to answer
something the corpus can't support.

### Data pipeline

| Source | Method | Coverage |
|---|---|---|
| **DarGlobal** | Polite headless-Chromium crawl at 1 req/s, breadth-first from the homepage, `robots.txt` respected | 44 projects, 52 articles, 15 press releases, 11 brand partnerships, plus FAQ, about and investor pages — full page text and JSON-LD rendered as prose |
| **Wasalt** | Public CDN sitemaps (`cdn.wasalt.sa`) | 8,630 of 8,634 category URLs parsed across 160 cities; 45,489 for-sale and 14,509 for-rent listing records with type, size, bedrooms, orientation and location |

Both collectors respect `robots.txt` and use no anti-bot circumvention. The
scraper writes per-source shards and merges them, so a single source can be
refreshed without re-collecting the other.

### Serving

FastAPI backend with Pydantic-validated requests, serving a dependency-free
vanilla-JS frontend — no build step, no bundler.

```
POST /api/chat             question, history, source filter, persona
GET  /api/health           liveness + index status
GET  /api/suggestions      starter questions
POST /api/admin/refresh    token-protected corpus rebuild
```

---

## By the numbers

| | |
|---|---|
| Documents indexed | **2,091** — 1,961 Wasalt + 130 DarGlobal → 2,508 chunks |
| Wasalt sitemap coverage | **8,630 / 8,634** category URLs (99.95%), 160 cities |
| Wasalt listings collected | 45,489 for sale · 14,509 for rent |
| Tests | **58** passing — parsers, chunking, retrieval, pipeline, API, LLM client |
| Runtime footprint | ~350–450 MB RSS, fits a 512 MB free instance |
| Image weight saved | ~1.5 GB, by choosing ONNX `fastembed` over torch |

---

## Architecture

```
┌─ scraper/ ──────────────────────────────┐   ┌─ data/ ─────────────┐
│ darglobal.py  headless-Chromium crawl   │──▶│ corpus.jsonl        │
│ wasalt.py     public CDN sitemap reader │   │ corpus_stats.json   │
└─────────────────────────────────────────┘   └──────────┬──────────┘
                                                         ▼  python -m rag.index
┌─ rag/ ─────────────────────────────────────────────────────────────┐
│ chunking.py  1200-char chunks, 150 overlap, metadata preserved     │
│ index.py     fastembed MiniLM-L6 (ONNX) + BM25, RRF hybrid search  │
│ llm.py       OpenRouter client, multi-model fallback, degradation  │
│ pipeline.py  retrieve → cited context → generate → source list     │
└───────────────────────────────┬────────────────────────────────────┘
                                ▼
┌─ server/main.py  FastAPI ─────────────────────────────┐
│ /api/chat · /api/health · /api/suggestions            │
│ /api/admin/refresh (token)   serves web/ UI           │
└───────────────────────────────────────────────────────┘
```

**Stack:** Python 3.12 · FastAPI · fastembed (ONNX) · rank-bm25 · Playwright ·
OpenRouter · vanilla-JS frontend.

A deliberate swap from a sentence-transformers / FAISS / React stack: the same
capability at roughly 1.5 GB less image weight and no frontend build step,
which is what makes a genuinely free deployment tier possible.

---

## Quickstart

```bash
pip install -r requirements.txt
python -m playwright install chromium     # scraper only
cp .env.example .env                      # add OPENROUTER_API_KEY

python -m scraper.run                     # build data/corpus.jsonl (~5 min)
python -m rag.index                       # build embeddings + BM25 index
uvicorn server.main:app --port 8000       # → http://localhost:8000
```

The corpus and stats are committed, so you can skip the scraper and index the
shipped data directly.

### Docker

```bash
docker compose up --build                 # → http://localhost:8000
```

The image bakes both the embedding model and the knowledge index at build time,
so the container never starts empty and needs no persistent disk.

---

## Deployment

Deployed on Render's free Docker tier via the included `render.yaml` blueprint:

1. Push the repo to GitHub.
2. Render dashboard → **New → Blueprint** → select the repo. `render.yaml`
   configures a Docker web service with a `/api/health` health check.
3. Add `OPENROUTER_API_KEY` under Environment → Add Secret, and set
   `APP_PUBLIC_URL` to the assigned `https://<name>.onrender.com`.
4. The first build takes ~5–8 minutes; the URL goes public as soon as the
   health check passes.

The Dockerfile is also Hugging Face Spaces-compatible — non-root uid 1000,
port 7860, caches inside `$HOME` — and runs anywhere else Docker does.

### Refreshing the knowledge base

```bash
python -m scraper.run && python -m rag.index          # locally
curl -X POST https://<host>/api/admin/refresh \
     -H "X-Admin-Token: <token>"                      # remotely
```

---

## Configuration

| Variable | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | Enables generated answers |
| `OPENROUTER_MODEL` | Default `nvidia/nemotron-3-ultra-550b-a55b:free`; falls back across 7 further verified free models |
| `OPENROUTER_BASE_URL` | Default `https://openrouter.ai/api/v1` |
| `APP_PUBLIC_URL` | Sent as HTTP-Referer to OpenRouter |
| `ADMIN_TOKEN` | Enables `POST /api/admin/refresh` |

---

## Tests

```bash
python -m pytest tests/        # 58 tests
python scripts/qa.py           # 10 realistic questions through the full pipeline
python scripts/probe_models.py # which OpenRouter free models are answering today
```

The suite covers both scraper parsers, chunking, hybrid retrieval and its
per-URL capping, the pipeline's persona handling and off-topic refusal, every
API route and its validation, and the LLM client's fallback behaviour.

Beyond unit tests, the running server was checked end to end: health, chat,
source filtering (a Wasalt-only query returns Wasalt URLs exclusively),
conversational follow-up resolution, off-topic refusal, static asset serving and
admin-token auth. The interface was driven in a headless browser to confirm that
citations render as clickable chips, that theme switching and persona switching
persist, that dictation and speech playback behave, and that there are no
console errors or horizontal overflow at 390 px.

---

## Project layout

```
scraper/   darglobal.py · wasalt.py · run.py
rag/       chunking.py · index.py · llm.py · pipeline.py
server/    main.py — FastAPI app and routes
web/       index.html · style.css · chat.js
tests/     58 tests across parsers, retrieval, pipeline, API, LLM
scripts/   qa.py · probe_models.py
data/      corpus.jsonl · corpus_stats.json
```

---

An independent project built for research and education. Not affiliated with or
endorsed by DarGlobal or Wasalt; details are best confirmed on the linked source
pages.
