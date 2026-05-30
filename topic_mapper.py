"""Topic mapper — discover which schemes/services appear under each topic.

Why: scheme/service cards on /topics/<slug> pages are JS-routed buttons,
not <a href> anchors, so anchor-based discovery yields zero hits. The data
must arrive via XHR or be embedded in hydration JSON.

Approach: Playwright renders each of the 12 topic pages; we listen for
every JSON response AND also scan the final rendered HTML, then extract
scheme/service IDs by regex. We intersect those IDs with the corpus we
already scraped (data/raw/schemes/, data/raw/services/) to discard noise.

Output: data/topic_mapping.json — { topic_slug: { schemes: [...], services: [...] } }
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "https://supportgowhere.life.gov.sg"
ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"
OUT_PATH = ROOT / "data" / "topic_mapping.json"

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

# Matches '/schemes/<ID>' or '/services/<ID>' anywhere in a string.
URL_PATH_RE = re.compile(r"/(schemes|services)/([A-Za-z0-9_-]+)")


def find_parent_ids(value) -> set[str]:
    """Walk any JSON-like value and collect scheme/service IDs from URL paths."""
    found: set[str] = set()
    if isinstance(value, dict):
        for v in value.values():
            found |= find_parent_ids(v)
    elif isinstance(value, list):
        for v in value:
            found |= find_parent_ids(v)
    elif isinstance(value, str):
        for m in URL_PATH_RE.finditer(value):
            found.add(m.group(2))
    return found


def discover_topic_items(
    context, slug: str, valid_schemes: set[str], valid_services: set[str]
) -> dict:
    """Render /topics/<slug>, capture XHR JSON + HTML, return mapping for this topic."""
    page = context.new_page()
    captured_ids: set[str] = set()

    def on_response(response):  # noqa: ANN001 - playwright callback shape
        try:
            ct = response.headers.get("content-type", "") or ""
            if "application/json" not in ct.lower():
                return
            if response.status != 200:
                return
            url = response.url
            # Skip obvious noise.
            if any(s in url for s in ("/gtag", "/analytics", "/beacon")):
                return
            body = response.json()
        except Exception:
            return
        captured_ids.update(find_parent_ids(body))

    page.on("response", on_response)
    url = f"{BASE}/topics/{slug}"
    page.goto(url, wait_until="networkidle", timeout=60_000)
    page.wait_for_timeout(2_500)
    # Also scan the rendered HTML (sometimes data is embedded in __NEXT_DATA__).
    html = page.content()
    for m in URL_PATH_RE.finditer(html):
        captured_ids.add(m.group(2))
    page.close()

    schemes = sorted(captured_ids & valid_schemes)
    services = sorted(captured_ids & valid_services)
    return {
        "schemes": schemes,
        "services": services,
        "n_schemes": len(schemes),
        "n_services": len(services),
        "total": len(schemes) + len(services),
    }


def main() -> None:
    valid_schemes = {p.stem for p in (RAW / "schemes").glob("*.json")}
    valid_services = {p.stem for p in (RAW / "services").glob("*.json")}
    print(f"Corpus: {len(valid_schemes)} schemes + {len(valid_services)} services")

    result: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT, locale="en-SG")
        for slug in TOPIC_SLUGS:
            print(f"  crawling /topics/{slug} ...", end=" ", flush=True)
            t0 = time.time()
            result[slug] = discover_topic_items(context, slug, valid_schemes, valid_services)
            dt = time.time() - t0
            print(f"{result[slug]['total']:4d} items  ({dt:.1f}s)")
            time.sleep(0.5)
        browser.close()

    OUT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    # Coverage summary
    all_scheme_ids: set[str] = set()
    all_service_ids: set[str] = set()
    for v in result.values():
        all_scheme_ids |= set(v["schemes"])
        all_service_ids |= set(v["services"])

    print()
    print("=" * 64)
    print(f"{'topic':28s} {'schemes':>8s} {'services':>9s} {'total':>6s}")
    print("-" * 64)
    for slug, v in result.items():
        print(f"{slug:28s} {v['n_schemes']:8d} {v['n_services']:9d} {v['total']:6d}")
    print("-" * 64)
    print(f"{'unique covered':28s} {len(all_scheme_ids):8d} {len(all_service_ids):9d} "
          f"{len(all_scheme_ids) + len(all_service_ids):6d}")
    print(f"{'corpus':28s} {len(valid_schemes):8d} {len(valid_services):9d} "
          f"{len(valid_schemes) + len(valid_services):6d}")
    not_covered_schemes = valid_schemes - all_scheme_ids
    not_covered_services = valid_services - all_service_ids
    if not_covered_schemes or not_covered_services:
        print()
        print(f"Records NOT linked to any topic: "
              f"{len(not_covered_schemes)} schemes, {len(not_covered_services)} services")
    print()
    print(f"Mapping saved: {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
