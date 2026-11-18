"""DarGlobal content crawler (headless Chromium via Playwright).

darglobal.co.uk is the official site of DarGlobal PLC, the London-listed
luxury developer. (NOTE: darglobal.com now redirects to an unrelated company,
dar.io — we crawl the .co.uk site.) The site is a Next.js app served through
Imperva, which serves real browsers normally; we crawl politely:
  - BFS from the homepage over same-domain links
  - 1 request/second, configurable page cap
  - robots.txt respected (it disallows /sitemap_index.xml and tracking-param
    URLs; we fetch neither)
Extraction: page title/meta + JSON-LD + readable body text with nav/footer
stripped, classified by URL path.
"""
from __future__ import annotations

import json
import re
import time
from collections import deque
from datetime import date
from urllib.parse import urlparse

BASE = "https://darglobal.co.uk"
SKIP_PAT = re.compile(
    r"(\.pdf$|\.jpg$|\.png$|/pay-online|/get-in-touch|utm_|sfmc_|/landing-page/|/lp/)", re.I
)
TYPE_BY_SEG = {
    "projects": "project", "press": "press-release", "blog": "article",
    "insights": "article", "partners": "brand-partnership", "faq": "faq",
    "about": "about", "investor": "investor-info", "commercial": "project",
    "hospitality": "project",
}
# Individual developments live at the site root (/marea, /les-vagues) or under
# these collection prefixes — everything root-level that is NOT one of these
# known static pages is a project page.
STATIC_ROOT = {
    "", "about", "faq", "press", "blog", "insights", "investor", "tokenization",
    "why-invest", "terms-of-uses", "terms-conditions", "terms-and-conditions",
    "privacy-policy", "exclusive-membership", "pay-online", "get-in-touch",
    "partners", "sitemap", "cookie-policy", "careers", "contact",
    "luxury-golf-communities", "media", "news",
}
PROJECT_PREFIX = {"one-of-one", "rayana", "amaya", "projects", "aida"}

STRIP_SELECTORS = ["nav", "header", "footer", "script", "style", "noscript",
                   "[class*=cookie]", "[id*=cookie]", "form"]


def classify(url: str) -> str:
    parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
    seg = parts[0] if parts else ""
    if seg in TYPE_BY_SEG:
        return TYPE_BY_SEG[seg]
    if seg in PROJECT_PREFIX:
        return "project"
    if seg not in STATIC_ROOT:   # root-level development page
        return "project"
    return "page"


def extract(page) -> dict:
    """Pull title, meta description, JSON-LD and cleaned body text."""
    meta = page.evaluate(
        """() => {
            const d = document;
            const md = d.querySelector('meta[name="description"]');
            const lds = [...d.querySelectorAll('script[type="application/ld+json"]')]
                        .map(s => s.textContent).slice(0, 4);
            const hs = [...d.querySelectorAll('h1, h2')]
                       .map(h => (h.innerText || '').trim())
                       .filter(t => t && t.length < 90).slice(0, 6);
            return {title: d.title, desc: md ? md.content : '', lds, heads: hs};
        }"""
    )
    for sel in STRIP_SELECTORS:
        try:
            page.evaluate(
                "sel => document.querySelectorAll(sel).forEach(e => e.remove())", sel
            )
        except Exception:
            pass
    body = page.inner_text("body", timeout=10000)
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    ld_bits = []
    for raw in meta["lds"]:
        try:
            ld = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for obj in (ld if isinstance(ld, list) else [ld]):
            if not isinstance(obj, dict):
                continue
            # Render as readable prose: raw JSON in the context window reads
            # badly in answers and wastes tokens.
            label = str(obj.get("name") or obj.get("headline") or "").strip()
            desc = str(obj.get("description") or "").strip()
            extra = []
            if addr := obj.get("address"):
                if isinstance(addr, dict):
                    addr = ", ".join(str(v) for k, v in addr.items()
                                     if k != "@type" and isinstance(v, str))
                extra.append(f"address: {addr}")
            if published := obj.get("datePublished"):
                extra.append(f"published {published}")
            line = " — ".join(p for p in (label, desc) if p)
            if extra:
                line = f"{line} ({'; '.join(extra)})" if line else "; ".join(extra)
            if line:
                ld_bits.append(line[:400])
    return {"title": meta["title"], "description": meta["desc"],
            "jsonld": ld_bits, "body": body, "heads": meta["heads"]}


