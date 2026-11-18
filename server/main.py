"""FastAPI backend serving the chat API and the web UI.

Run:  uvicorn server.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

app = FastAPI(title="DAR & Wasalt Property Assistant", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

_bot = None
_bot_lock = threading.Lock()
_refresh_state = {"running": False, "last": None}


def bot():
    global _bot
    with _bot_lock:
        if _bot is None:
            from rag.pipeline import Chatbot
            _bot = Chatbot()
        return _bot


class ChatTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)
    source: str = Field(default="both", pattern="^(both|darglobal|wasalt)$")
    persona: str = Field(default="maria", pattern="^(maria|ben)$")


@app.get("/api/health")
def health():
    stats_file = ROOT / "data" / "corpus_stats.json"
    stats = json.loads(stats_file.read_text()) if stats_file.exists() else {}
    from rag.llm import llm_mode
    return {"status": "ok", "llm_mode": llm_mode(),
            "model": os.environ.get("OPENROUTER_MODEL", "auto"),
            "corpus": stats, "refresh": _refresh_state}


@app.get("/api/suggestions")
def suggestions():
    return {"suggestions": [
        "What projects does DarGlobal currently have?",
        "Tell me about DarGlobal's Trump-branded developments",
        "Which cities does Wasalt cover in Saudi Arabia?",
        "What villas are for sale on Wasalt?",
        "Which luxury brands does DarGlobal partner with?",
        "What properties does Wasalt list in Riyadh?",
        "What is DarGlobal's latest financial performance?",
        "Compare DarGlobal and Wasalt — what does each offer?",
    ]}


@app.post("/api/chat")
def chat(req: ChatRequest):
    try:
        result = bot().answer(req.message,
                              [t.model_dump() for t in req.history],
                              source=req.source, persona=req.persona)
    except FileNotFoundError:
        raise HTTPException(503, "Knowledge index not built yet. "
                                 "Run: python -m scraper.run && python -m rag.index")
    return result


def _browser_available() -> bool:
    """Playwright browsers ship only in dev images, not the slim runtime one."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True
    except Exception:  # noqa: BLE001
        return False


@app.post("/api/admin/refresh")
def refresh(x_admin_token: str = Header(default="")):
    expected = os.environ.get("ADMIN_TOKEN", "")
    if not expected or x_admin_token != expected:
        raise HTTPException(401, "bad or missing X-Admin-Token")
    if _refresh_state["running"]:
        return {"status": "already running"}

    # Wasalt needs only HTTP sitemap reads; DarGlobal needs a real browser.
    with_darglobal = _browser_available()
    args = ["-m", "scraper.run"] + ([] if with_darglobal else ["--skip-darglobal"])

    def job():
        global _bot
        import subprocess
        import sys
        _refresh_state["running"] = True
        try:
            subprocess.run([sys.executable, *args], cwd=ROOT, check=True,
                           timeout=3600)
            subprocess.run([sys.executable, "-m", "rag.index"], cwd=ROOT,
                           check=True, timeout=3600)
            with _bot_lock:
                _bot = None  # reload on next request
            _refresh_state["last"] = "ok"
        except Exception as e:  # noqa: BLE001
            _refresh_state["last"] = f"failed: {e}"
        finally:
            _refresh_state["running"] = False

    threading.Thread(target=job, daemon=True).start()
    return {"status": "started", "sources": "both" if with_darglobal else
            "wasalt only (no browser in this image; DarGlobal shard reused)"}


@app.get("/")
def home():
    return FileResponse(ROOT / "web" / "index.html")


app.mount("/", StaticFiles(directory=ROOT / "web"), name="static")
