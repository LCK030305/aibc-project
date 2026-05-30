"""Diagnose a single topic page — what items the site shows vs. what we captured.

Reveals three things:
  1. All URL paths the page references (any /schemes/, /services/, /grants/, etc.)
  2. Which IDs are in our corpus vs. outside it (newly added since our scrape?)
  3. The raw card count visible in the DOM (the page says '72 results found' — does that match?)

Usage:
    python diagnose_topic.py caregiving-support
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "https://supportgowhere.life.gov.sg"
ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36"
)

# Broader pattern — anything that looks like an item URL, not just /schemes/ or /services/.
ITEM_PATH_RE = re.compile(r"/(schemes|services|grants|caregiving)/([A-Za-z0-9_-]+)")
RESULTS_RE = re.compile(r"(\d+)\s+results?\s+found", re.IGNORECASE)


def main(slug: str) -> None:
    valid_schemes = {p.stem for p in (RAW / "schemes").glob("*.json")}
    valid_services = {p.stem for p in (RAW / "services").glob("*.json")}
    valid_all = valid_schemes | valid_services

    url = f"{BASE}/topics/{slug}"
    json_id_hits: set[tuple[str, str]] = set()
    html_id_hits: set[tuple[str, str]] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=USER_AGENT, locale="en-SG")
        page = ctx.new_page()

        def on_response(response):  # noqa: ANN001
            try:
                ct = (response.headers.get("content-type", "") or "").lower()
                if "application/json" not in ct or response.status != 200:
                    return
                if any(s in response.url for s in ("/gtag", "/analytics", "/beacon")):
                    return
                # Re-fetch body as text so we can regex it (avoids deep JSON walking).
                body_text = response.text()
            except Exception:
                return
            for m in ITEM_PATH_RE.finditer(body_text):
                json_id_hits.add((m.group(1), m.group(2)))

        page.on("response", on_response)
        page.goto(url, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(3_000)
        html = page.content()

        # Try to read the displayed result count.
        m = RESULTS_RE.search(html)
        page_says = int(m.group(1)) if m else None

        # Count cards (a few common selectors — try each).
        card_counts: dict[str, int] = {}
        for sel in (
            "[data-testid='scheme-card']",
            "[data-testid='service-card']",
            "[data-testid='result-card']",
            "[data-testid='card']",
            "article[role='listitem']",
            "[role='listitem']",
            "li[data-testid]",
        ):
            try:
                n = page.locator(sel).count()
                if n:
                    card_counts[sel] = n
            except Exception:
                pass

        for m2 in ITEM_PATH_RE.finditer(html):
            html_id_hits.add((m2.group(1), m2.group(2)))

        browser.close()

    all_hits = json_id_hits | html_id_hits
    by_kind = Counter(kind for kind, _ in all_hits)

    print(f"Topic: {slug}")
    print(f"URL  : {url}")
    print()
    print(f"Page reports '{page_says} results found'" if page_says else
          "(no 'N results found' text on page)")
    if card_counts:
        print(f"Card counts in DOM: {card_counts}")
    else:
        print("Card counts in DOM: (no known selector matched — cards may use a "
              "different attribute set)")
    print()
    print("Unique item paths captured (XHR JSON + HTML):")
    for kind, n in by_kind.most_common():
        print(f"  /{kind:11s}: {n}")
    print()

    # In-corpus vs out-of-corpus split
    in_corpus = [(k, i) for (k, i) in all_hits if i in valid_all]
    out_of_corpus = [(k, i) for (k, i) in all_hits if i not in valid_all]

    print(f"In corpus      : {len(in_corpus)}")
    print(f"NOT in corpus  : {len(out_of_corpus)}  <-- these are likely new")
    if out_of_corpus:
        print()
        print("Items discovered but missing from our scraped corpus:")
        for kind, pid in sorted(out_of_corpus):
            print(f"  /{kind}/{pid}")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "caregiving-support"
    main(target)
