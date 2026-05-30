"""Scrape the corpus-missing items found by find_missing.py.

Reads data/missing_items.json and scrapes each URL using the same
extraction logic as scraper.py. Output JSONs land in
data/raw/{schemes,services}/ alongside existing records.

After this, re-run: chunker.py → embed.py → topic_mapper.py.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

# Reuse the existing scraper's logic so behaviour stays consistent.
from scraper import (  # noqa: E402
    REQUEST_DELAY_SEC,
    USER_AGENT,
    extract_record,
    save_record,
)

ROOT = Path(__file__).parent
MISSING_PATH = ROOT / "data" / "missing_items.json"


def main() -> None:
    data = json.loads(MISSING_PATH.read_text(encoding="utf-8"))
    urls = data["missing_urls"]
    print(f"Scraping {len(urls)} missing items...")
    print()

    scraped = 0
    failed: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT, locale="en-SG")
        page = context.new_page()
        for i, url in enumerate(urls, 1):
            print(f"  {i:2d}/{len(urls)} {url}")
            record = extract_record(page, url)
            if record is None or not record.get("text"):
                failed.append(url)
                continue
            save_record(record)
            scraped += 1
            time.sleep(REQUEST_DELAY_SEC)
        browser.close()

    print()
    print(f"Scraped : {scraped}")
    print(f"Failed  : {len(failed)}")
    for f in failed:
        print(f"  ! {f}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
