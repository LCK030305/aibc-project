"""Print a curated sample of corpus records for human eyeball QA.

Run after scraper.py has populated data/raw/. Forces UTF-8 stdout so the
SGW corpus (which contains zero-width spaces, em-dashes, etc.) prints
cleanly on Windows PowerShell too.
"""

import io
import json
import sys
from pathlib import Path

# Force UTF-8 stdout (Windows PowerShell defaults to cp1252).
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)

BASE = Path(__file__).parent / "data" / "raw"

# Curated sample across schemes / services / diverse topic domains.
PICKS = [
    ("schemes",  "COMCARE-SMTA", "financial    | flagship"),
    ("schemes",  "CHAS",         "healthcare   | very common"),
    ("schemes",  "ATF",          "disability   | grant"),
    ("services", "SVC-FSCF",     "family       | multi-branch service"),
    ("services", "ECsnBwjK",     "crisis       | SOS Care Text"),
    ("services", "KIDSTART",     "children     | early-intervention"),
]


def main() -> None:
    for folder, page_id, tag in PICKS:
        f = BASE / folder / f"{page_id}.json"
        if not f.exists():
            print(f"!!! missing: {f}")
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        print("=" * 78)
        print(f"[{tag}]")
        print(f"id     : {d['id']}  ({d['kind']})")
        print(f"title  : {d['title']}")
        print(f"url    : {d['url']}")
        print(f"chars  : {d['char_count']}")
        print()
        print(d["text"])
        print()


if __name__ == "__main__":
    main()
