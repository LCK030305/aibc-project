"""Debug what /topics/financial-support actually renders into the DOM.

The first scrape pass discovered 0 URLs per topic page — so either:
  - the listings need more time to render than `networkidle` waits,
  - the items are not <a href="/schemes/..."> anchors (could be buttons /
    client-side routed divs / full URLs),
  - or there's a "Load more" gate / infinite scroll.

This probe dumps enough diagnostic info to figure out which.
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "samples"
OUT.mkdir(exist_ok=True)
URL = "https://supportgowhere.life.gov.sg/topics/financial-support"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36"
)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(user_agent=USER_AGENT, locale="en-SG")
    page = context.new_page()
    page.goto(URL, wait_until="networkidle", timeout=60_000)
    page.wait_for_timeout(2_500)
    html = page.content()
    (OUT / "topic_financial.html").write_text(html, encoding="utf-8")
    page.screenshot(path=str(OUT / "topic_financial.png"), full_page=True)
    print(f"title         : {page.title()!r}")
    print(f"rendered bytes: {len(html):,}")
    print(f"total <a>     : {page.locator('a').count()}")

    # Show all unique href patterns to see how items are linked.
    hrefs = page.evaluate(
        """() => Array.from(document.querySelectorAll('a')).map(a => a.getAttribute('href') || '')"""
    )
    print(f"unique hrefs  : {len(set(hrefs))}")

    # Categorise hrefs by their leading path segment so we can spot the pattern.
    buckets: dict[str, list[str]] = {}
    for h in hrefs:
        if not h:
            continue
        key = "/".join(h.split("/")[:2]) if h.startswith("/") else h.split(":", 1)[0]
        buckets.setdefault(key, []).append(h)
    print("\nhref buckets (head of each):")
    for k, vs in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        sample = vs[0] if vs else ""
        print(f"  {len(vs):4d} x {k!r:30s} e.g. {sample}")

    # Check for "Load more" button (pagination control).
    for label in ["Load more", "Show more", "View all", "See all"]:
        cnt = page.get_by_text(label, exact=False).count()
        if cnt:
            print(f"  found {cnt}x text {label!r}")

    # Look for any data-testid attributes — useful for stable selectors.
    testids = page.evaluate(
        """() => Array.from(new Set(Array.from(document.querySelectorAll('[data-testid]')).map(e => e.getAttribute('data-testid'))))"""
    )
    print(f"\ndata-testid values present ({len(testids)}):")
    for t in testids[:30]:
        print(f"  {t}")

    browser.close()
