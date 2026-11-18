"""Wasalt knowledge collection — from their openly served CDN sitemaps ONLY.

wasalt.sa HTML pages sit behind a Cloudflare challenge for automated clients,
and we do not bypass anti-bot protections. Their robots.txt, however, openly
publishes rich sitemaps on cdn.wasalt.sa (CloudFront, no challenge):

  product_sitemap_en_sa   ~40k sale-listing URLs; slugs encode type/size/attrs
  rental_pdp_sitemap_en_sa rental-listing URLs
  category_sitemap_en_sa  ~8.6k "properties-for-sale-in-<city>-<district>" pages
  static_sitemap_en_sa    informational /s/ pages

From these we build real, citable records: every fact we store (listing title,
type, deal, size, city/district, URL) comes verbatim from Wasalt's published
sitemap data. Page-level details (price, amenities, photos) are NOT collected;
the chatbot is told to say so.
"""
from __future__ import annotations

import gzip
import io
import re
import time
from collections import defaultdict
from datetime import date

import requests

CDN = "https://cdn.wasalt.sa/sitemap/"
SITEMAPS = {
    "sale": "product_sitemap_en_sa.xml.gz",
    "rent": "rental_pdp_sitemap_en_sa.xml.gz",
    "category": "category_sitemap_en_sa.xml.gz",
    "static": "static_sitemap_en_sa.xml.gz",
}
UA = {"User-Agent": "DARWasaltResearchBot/0.1 (public sitemap reader)"}

LOC_RE = re.compile(r"<loc>\s*([^<]+?)\s*</loc>")

# slug vocabulary -> property type
TYPES = [
    "villa", "apartment", "land", "building", "floor", "duplex", "townhouse",
    "farm", "istraha", "rest-house", "resthouse", "chalet", "office", "shop",
    "showroom", "warehouse", "studio", "room", "palace", "compound",
]

# Category slugs are "<plural-type>-for-<deal>-in-<location>"; map back to singular.
PLURAL_TYPE = {
    "properties": "property", "villas": "villa", "lands": "land",
    "apartments": "apartment", "buildings": "building", "floors": "floor",
    "duplexes": "duplex", "chalets": "chalet", "showrooms": "showroom",
    "farms": "farm", "rest-houses": "rest house", "offices": "office",
    "shops": "shop", "warehouses": "warehouse", "towers": "tower",
    "townhouses": "townhouse", "studios": "studio", "rooms": "room",
    "furnished-apartments": "furnished apartment",
    "furnished-villas": "furnished villa", "commercial-lands": "commercial land",
    "residential-lands": "residential land", "commercial-buildings":
    "commercial building", "residential-buildings": "residential building",
    "istrahas": "istraha", "camps": "camp", "stations": "station",
    "exhibitions": "exhibition", "hangars": "hangar", "factories": "factory",
    "commercial-properties": "commercial property",
    "residential-properties": "residential property",
}
# Arabic name articles/particles: a location slug starting with one of these
# carries the city name over 2+ tokens (al-khobar, hafar-al-batin, wadi-ad-dawasir).
ARTICLES = {"al", "ad", "ar", "as", "az", "at", "an", "ash", "ath", "umm",
            "abu", "bani", "ain", "wadi", "ras", "hafar", "khamis", "bish",
            "dhahrat", "jubbah", "tarf"}
# Big cities are sub-divided by compass zone: east-riyadh-al-marjan.
ZONES = {"east", "west", "north", "south", "central"}


def fetch_sitemap(name: str, timeout: int = 60, retries: int = 4) -> list[str]:
    """Return all <loc> URLs of one sitemap (CDN serves them challenge-free).

    Retries on transient network/DNS failures — the CloudFront host
    intermittently fails to resolve on some networks.
    """
    last: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(CDN + SITEMAPS[name], headers=UA, timeout=timeout)
            resp.raise_for_status()
            raw = resp.content
            if raw[:2] == b"\x1f\x8b":  # sometimes gzipped, sometimes not
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            return LOC_RE.findall(raw.decode("utf-8", "replace"))
        except requests.RequestException as e:
            last = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt * 2)  # 2, 4, 8s
    raise last  # type: ignore[misc]


def split_location(slug: str) -> tuple[str, str, str]:
    """'east-riyadh-al-marjan' -> ('east', 'riyadh', 'al marjan').

    City names run to the end of any leading article chain, so
    'hafar-al-batin-x' -> city 'hafar al batin', district 'x'.
    """
    parts = [p for p in slug.lower().split("-") if p]
    zone = ""
    if parts and parts[0] in ZONES:
        zone, parts = parts[0], parts[1:]
    n = 1
    while n < len(parts) and parts[n - 1] in ARTICLES:
        n += 1
    return zone, " ".join(parts[:n]), " ".join(parts[n:])


