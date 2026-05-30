"""SupportGoWhere corpus scraper.

Pipeline
--------
1. Discover : fetch /sitemap.xml and extract all /schemes/* + /services/*
              URLs. (Topic pages were considered but their item cards are
              JS-button-routed, not anchor-linked, so they yield 0 hrefs.
              The sitemap remains the authoritative URL list.)
2. Scrape   : for each unique URL, render the page, click "Expand all
              sections" so accordion content is visible, then capture the
              <main> element's text + HTML. Saves one JSON per page under
              data/raw/{schemes|services}/<ID>.json.
3. Manifest : write data/manifest.json with counts + failure log.

Usage
-----
    # Scrape just N URLs (smoke test):
    python scraper.py 5

    # Full run (no arg):
    python scraper.py

Notes
-----
* Resumable: pages whose output JSON already exists are skipped.
* Polite: 500 ms delay between page loads.
* Single Chromium context for the whole run (fast, low overhead).
* `topics` field is left as [] for now — v2 will populate via a separate
  topic-mapping pass (likely by clicking topic-page cards or hitting the
  underlying Next.js data API).
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE = "https://supportgowhere.life.gov.sg"
ROOT = Path(__file__).parent
DATA = ROOT / "data"
RAW = DATA / "raw"
SCHEMES_DIR = RAW / "schemes"
SERVICES_DIR = RAW / "services"
MANIFEST_PATH = DATA / "manifest.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36"
)

SITEMAP_URL = f"{BASE}/sitemap.xml"
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"

# Live category slugs verified from the rendered homepage on 2026-05-27.
# Kept for the future topic-mapping pass; not used in the v1 scrape itself.
TOPIC_SLUGS = [
    "caregiving-support",
    "citizenship-residency",
    "counselling-crisis",
    "disability-support",
    "education-learning",
    "family-parenting",
    "financial-support",
    "healthcare",
    "housing-shelters",
    "mental-health",
    "retirement-legacy",
    "work-employment",
]

REQUEST_DELAY_SEC = 0.5
NAV_TIMEOUT_MS = 45_000
SETTLE_MS = 800


def url_to_id(url: str) -> tuple[str, str]:
    """Return (kind, page_id) from a /schemes/<ID>[/<slug>] or /services/... URL."""
    # Accept both '/schemes/<id>/<slug>' (canonical) and '/schemes/<id>' (no slug).
    match = re.search(r"/(schemes|services)/([^/?#]+)", url)
    if not match:
        raise ValueError(f"unrecognized url shape: {url}")
    kind = "scheme" if match.group(1) == "schemes" else "service"
    return kind, match.group(2)


def fetch(page: Page, url: str) -> bool:
    """Navigate to url, wait for the SPA to settle. Returns True on success."""
    try:
        page.goto(url, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
        page.wait_for_timeout(SETTLE_MS)
        return True
    except Exception as exc:  # noqa: BLE001 - we log and continue
        print(f"  ! fetch failed: {exc}", file=sys.stderr)
        return False


def fetch_sitemap_urls() -> list[str]:
    """Fetch /sitemap.xml and return all /schemes/* + /services/* URLs."""
    req = urllib.request.Request(SITEMAP_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
    root = ET.fromstring(body)
    urls: set[str] = set()
    for loc in root.iter(f"{{{SITEMAP_NS}}}loc"):
        url = (loc.text or "").strip()
        if "/schemes/" in url or "/services/" in url:
            urls.add(url)
    return sorted(urls)


def extract_record(page: Page, url: str) -> dict | None:
    """Render a scheme/service page; return a structured record (or None on failure)."""
    if not fetch(page, url):
        return None
    # Best-effort: expand all accordions so all section text is in the visible tree.
    expand_btn = page.get_by_text(
        re.compile(r"^\s*expand all sections\s*$", re.I)
    )
    if expand_btn.count() > 0:
        try:
            expand_btn.first.click(timeout=3_000)
            page.wait_for_timeout(400)
        except Exception:  # noqa: BLE001 - non-fatal
            pass
    title = (page.title() or "").replace(" - SupportGoWhere", "").strip()
    main = page.locator("main").first
    try:
        text = main.inner_text(timeout=5_000)
    except Exception:  # noqa: BLE001
        text = ""
    kind, page_id = url_to_id(url)
    # Detect SGW's "Page not found" error page so dead sitemap URLs don't
    # silently land in the corpus. Title is "Error" and body starts with
    # "Error - SupportGoWhere\nPage not found".
    if title == "Error" or text.startswith("Error - SupportGoWhere\nPage not found"):
        print(f"  ! dead URL (Page not found): {url}", file=sys.stderr)
        return None
    return {
        "id": page_id,
        "kind": kind,
        "url": url,
        "title": title,
        "text": text,
        "char_count": len(text),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


def save_record(record: dict, topics: list[str] | None = None) -> Path:
    """Save a scrape record to data/raw/{schemes|services}/<id>.json."""
    record = dict(record, topics=sorted(topics or []))
    out_dir = SCHEMES_DIR if record["kind"] == "scheme" else SERVICES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{record['id']}.json"
    path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def output_path_for(url: str) -> Path:
    kind, page_id = url_to_id(url)
    folder = SCHEMES_DIR if kind == "scheme" else SERVICES_DIR
    return folder / f"{page_id}.json"


def main(limit: int | None = None) -> None:
    DATA.mkdir(exist_ok=True)
    SCHEMES_DIR.mkdir(parents=True, exist_ok=True)
    SERVICES_DIR.mkdir(parents=True, exist_ok=True)

    started = datetime.now(timezone.utc)

    # --- Phase 1: discover (no browser needed; sitemap is plain XML) --------
    print("=" * 60)
    print("Phase 1: discover URLs from sitemap.xml")
    print("=" * 60)
    all_urls = fetch_sitemap_urls()
    scheme_urls = [u for u in all_urls if "/schemes/" in u]
    service_urls = [u for u in all_urls if "/services/" in u]
    print(f"  schemes  : {len(scheme_urls)}")
    print(f"  services : {len(service_urls)}")
    print(f"  total    : {len(all_urls)}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT, locale="en-SG")
        page = context.new_page()

        # --- Phase 2: scrape ------------------------------------------------
        targets = all_urls[:limit] if limit else all_urls
        print()
        print("=" * 60)
        print(f"Phase 2: scrape {len(targets)} pages")
        print("=" * 60)
        failed: list[dict] = []
        skipped = 0
        scraped = 0
        for i, url in enumerate(targets, 1):
            kind, page_id = url_to_id(url)
            out = output_path_for(url)
            if out.exists():
                skipped += 1
                continue
            print(f"  {i:3d}/{len(targets)} {kind:7s} {page_id}")
            record = extract_record(page, url)
            if record is None or not record.get("text"):
                failed.append({"url": url, "id": page_id, "kind": kind})
                continue
            save_record(record)
            scraped += 1
            time.sleep(REQUEST_DELAY_SEC)

        # --- Phase 3: manifest ----------------------------------------------
        ended = datetime.now(timezone.utc)
        manifest = {
            "started_at": started.isoformat(),
            "ended_at": ended.isoformat(),
            "duration_sec": (ended - started).total_seconds(),
            "topic_slugs_reference": TOPIC_SLUGS,
            "sitemap_url_count": len(all_urls),
            "scheme_count": len(scheme_urls),
            "service_count": len(service_urls),
            "targets_attempted": len(targets),
            "newly_scraped": scraped,
            "skipped_existing": skipped,
            "failed": failed,
        }
        MANIFEST_PATH.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        browser.close()

    print()
    print("=" * 60)
    print(f"Done. scraped={scraped} skipped={skipped} failed={len(failed)}")
    print(f"Manifest: {MANIFEST_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    main(int(arg) if arg else None)
