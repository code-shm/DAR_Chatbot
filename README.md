# DAR & Wasalt Property Assistant

An unofficial RAG chatbot that answers questions about **DarGlobal**
(darglobal.co.uk — London-listed luxury real-estate developer) and **Wasalt**
(wasalt.sa — Saudi property marketplace), grounded in publicly available data
with clickable source citations.

> ⚠️ Independent project for research/education. Not affiliated with, or
> endorsed by, DarGlobal or Wasalt. Always verify details on the linked
> source pages.

## Architecture

```
┌─ scraper/ ──────────────────────────────┐   ┌─ data/ ─────────────┐
│ darglobal.py  headless-Chromium crawl   │──▶│ corpus.jsonl        │
│ wasalt.py     public CDN sitemap reader │   │ corpus_stats.json   │
└─────────────────────────────────────────┘   └──────────┬──────────┘
                                                         ▼  python -m rag.index
┌─ rag/ ─────────────────────────────────────────────────────────────┐
│ chunking.py  1200-char chunks, metadata preserved                  │
│ index.py     fastembed MiniLM-L6 (ONNX) + BM25, RRF hybrid search  │
│ llm.py       OpenRouter client (free models, retries, fallbacks)   │
│ pipeline.py  retrieve → cited context → generate → source list     │
└───────────────────────────────┬────────────────────────────────────┘
                                ▼
┌─ server/main.py  FastAPI ─────────────────────────────┐
│ POST /api/chat   GET /api/health  GET /api/suggestions│
│ POST /api/admin/refresh (token)   serves web/ UI      │
└───────────────────────────────────────────────────────┘
```

**Stack:** Python 3.12 · FastAPI · fastembed (ONNX, no torch — small enough
for free-tier hosting) · rank-bm25 · Playwright · OpenRouter · vanilla-JS UI.
A deliberate swap from the suggested sentence-transformers/FAISS/React: same
capability, ~1.5 GB less image weight, no frontend build step.

## Data collection (and its honest limits)

| Source | Method | What we get |
|---|---|---|
| DarGlobal | Polite headless-browser crawl (1 req/s, page cap), BFS from homepage; robots.txt respected | Full page content: projects, press releases, blog/insights, FAQ, partners, investor pages + JSON-LD |
| Wasalt | **Sitemaps only**, from their openly served CDN (`cdn.wasalt.sa`) | ~40k+ real listing records (type, size, bedrooms, orientation, location, URL), 8.6k city/district pages, aggregated per-city documents |

Why sitemap-only for Wasalt: wasalt.sa HTML sits behind a Cloudflare
challenge for automated clients, and this project **does not bypass anti-bot
protections**. Their robots.txt welcomes bots and publishes rich sitemaps —
so that is what we use. Consequence: **no prices/amenities for Wasalt**; the
bot says so and links to the listing instead.

Note: `darglobal.com` (as in the original brief) now redirects to an
unrelated company (dar.io); the real DarGlobal site is `darglobal.co.uk`.

## Run locally

```bash
pip install -r requirements.txt
python -m playwright install chromium     # scraper only
cp .env.example .env                      # add OPENROUTER_API_KEY when you have one

python -m scraper.run                     # build data/corpus.jsonl (~5 min)
python -m rag.index                       # build embeddings + BM25 index
uvicorn server.main:app --port 8000       # open http://localhost:8000
```

Without `OPENROUTER_API_KEY` the app runs in **demo mode**: real retrieval +
citations, but answers are clearly-labeled source excerpts, not generated text.

## Docker

```bash
docker compose up --build        # http://localhost:8000
```

The image bakes the embedding model and (if `data/` is absent) builds a
Wasalt-only index at build time so it never starts empty. `./data` is mounted
as a volume for persistence.

## Refreshing the knowledge base

```bash
# locally
python -m scraper.run && python -m rag.index
# or remotely (set ADMIN_TOKEN in .env first)
curl -X POST https://<host>/api/admin/refresh -H "X-Admin-Token: <token>"
```

## Environment variables

| Var | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | enables real LLM answers (else demo mode) |
| `OPENROUTER_MODEL` | default `nvidia/nemotron-3-ultra-550b-a55b:free`; auto-falls back across 7 other verified free models |
| `OPENROUTER_BASE_URL` | default `https://openrouter.ai/api/v1` |
| `APP_PUBLIC_URL` | sent as HTTP-Referer to OpenRouter |
| `ADMIN_TOKEN` | enables `POST /api/admin/refresh` |

## Testing

```bash
python -m pytest tests/        # 46 unit + API + retrieval + pipeline tests
python scripts/qa.py           # 10 realistic questions through the full pipeline
python scripts/probe_models.py # which OpenRouter free models actually work today
```

Free models come from a shared pool, so availability shifts. `probe_models.py`
sends a RAG-style prompt to every free model and reports which answer **and**
cite correctly — run it if answers start failing, and reorder
`PREFERRED_FREE` in `rag/llm.py` from its output.

### Measured results

Collected 2026-11-18 (`data/corpus_stats.json`):

| | |
|---|---|
| Documents | **2,091** (1,961 Wasalt + 130 DarGlobal) → 2,508 chunks |
| Wasalt sitemap coverage | **8,630 / 8,634** category URLs parsed (99.95%), 160 cities |
| Wasalt listings indexed | 45,489 for sale + 14,509 for rent (1,500 sampled as individual docs) |
| DarGlobal pages | 44 projects, 52 articles, 15 press releases, 11 brand partnerships |

**Retrieval separation** (dense cosine of the top hit, measured over 13 queries):

| Query kind | Top-hit score |
|---|---|
| On-topic ("Trump International Hotel Dubai", "villas for sale in Riyadh") | 0.497 – 0.777 |
| Off-topic ("who won the cricket world cup", "how do I bake sourdough") | 0.057 – 0.248 |

The gap is wide and stable, so `RELEVANCE_FLOOR = 0.35` rejects off-topic
questions **before** reaching the LLM — no hallucination, no wasted tokens.

**End-to-end checks against the running server:** health, chat, source
filtering (Wasalt-only returns Wasalt URLs exclusively), conversational
follow-ups (resolving "what about *its* location?" to the previously
discussed development), off-topic refusal, static assets, and admin-token
auth (401 without a valid token). The UI was driven in a headless browser:
citations render as clickable chips, no console errors, no horizontal
overflow at 390 px.

## Deployment

Designed for Hugging Face Spaces (Docker Space, port 7860) or Render
(`$PORT` honored). See `Dockerfile`; `docker compose up` locally.

## Known limitations

- Wasalt: titles/types/sizes/locations/URLs only — no prices or amenities
  (bot challenge; see above). The bot states this and cites listing URLs.
- DarGlobal crawl is capped (default 130 pages) — deep blog archives may be
  partial.
- Generic questions ("what projects do you have?") often rank the FAQ page
  highly because it is phrased as questions. Answers stay correct and cited,
  but a project-listing page would sometimes be the better lead source.
- Only 1,500 of the ~60k Wasalt listings are indexed individually (an even
  sample); city/type/bedroom directory documents cover the rest in aggregate.
- Free OpenRouter models rate-limit; the client retries and falls back
  across models, but heavy traffic may still see delays.
- Knowledge is a snapshot (`date_scraped` stored per document); refresh to
  update.