def parse_listing(url: str) -> dict | None:
    """Parse a product URL slug into a structured record.

    e.g. /en/property/sale/villa-333-sqm-facing-east-on-20m-width-street-5841671
    """
    m = re.search(r"/en/property/(sale|rent)/([a-z0-9-]+?)-(\d{5,})/?$", url)
    if not m:
        return None
    deal, slug, lid = m.groups()
    title = slug.replace("-", " ")
    rec = {"deal": deal, "id": lid, "title": title, "url": url}
    for t in TYPES:
        if slug.startswith(t.replace(" ", "-")) or f"-{t}-" in f"-{slug}-":
            rec["type"] = t
            break
    if m2 := re.search(r"(\d+)-sqm", slug):
        rec["sqm"] = int(m2.group(1))
    if m2 := re.search(r"(\d+)-bedrooms?", slug):
        rec["bedrooms"] = int(m2.group(1))
    if m2 := re.search(r"facing-([a-z]+)", slug):
        rec["facing"] = m2.group(1)
    if m2 := re.search(r"(\d+)m-width-street", slug):
        rec["street_width_m"] = int(m2.group(1))
    return rec


CATEGORY_RE = re.compile(
    r"/en/(?:(\d+)-bedroom-)?([a-z]+(?:-[a-z]+)?)-for-(sale|rent)-in-([A-Za-z0-9-]+?)/?$"
)


def parse_category(url: str) -> dict | None:
    """Parse a browse page, e.g.
    /en/properties-for-sale-in-taif-al-malaab
    /en/rest-houses-for-sale-in-buraidah-jbara
    /en/villas-for-sale-in-east-riyadh-al-marjan
    /en/3-bedroom-apartments-for-rent-in-jeddah-al-hamra
    """
    m = CATEGORY_RE.search(url)
    if not m:
        return None
    beds, plural, deal, loc = m.groups()
    ptype = PLURAL_TYPE.get(plural)
    if ptype is None:
        return None
    zone, city, district = split_location(loc)
    if not city:
        return None
    return {"deal": deal, "ptype": ptype, "zone": zone, "city": city,
            "district": district, "url": url,
            "bedrooms": int(beds) if beds else None}