# "DUBAI, UAE" / "BENAHAVÍS, SPAIN" / "AL MARJAN ISLAND, RAK, UAE"
LOCATION_RE = re.compile(
    r"\b([A-Z][A-Z\sÁÉÍÓÚÀÈÌÒÙÑÇ'’-]{2,30},\s*(?:[A-Z]{2,4},\s*)?"
    r"(?:UAE|KSA|SAUDI ARABIA|SPAIN|QATAR|OMAN|UNITED ARAB EMIRATES|"
    r"UNITED KINGDOM|UK|MOROCCO|GREECE))\b"
)
COUNTRIES = ("UAE", "United Arab Emirates", "Saudi Arabia", "Qatar", "Oman",
             "Spain", "United Kingdom", "Morocco", "Greece")


def guess_name(url: str, title: str, heads: list[str]) -> str:
    """Prefer a real project name over the SEO title."""
    slug = urlparse(url).path.strip("/").split("/")[-1]
    slug_words = {w for w in re.split(r"[-_]", slug.lower()) if len(w) > 2}
    # a heading that echoes the slug is almost certainly the project name
    for h in heads:
        hw = {w for w in re.split(r"\W+", h.lower()) if len(w) > 2}
        if slug_words & hw:
            return h.strip()
    first = title.split("|")[0].strip()
    # generic SEO titles ("Buy Branded Homes") don't match the slug — fall back
    if slug_words & {w for w in re.split(r"\W+", first.lower()) if len(w) > 2}:
        return first
    return heads[0].strip() if heads else first


def guess_location(text: str) -> str:
    if m := LOCATION_RE.search(text):
        return m.group(1).title().replace("Uae", "UAE").replace("Uk", "UK")
    for c in COUNTRIES:
        if re.search(rf"\b{re.escape(c)}\b", text, re.I):
            return c
    return ""


def crawl(max_pages: int = 120, delay_s: float = 1.0, headless: bool = True) -> list[dict]:
    from playwright.sync_api import sync_playwright

    today = date.today().isoformat()
    seen: set[str] = set()
    queue: deque[str] = deque([BASE + "/", BASE + "/faq", BASE + "/about",
                               BASE + "/press", BASE + "/blog", BASE + "/insights"])
    docs: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_context(locale="en-US").new_page()
        while queue and len(docs) < max_pages:
            url = queue.popleft().split("#")[0].split("?")[0].rstrip("/") or BASE
            if url in seen or SKIP_PAT.search(url):
                continue
            if not urlparse(url).netloc.endswith("darglobal.co.uk"):
                continue
            if urlparse(url).netloc.startswith(("cdn.", "agents.")):
                continue
            seen.add(url)
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=40000)
                page.wait_for_timeout(1800)  # let Next.js hydrate
                if not resp or resp.status >= 400:
                    print(f"  skip {url} (status {resp.status if resp else '?'})")
                    continue
                # enqueue new internal links BEFORE stripping nav
                for href in page.eval_on_selector_all(
                        "a[href]", "els => els.map(e => e.href)"):
                    h = href.split("#")[0].split("?")[0].rstrip("/")
                    if h and h not in seen and not SKIP_PAT.search(h):
                        queue.append(h)
                ex = extract(page)
            except Exception as e:
                print(f"  error {url}: {type(e).__name__}: {str(e)[:120]}")
                continue
            if len(ex["body"]) < 200:  # empty/JS-failed page
                continue
            ctype = classify(url)
            name = guess_name(url, ex["title"], ex["heads"]) if ctype == "project" else ""
            location = guess_location(ex["body"][:3000]) if ctype == "project" else ""
            # lead with name/location so retrieval and citations read well
            header = " — ".join(p for p in (name, location) if p)
            text = (f"{header}\n(DarGlobal development page: {url})\n\n"
                    if header else "") + ex["body"]
            if ex["jsonld"]:
                text += "\n\n" + "\n".join(ex["jsonld"])[:1500]
            docs.append({
                "source": "darglobal", "url": url,
                "title": name or ex["title"],
                "content_type": ctype, "property_name": name,
                "location": location, "language": "en", "date_scraped": today,
                "description": ex["description"], "text": text[:20000],
            })
            print(f"  [{len(docs):3}] {ctype:17} {name or ex['title'][:40]:42} {url}")
            time.sleep(delay_s)
        browser.close()
    return docs
