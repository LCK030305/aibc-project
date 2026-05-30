"""Find all corpus-missing items across the 12 topic pages.

Re-renders every topic page, captures every (kind, id) pair we see, and
flags any that aren't yet in data/raw/schemes/ or data/raw/services/.
Output:
  - data/missing_items.json     (full breakdown per topic + global set)
  - prints a summary table to stdout

After this, we know exactly how many newly-added items to scrape.
"""

from __future__ import annotations

import io
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

from playwright.sync_api import sync_playwright

# Force UTF-8 stdout on Windows.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)

BASE = "https://supportgowhere.life.gov.sg"
ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"
OUT_PATH = ROOT / "data" / "missing_items.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36"
)

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

ITEM_PATH_RE = re.compile(r"/(schemes|services)/([A-Za-z0-9_-]+)")


def crawl_topic(context, slug: str) -> set[tuple[str, str]]:
    """Return all (kind, id) pairs surfaced on /topics/<slug>."""
    page = context.new_page()
    hits: set[tuple[str, str]] = set()

    def on_response(response):  # noqa: ANN001
        try:
            ct = (response.headers.get("content-type", "") or "").lower()
            if "application/json" not in ct or response.status != 200:
                return
            if any(s in response.url for s in ("/gtag", "/analytics", "/beacon")):
                return
            body_text = response.text()
        except Exception:
            return
        for m in ITEM_PATH_RE.finditer(body_text):
            hits.add((m.group(1), m.group(2)))

    page.on("response", on_response)
    page.goto(f"{BASE}/topics/{slug}", wait_until="networkidle", timeout=60_000)
    page.wait_for_timeout(2_500)
    html = page.content()
    for m in ITEM_PATH_RE.finditer(html):
        hits.add((m.group(1), m.group(2)))
    page.close()
    return hits


def main() -> None:
    valid_schemes = {p.stem for p in (RAW / "schemes").glob("*.json")}
    valid_services = {p.stem for p in (RAW / "services").glob("*.json")}
    print(f"Existing corpus: {len(valid_schemes)} schemes + {len(valid_services)} services")
    print()

    per_topic: dict[str, dict] = {}
    all_missing: set[tuple[str, str]] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT, locale="en-SG")
        for slug in TOPIC_SLUGS:
            t0 = time.time()
            hits = crawl_topic(context, slug)
            missing = sorted(
                (kind, pid) for (kind, pid) in hits
                if not ((kind == "schemes" and pid in valid_schemes) or
                        (kind == "services" and pid in valid_services))
            )
            per_topic[slug] = {
                "total_found": len(hits),
                "missing_count": len(missing),
                "missing": missing,
            }
            all_missing.update(missing)
            dt = time.time() - t0
            print(f"  {slug:25s}  found={len(hits):4d}  missing={len(missing):3d}  ({dt:.1f}s)")
        browser.close()

    out = {
        "per_topic": per_topic,
        "all_missing_count": len(all_missing),
        "all_missing": sorted(all_missing),
        "missing_urls": [f"{BASE}/{kind}/{pid}" for (kind, pid) in sorted(all_missing)],
    }
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print("=" * 60)
    print(f"Total unique missing items across all topics: {len(all_missing)}")
    print("=" * 60)
    for kind, pid in sorted(all_missing):
        print(f"  /{kind}/{pid}")
    print()
    print(f"Saved to: {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