def build_documents(max_listing_docs: int = 1500) -> list[dict]:
    """Turn sitemap data into corpus documents with metadata."""
    today = date.today().isoformat()
    docs: list[dict] = []

    def doc(**kw) -> dict:
        base = {"source": "wasalt", "date_scraped": today, "language": "en"}
        base.update(kw)
        return base

    listings: list[dict] = []
    for deal_map in ("sale", "rent"):
        try:
            urls = fetch_sitemap(deal_map)
        except requests.RequestException as e:
            print(f"  wasalt {deal_map} sitemap failed: {e}")
            continue
        parsed = [r for r in (parse_listing(u) for u in urls) if r]
        print(f"  wasalt {deal_map}: {len(urls)} urls -> {len(parsed)} parsed records")
        listings.extend(parsed)
        time.sleep(1)

    cats = []
    try:
        cats = [c for c in (parse_category(u) for u in fetch_sitemap("category")) if c]
        print(f"  wasalt categories: {len(cats)} city/district pages")
    except requests.RequestException as e:
        print(f"  wasalt category sitemap failed: {e}")

    # ---- aggregate: one doc per city ----
    by_city: dict[str, list[dict]] = defaultdict(list)
    for c in cats:
        by_city[c["city"]].append(c)
    type_counts: dict[str, int] = defaultdict(int)
    for r in listings:
        type_counts[r.get("type", "other")] += 1

    for city, rows in sorted(by_city.items(), key=lambda kv: -len(kv[1])):
        districts = sorted({r["district"] for r in rows if r["district"]})
        zones = sorted({r["zone"] for r in rows if r["zone"]})
        ptypes = sorted({r["ptype"] for r in rows if r["ptype"] != "property"})
        sale = {r["district"] for r in rows if r["deal"] == "sale"}
        rent = {r["district"] for r in rows if r["deal"] == "rent"}
        # a canonical browse URL for this city (prefer the generic sale page)
        canon = next((r["url"] for r in rows
                      if r["ptype"] == "property" and r["deal"] == "sale"), rows[0]["url"])
        text = (
            f"Wasalt (wasalt.sa) is a Saudi Arabian property marketplace. "
            + (f"In {city.title()}, Wasalt has browse pages covering "
               f"{len(districts)} districts/areas"
               + (f", organised into {len(zones)} zones ({', '.join(zones)})"
                  if zones else "")
               if districts else
               f"Wasalt covers {city.title()} as a whole, without separate "
               "district pages")
            + ". "
            + (f"Property types listed in {city.title()}: {', '.join(ptypes)}. "
               if ptypes else "")
            + (f"{len(sale)} areas have properties for sale"
               + (f" and {len(rent)} areas have rentals. " if rent else ". ")
               + f"Districts in {city.title()} include: "
               + ", ".join(d.title() for d in districts[:60])
               + ("..." if len(districts) > 60 else "") + ". "
               if districts else
               f"Properties are listed for {' and '.join(sorted({r['deal'] for r in rows}))}. ")
            + f"Browse: {canon}"
        )
        docs.append(doc(
            url=canon, title=f"Wasalt properties in {city.title()}",
            content_type="location-directory", location=city.title(), text=text,
        ))

    # ---- one doc per (city, bedroom count) for "3 bedroom apartments" queries ----
    by_beds: dict[tuple[str, int, str], list[dict]] = defaultdict(list)
    for c in cats:
        if c.get("bedrooms"):
            by_beds[(c["city"], c["bedrooms"], c["ptype"])].append(c)
    for (city, beds, ptype), rows in sorted(by_beds.items()):
        districts = sorted({r["district"] for r in rows if r["district"]})
        deals = sorted({r["deal"] for r in rows})
        docs.append(doc(
            url=rows[0]["url"],
            title=f"Wasalt: {beds}-bedroom {ptype}s in {city.title()}",
            content_type="bedroom-directory", location=city.title(),
            text=(
                f"Wasalt has {beds}-bedroom {ptype}s for "
                f"{' and '.join(deals)} in {city.title()}, Saudi Arabia"
                + (f", across {len(districts)} areas: "
                   + ", ".join(d.title() for d in districts[:40])
                   if districts else "")
                + f". Browse {beds}-bedroom {ptype}s in {city.title()}: {rows[0]['url']}"
            ),
        ))

    # ---- one doc per (city, property type) so type questions retrieve well ----
    by_city_type: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for c in cats:
        if c["ptype"] != "property" and not c.get("bedrooms"):
            by_city_type[(c["city"], c["ptype"])].append(c)
    for (city, ptype), rows in by_city_type.items():
        if len(rows) < 2:
            continue
        districts = sorted({r["district"] for r in rows if r["district"]})
        deals = sorted({r["deal"] for r in rows})
        docs.append(doc(
            url=rows[0]["url"],
            title=f"Wasalt: {ptype}s in {city.title()}",
            content_type="type-location-directory", location=city.title(),
            text=(
                f"Wasalt lists {ptype}s for {' and '.join(deals)} in "
                f"{city.title()}, Saudi Arabia, across {len(districts)} areas"
                + (": " + ", ".join(d.title() for d in districts[:40])
                   if districts else "")
                + f". Browse {ptype}s in {city.title()}: {rows[0]['url']}"
            ),
        ))

    # ---- overview doc ----
    n_sale = sum(1 for r in listings if r["deal"] == "sale")
    n_rent = len(listings) - n_sale
    tc = ", ".join(f"{k}: {v}" for k, v in sorted(type_counts.items(), key=lambda kv: -kv[1]))
    top_cities = ", ".join(
        f"{c.title()} ({len({r['district'] for r in rows})} areas)"
        for c, rows in sorted(by_city.items(), key=lambda kv: -len(kv[1]))[:15])
    docs.append(doc(
        url="https://wasalt.sa/en/", title="Wasalt marketplace overview",
        content_type="overview", location="Saudi Arabia",
        text=(
            f"Wasalt (wasalt.sa) is a Saudi property marketplace covering "
            f"{len(by_city)} cities. As of {today}, its public sitemaps list "
            f"{n_sale} properties for sale and {n_rent} for rent. "
            f"Cities with the most areas covered: {top_cities}. "
            f"Listing counts by property type: {tc}. "
            "NOTE ON DATA DEPTH: Wasalt page content (prices, amenities, photos) "
            "is protected by a bot challenge and was not collected; this knowledge "
            "base holds listing titles, types, sizes, locations and direct URLs "
            "from Wasalt's public sitemaps. For prices and amenities the user "
            "should open the cited listing URL."
        ),
    ))

    # ---- individual listing docs (sampled evenly) ----
    step = max(1, len(listings) // max_listing_docs)
    for r in listings[::step][:max_listing_docs]:
        bits = [r["title"].title()]
        if "sqm" in r:
            bits.append(f"area {r['sqm']} sqm")
        if "bedrooms" in r:
            bits.append(f"{r['bedrooms']} bedrooms")
        if "facing" in r:
            bits.append(f"facing {r['facing']}")
        if "street_width_m" in r:
            bits.append(f"on a {r['street_width_m']}m wide street")
        text = (
            f"Wasalt listing ({r['deal']}): " + ", ".join(bits)
            + f". Listing ID {r['id']}. Details and price: {r['url']}"
        )
        docs.append(doc(
            url=r["url"], title=r["title"].title(),
            content_type=f"listing-{r['deal']}",
            property_name=r["title"].title(),
            location=r.get("city", ""), text=text,
        ))

    # ---- static info pages (titles + urls only) ----
    try:
        for u in fetch_sitemap("static"):
            slug = u.rstrip("/").rsplit("/", 1)[-1].replace("-", " ")
            docs.append(doc(
                url=u, title=f"Wasalt: {slug}", content_type="info-page",
                text=f"Wasalt informational page about {slug}: {u}",
            ))
    except requests.RequestException:
        pass

    return docs
