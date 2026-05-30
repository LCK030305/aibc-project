"""Chunker: split scraped SupportGoWhere records into section-level chunks.

For each input record (data/raw/{schemes,services}/<id>.json), emits:
  - tagline    chunk : 1-line scheme description
  - highlights chunk : SCHEME/SERVICE HIGHLIGHTS bullets
  - about      chunk : "About this support"
  - who        chunk : "Who is this for?"  (eligibility — high-value for RAG)
  - apply      chunk : "How to apply?"
  - help       chunk : "Where can I find help?"
  - expect     chunk : "What to expect?"
  - whole      chunk : all of the above concatenated (for full-record queries)

Sections only emit if present (records vary; e.g. KidSTART has no `help`).

UI noise is stripped (Share link, SUPPORT RECOMMENDER block, "Find service
providers near you", etc.). The "last updated" date is captured as metadata
and trailing content (SUPPORT RECOMMENDER banner, provider lists) is
truncated to keep section chunks clean.

Output: data/chunks/chunks.jsonl + data/chunks/summary.json.

Run with the project venv:
    .venv\\Scripts\\python.exe chunker.py
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "chunks"
OUT_JSONL = OUT_DIR / "chunks.jsonl"
SUMMARY_PATH = OUT_DIR / "summary.json"

# Section heading -> stable slug. These are the markers we split on.
SECTION_SLUGS = {
    "About this support":     "about",
    "Who is this for?":       "who",
    "How to apply?":          "apply",
    "Where can I find help?": "help",
    "What to expect?":        "expect",
}
SECTION_LABELS = list(SECTION_SLUGS.keys())

# Single-line UI noise to drop entirely.
NOISE_LINES = {
    "Share link",
    "Collapse all sections",
    "Expand all sections",
    "Apply now",
    "Apply now / View application",
    "Find service providers near you",
    "Filters",
    "Sort By",
    "Show more details",
    "Check now",
    "View more details",
}

# Multi-line noise blocks to remove via regex.
NOISE_PATTERNS = [
    # SUPPORT RECOMMENDER callout at the bottom of every page.
    re.compile(
        r"^SUPPORT RECOMMENDER\s*\n.*?Check now\s*$",
        re.MULTILINE | re.DOTALL,
    ),
]

# Captures the "last updated" date and lets us truncate everything after it.
LAST_UPDATED_PATTERN = re.compile(
    r"^(?:Scheme last updated|Information last updated on)\s+([0-9]{1,2}\s+\w+\s+\d{4})\s*$",
    re.MULTILINE,
)


def strip_leading_title_dup(text: str, title: str) -> str:
    """Drop the duplicated '<title> - SupportGoWhere\\n<title>' header."""
    lines = text.splitlines()
    if len(lines) >= 2:
        if lines[0].strip() == f"{title} - SupportGoWhere" and lines[1].strip() == title:
            return "\n".join(lines[2:]).lstrip()
    if lines and lines[0].strip().endswith("- SupportGoWhere"):
        return "\n".join(lines[1:]).lstrip()
    return text


def strip_noise(text: str) -> str:
    """Strip UI noise lines and multi-line blocks."""
    for pat in NOISE_PATTERNS:
        text = pat.sub("", text)
    kept = [ln for ln in text.splitlines() if ln.strip() not in NOISE_LINES]
    out = "\n".join(kept)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def extract_last_updated(text: str) -> tuple[str | None, str]:
    """Capture the last-updated date and truncate everything from that line on."""
    m = LAST_UPDATED_PATTERN.search(text)
    if m:
        return m.group(1), text[:m.start()].rstrip()
    return None, text


def extract_tagline(text: str) -> tuple[str, str]:
    """Tagline = text before SCHEME/SERVICE HIGHLIGHTS. Returns (tagline, rest)."""
    m = re.search(r"^(SCHEME HIGHLIGHTS|SERVICE HIGHLIGHTS)\s*$", text, re.MULTILINE)
    if m:
        return text[:m.start()].strip(), text[m.start():].strip()
    # Fallback: first paragraph.
    para_break = text.find("\n\n")
    if para_break > 0:
        return text[:para_break].strip(), text[para_break + 2:].strip()
    return "", text


def extract_highlights(text: str) -> tuple[str, str]:
    """Pull bullets between HIGHLIGHTS header and the first real section."""
    header_match = re.match(r"^(?:SCHEME HIGHLIGHTS|SERVICE HIGHLIGHTS)\s*\n", text)
    if header_match:
        text = text[header_match.end():]
    end_pattern = re.compile(
        r"^(?:About this support|Who is this for\?|How to apply\?|"
        r"Where can I find help\?|What to expect\?|SERVICE PROVIDERS|HELPLINE)\s*$",
        re.MULTILINE,
    )
    m = end_pattern.search(text)
    if m:
        return text[:m.start()].strip(), text[m.start():]
    return text.strip(), ""


def split_by_sections(text: str) -> dict[str, str]:
    """Capture body text under each known section heading."""
    label_re = "|".join(re.escape(lbl) for lbl in SECTION_LABELS)
    splitter = re.compile(rf"^({label_re})\s*$", re.MULTILINE)
    matches = list(splitter.finditer(text))
    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        slug = SECTION_SLUGS[m.group(1)]
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body and slug not in sections:
            sections[slug] = body
    return sections


def chunkify_record(record: dict) -> list[dict]:
    parent_id = record["id"]
    kind = record["kind"]
    title = record["title"]
    url = record["url"]

    text = record["text"]
    text = strip_leading_title_dup(text, title)
    text = strip_noise(text)
    last_updated, text = extract_last_updated(text)
    tagline, rest = extract_tagline(text)
    highlights, rest = extract_highlights(rest)
    sections = split_by_sections(rest)

    def chunk(section_slug: str, label: str, body: str) -> dict:
        return {
            "chunk_id": f"{parent_id}__{section_slug}",
            "parent_id": parent_id,
            "kind": kind,
            "section": section_slug,
            "section_label": label,
            "title": title,
            "tagline": tagline,
            "url": url,
            "last_updated": last_updated,
            "text": body,
            "char_count": len(body),
        }

    chunks: list[dict] = []
    if tagline:
        chunks.append(chunk("tagline", "Tagline", tagline))
    if highlights:
        label = "Service Highlights" if kind == "service" else "Scheme Highlights"
        chunks.append(chunk("highlights", label, highlights))
    for slug in ("about", "who", "apply", "help", "expect"):
        if slug in sections:
            label = next(lbl for lbl, s in SECTION_SLUGS.items() if s == slug)
            chunks.append(chunk(slug, label, sections[slug]))
    parts = [p for p in ([tagline, highlights] + list(sections.values())) if p]
    chunks.append(chunk("whole", "Full record", "\n\n".join(parts)))
    return chunks


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sources = sorted(RAW.glob("schemes/*.json")) + sorted(RAW.glob("services/*.json"))
    all_chunks: list[dict] = []
    for f in sources:
        record = json.loads(f.read_text(encoding="utf-8"))
        all_chunks.extend(chunkify_record(record))

    with OUT_JSONL.open("w", encoding="utf-8") as fp:
        for ch in all_chunks:
            fp.write(json.dumps(ch, ensure_ascii=False) + "\n")

    section_counts = Counter(c["section"] for c in all_chunks)
    kind_counts = Counter(c["kind"] for c in all_chunks)
    char_lens = [c["char_count"] for c in all_chunks]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_records": len(sources),
        "total_chunks": len(all_chunks),
        "by_section": dict(section_counts),
        "by_kind": dict(kind_counts),
        "char_stats": {
            "min":    min(char_lens) if char_lens else 0,
            "max":    max(char_lens) if char_lens else 0,
            "mean":   int(sum(char_lens) / len(char_lens)) if char_lens else 0,
            "median": int(sorted(char_lens)[len(char_lens) // 2]) if char_lens else 0,
        },
        "output_file": str(OUT_JSONL.relative_to(ROOT)),
    }
    SUMMARY_PATH.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Source records : {len(sources)}")
    print(f"Total chunks   : {len(all_chunks)}")
    print(f"Output         : {OUT_JSONL.relative_to(ROOT)}")
    print(f"Summary        : {SUMMARY_PATH.relative_to(ROOT)}")
    print()
    print("Section coverage:")
    for sect in ("tagline", "highlights", "about", "who", "apply", "help", "expect", "whole"):
        cnt = section_counts.get(sect, 0)
        pct = (cnt / len(sources) * 100) if sources else 0
        print(f"  {sect:12s} {cnt:5d}  ({pct:5.1f}% of records)")
    print()
    print(f"Char length:  min={summary['char_stats']['min']:>5}  "
          f"median={summary['char_stats']['median']:>5}  "
          f"mean={summary['char_stats']['mean']:>5}  "
          f"max={summary['char_stats']['max']:>5}")


if __name__ == "__main__":
    main()
