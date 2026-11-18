"""Probe every OpenRouter free model: which actually return usable content?"""
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
KEY = os.environ["OPENROUTER_API_KEY"]
BASE = "https://openrouter.ai/api/v1"

models = [m for m in requests.get(f"{BASE}/models", timeout=30).json()["data"]
          if m["id"].endswith(":free")]
models.sort(key=lambda m: -(m.get("context_length") or 0))
print(f"{len(models)} free models\n")

PROMPT = [{"role": "system", "content": "Answer only from the source. Cite like [1]."},
          {"role": "user", "content": "SOURCES:\n[1] Marea is a DarGlobal "
                                      "development in Costa del Sol, Spain, with "
                                      "interiors by Missoni.\n\nQUESTION: Where is Marea?"}]

ok = []
for m in models:
    mid = m["id"]
    t0 = time.time()
    try:
        r = requests.post(f"{BASE}/chat/completions",
                          headers={"Authorization": f"Bearer {KEY}",
                                   "Content-Type": "application/json"},
                          json={"model": mid, "messages": PROMPT,
                                "max_tokens": 120, "temperature": 0.2},
                          timeout=75)
    except requests.RequestException as e:
        print(f"  {mid:52} NET  {type(e).__name__}")
        continue
    dt = time.time() - t0
    if r.status_code != 200:
        try:
            msg = r.json().get("error", {}).get("message", "")[:45]
        except Exception:
            msg = r.text[:45]
        print(f"  {mid:52} {r.status_code}  {msg}")
        continue
    body = r.json()
    ch = (body.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    content = msg.get("content")
    reasoning = msg.get("reasoning")
    if isinstance(content, str) and content.strip():
        cited = "[1]" in content
        print(f"  {mid:52} OK   {dt:5.1f}s cite={cited} {content.strip()[:60]!r}")
        ok.append((mid, dt, cited))
    else:
        print(f"  {mid:52} EMPTY content={content!r} "
              f"reasoning={'yes' if reasoning else 'no'} finish={ch.get('finish_reason')}")

print("\nWORKING, fastest first:")
for mid, dt, cited in sorted(ok, key=lambda x: x[1]):
    print(f"  {dt:5.1f}s  cite={cited}  {mid}")
