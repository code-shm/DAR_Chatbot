# Deployment

Researched 2026-11-18 against the providers' current docs. Short version:
**Render's free web service is the only confirmed $0 tier that runs a
Dockerfile.** Hugging Face Docker Spaces now require a paid plan.

| Provider | Free? | Docker | Notes |
|---|---|---|---|
| **Render** (recommended) | ✅ 750 instance-h/month | ✅ | spins down after 15 min idle, ~1 min cold start; **no persistent disk** on free |
| Hugging Face Spaces | ❌ Docker Spaces need PRO (personal) / Team (org) | ✅ | free accounts limited to Gradio/ZeroGPU Spaces |
| Fly.io | ❌ no free allowance | ✅ | ~$3.69/mo (512MB) – $6.70/mo (1GB); bills under $5 are waived on personal orgs |
| Koyeb | ❌ no free compute tier | ✅ | Pro from $29/mo |
| Google Cloud Run | ❓ unverified | ✅ | has a monthly free allowance historically; needs a billing account |

This app is built to suit a free, disk-less host: the knowledge index is
**baked into the image at build time**, so an ephemeral filesystem and
cold restarts cost nothing but the restart itself.

## Option A — Render (free, recommended)

Needs: a GitHub repo for this project + a free Render account.

1. Push this repo to GitHub.
2. Render dashboard → **New → Blueprint** → select the repo.
   `render.yaml` configures a free Docker web service with a
   `/api/health` health check.
3. Add the secret env vars (Environment → Add Secret):
   `OPENROUTER_API_KEY`, optionally `ADMIN_TOKEN`, and set
   `APP_PUBLIC_URL` to the assigned `https://<name>.onrender.com` URL.
4. First build takes ~5–8 min (installs deps, bakes the embedding model,
   builds the index). The URL is public as soon as the health check passes.

Caveats: single instance; the service sleeps after 15 min of no traffic and
takes ~1 min to wake; the filesystem resets on every restart (by design here).

## Option B — Hugging Face Spaces (needs PRO)

The Dockerfile is already Spaces-compatible (non-root uid 1000, port 7860,
caches inside `$HOME`). If you have PRO:

1. Create a **Docker** Space.
2. Prepend this frontmatter to `README.md` (Spaces reads it):
   ```yaml
   ---
   title: DAR & Wasalt Property Assistant
   emoji: 🏙️
   colorFrom: gray
   colorTo: blue
   sdk: docker
   app_port: 7860
   pinned: false
   ---
   ```
3. `git push` to `https://huggingface.co/spaces/<user>/<name>` (a write token).
4. Add `OPENROUTER_API_KEY` under Settings → Secrets (injected at runtime).

## Option C — Fly.io (~$4–7/month, always on)

```bash
fly launch --no-deploy        # generates fly.toml from the Dockerfile
fly secrets set OPENROUTER_API_KEY=...
fly deploy
```
Use `shared-cpu-1x` with 1GB RAM for headroom (512MB is tight with
onnxruntime loaded).

## Option D — anywhere you already have Docker

```bash
docker compose up --build     # http://localhost:8000
```

## Memory footprint

Roughly 350–450 MB RSS: Python + FastAPI (~80 MB), onnxruntime with
MiniLM-L6 loaded (~250 MB), embeddings matrix (~8 MB for ~5k chunks at 384
dims) and the BM25 index. It fits a 512 MB instance, with little room to
spare — prefer 1 GB where it is free to do so.

## What is NOT in the runtime image

Playwright/Chromium (~400 MB) is excluded on purpose: the DarGlobal crawl
runs on a dev machine and its output is committed as
`data/corpus_darglobal.jsonl`. In the deployed container,
`POST /api/admin/refresh` therefore refreshes **Wasalt only** (sitemaps need
no browser) and reuses the committed DarGlobal shard — the response says
which sources it refreshed. For a full re-crawl, run
`python -m scraper.run` locally and redeploy.
