"""Probe SupportGoWhere DOM structure before writing the real scraper.

We render 3 representative pages with Playwright (JS executed), save the
HTML + a full-page screenshot, and print quick selector counts. The findings
tell us:
  - whether the JS-rendered content is actually accessible
  - which selectors hit the category cards / scheme body / service body
  - what page title, headings, and main-content structure look like

Outputs go to ./samples/.
"""

from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "samples"
OUT.mkdir(exist_ok=True)

URLS = {
    "homepage": "https://supportgowhere.life.gov.sg/",
    "scheme_smta": (
        "https://supportgowhere.life.gov.sg/schemes/"
        "COMCARE-SMTA/comcare-short-to-medium-term-assistance-smta"
    ),
    "service_fsc": (
        "https://supportgowhere.life.gov.sg/services/"
        "SVC-FSCF/family-service-centre-fsc"
    ),
}

# Selectors we want to probe on each rendered page. Order doesn't matter; we
# just want to see which ones hit and roughly what they contain.
SELECTORS = [
    "a[href*='/categories/']",
    "a[href*='/topics/']",
    "a[href^='/schemes/']",
    "a[href^='/services/']",
    "a[href^='/caregiving']",
    "h1",
    "h2",
    "main",
    "[role='main']",
    "article",
    "section",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36"
)


def probe() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT, locale="en-SG")
        for name, url in URLS.items():
            print(f"\n=== {name}  ->  {url}")
            page = context.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=45_000)
            except Exception as exc:  # noqa: BLE001 - we want to see any failure
                print(f"  goto error: {exc}")
                page.close()
                continue
            page.wait_for_timeout(1500)  # let late JS settle
            html = page.content()
            (OUT / f"{name}.html").write_text(html, encoding="utf-8")
            page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
            print(f"  title          : {page.title()!r}")
            print(f"  rendered bytes : {len(html):,}")
            for sel in SELECTORS:
                try:
                    count = page.locator(sel).count()
                except Exception as exc:  # noqa: BLE001
                    print(f"  {sel:35s} error: {exc}")
                    continue
                if count == 0:
                    continue
                first_text = ""
                try:
                    first_text = (
                        page.locator(sel).first.inner_text(timeout=2_000)[:90]
                        .replace("\n", " ")
                        .strip()
                    )
                except Exception:  # noqa: BLE001
                    pass
                print(f"  {sel:35s} count={count:4d}  first={first_text!r}")
            page.close()
        browser.close()
    print(f"\nDone. Samples written to: {OUT}")


if __name__ == "__main__":
    probe()
