# Testing Results

All figures below were produced by running the code, not estimated.
Date: 2026-11-18. Reproduce with the commands shown.

## 1. Automated test suite

```
$ python -m pytest tests/ -q
46 passed in 2.93s
```

| File | Covers |
|---|---|
| `test_wasalt_parse.py` (12) | listing/category slug parsing, Arabic-article city splitting, compass zones, hyphenated and bedroom-prefixed types, mixed-case slugs, unknown-type rejection |
| `test_darglobal_parse.py` (11) | page classification, project-name recovery from headings, location extraction |
| `test_chunking.py` (4) | chunk sizing, overlap, no content loss, metadata preservation |
| `test_retrieval.py` (6) | per-URL chunk cap (regression), source filtering, `k` limit, metadata/scores |
| `test_pipeline.py` (7) | off-topic refusal, borderline floor, citations present, demo-mode labelling, LLM-failure degradation, follow-up context |
| `test_api.py` (6) | health, chat round-trip, request validation (422), admin auth (401), suggestions |

## 2. Scraper verification (real sites)

**Wasalt** — parsed from the CDN sitemaps listed in their `robots.txt`:

```
8,630 / 8,634 category URLs parsed (99.95%)
160 cities;  45,489 properties for sale;  14,509 for rent
```
The 4 unparsed URLs are malformed entries in the sitemap itself.

Before the parser fix, only 1,699 URLs (19.7%) parsed, and Riyadh resolved to
110 pages instead of its true 1,604 — the compass-zone slugs
(`east-riyadh-…`) were being read as separate cities.

**DarGlobal** — 130 pages crawled at 1 req/s, robots-respecting:

| Type | Count |
|---|---|
| project | 44 |
| article (blog + insights) | 52 |
| press-release | 15 |
| brand-partnership | 11 |
| other (faq, about, investor, legal) | 8 |

## 3. Retrieval quality

Dense cosine of the top hit, measured across 13 queries:

| Query | Top score |
|---|---|
| "villas for sale in Riyadh" | 0.777 |
| "Trump International Hotel Dubai" | 0.761 |
| "3 bedroom apartments Jeddah" | 0.715 |
| "DarGlobal financial results" | 0.663 |
| "Lamborghini branded residences" | 0.637 |
| "which cities does Wasalt cover" | 0.593 |
| "What projects does DarGlobal have?" | 0.552 |
| "Aston Martin partnership" | 0.497 |
| — *off-topic below* — | |
| "what is the capital of Mongolia" | 0.248 |
| "how do I bake sourdough bread" | 0.126 |
| "best vaccine for measles" | 0.095 |
| "Who won the cricket world cup?" | 0.082 |
| "python async await tutorial" | 0.057 |

On-topic 0.497–0.777 vs off-topic 0.057–0.248 — a clean gap, so
`RELEVANCE_FLOOR = 0.35` separates them with margin on both sides.
Verified live: all 5 off-topic queries refused, all 5 on-topic answered with
8 sources each.

## 4. End-to-end API (running server)

```
GET  /api/health                      200, 2,091 docs reported
POST /api/chat  (darglobal filter)    200, 8 sources, all darglobal URLs
POST /api/chat  (wasalt filter)       200, all wasalt URLs
POST /api/chat  (off-topic)           200, off_topic=true, 0 sources
POST /api/chat  (follow-up history)   200, "its location" resolved to
                                      darglobal.co.uk/marea
POST /api/chat  (empty message)       422 validation error
POST /api/chat  (bad source value)    422 validation error
POST /api/admin/refresh (no token)    401
POST /api/admin/refresh (bad token)   401
GET  / , /style.css , /chat.js        200
```

## 5. Frontend (headless browser)

Driven with Playwright at 1280×900 (light + dark) and 390×844 (mobile):

- 8 suggestion chips render; status line reports the live document count
- a real question returns an answer with **8 clickable citation chips**
- **zero console errors** in either theme
- **no horizontal overflow** at 390 px

## 6. OpenRouter model probe (live)

`python scripts/probe_models.py` sends a RAG-style prompt to **every** free
model and reports which return usable, cited text. Run 2026-11-18:

| Result | Models |
|---|---|
| ✅ answered **and** cited (8) | `nemotron-3-ultra-550b-a55b`, `nemotron-3.5-super-vl`, `particle-1`, `ling-3.2-flash`, `ernie-5.5-flash-preview`, `flint-v1.0`, `north-mini-code`, `nemotron-3-nano-omni` |
| ⚠️ HTTP 200 but `content: null` (2) | `nemotron-3.5-lightning`, `dots-3-note-preview` — reasoning models that spend the whole token budget on hidden reasoning (`finish_reason=length`) |
| ⛔ 429 rate-limited upstream (3) | `gemma-4-31b-it`, `gemma-4-26b-a4b-it`, `lfm-3-1.7b` |
| ⛔ 403 gated (1) | `inkling-2-small` |

Two findings changed the code:

1. The original default (`gemma-4-31b-it:free`) is **rate-limited on the
   shared free pool**, so the default is now `nemotron-3-ultra-550b-a55b:free`
   with the other seven verified models as fallbacks.
2. A `200` response does **not** guarantee text. The client previously
   returned `None` straight to the caller; it now treats empty content as a
   failure and moves to the next model.

Latency of the working models: 0.8 – 2.3 s.

## 7. Live generation (real answers, no mocks)

With `OPENROUTER_API_KEY` set, `python scripts/qa.py` reports
`LLM mode: openrouter`. Behaviour on the questions that matter most:

- **"What is the price of a villa in Riyadh?"** →
  *"The sources provided **do not contain any villa prices for Riyadh**."*
  It then explains that the Wasalt knowledge base holds titles, sizes and
  locations but not prices, and links the listing page. **No invented price.**
- **"Who won the cricket world cup?"** → refused by the relevance floor
  before any LLM call.
- **"Tell me about the Trump International projects"** → a structured
  answer naming Trump International Hotel & Tower Dubai, the contractor
  award and the 80-floor tower, each claim carrying a `[n]` citation.
- **"Compare what DarGlobal and Wasalt each offer"** → correctly separates
  the developer from the marketplace, citing both sources.
- **"Which cities does Wasalt cover?"** → 160 cities with a per-city area
  table, cited to the overview document.

Verified over HTTP (`POST /api/chat` → `"mode": "openrouter"`) and in the
browser: inline `[n]` markers match the citation chips beneath each answer.

## 8. Known gaps

- **Docker image not built locally.** Docker Desktop's Linux engine on this
  machine returns HTTP 500 at every API version (its `docker-desktop` WSL
  distro was stopped; starting it revived the engine only briefly). This is a
  broken local Docker install, not a Dockerfile problem, and it does not
  affect Render, which builds server-side. Verify locally after restarting
  Docker Desktop with `docker compose up --build`.
- **Free models are a shared pool.** Three of the 14 were rate-limited
  during the probe, and which ones are throttled changes through the day.
  The client falls back across seven verified models, but under load a
  request can still exhaust them; re-run `scripts/probe_models.py` to refresh
  the preference list if answers start failing.
- **Demo mode is still a real code path** (no key configured). It is
  exercised by the test suite, but it is a fallback, not the product.
