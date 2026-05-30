# SAO Co-Pilot — MSF Programme Matcher

> *Reduce the time Social Assistance Officers spend resource-hunting, so more time goes to the families they serve.*

A Streamlit + RAG capstone for the **Singapore Polytechnic AI Champions Bootcamp** (MSF / GovTech, 2026).
**Use Case #1** addresses Pain Point #3 in the SAO workflow: matching a client's situation to the right
MSF schemes and community services from the
[SupportGoWhere](https://supportgowhere.life.gov.sg/) catalogue
(~307 records across 12 categories).

---

## What it does

A SAO types a 1–2 sentence client situation. The app:

1. **Embeds** the situation with `text-embedding-3-small`.
2. **Retrieves** the top 15 best-matching section-level chunks from the SGW corpus (cosine similarity).
3. **Deduplicates** to one entry per scheme/service, applies optional category/kind filters.
4. **Re-ranks** with `gpt-4.1-mini` using a **CO-STAR** prompt that asks for selection + rationale +
   eligibility flags + verbatim evidence quote, returned as structured JSON.
5. **Displays** the top 3–5 recommendations as cards, each with a fit score, the LLM's reasoning, a
   quote from the SGW corpus as evidence, a checklist of items the SAO must verify with the client,
   and a link to the live SGW page.

The end-to-end response is **~5 seconds** and costs **~$0.003 per query** on the OpenAI API.

---

## Quick start

```powershell
# 1. Clone or pull the project; cd into it
cd "D:\AI\1. MSF_AI_LLM_bootcamp_GovTech_SGPoly_May2026\Capstone assignment"

# 2. Create venv + install deps
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium   # one-time

# 3. Drop your OpenAI key in .env (gitignored)
echo OPENAI_API_KEY=sk-... > .env

# 4. (Optional) Re-build the corpus from scratch
.venv\Scripts\python scraper.py        # ~15 min
.venv\Scripts\python chunker.py        # seconds
.venv\Scripts\python embed.py          # ~20 sec ($0.005)
.venv\Scripts\python topic_mapper.py   # ~2 min

# 5. Launch the UI
.venv\Scripts\streamlit run app.py
#    -> open http://localhost:8501
```

**Required OpenAI project access:** `text-embedding-3-small` + `gpt-4.1-mini`.
Enable in `platform.openai.com/settings/projects/<your_project>/limits` → *Allowed models*.

---

## Architecture (data flow)

```
                    ┌──────────────────────────────┐
   SAO text input → │  app.py (Streamlit)          │
                    └──────────────┬───────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │  recommender.recommend()     │
                    └──────────────┬───────────────┘
                       ┌───────────┴────────────┐
                       ▼                        ▼
              retriever.search()       prompts.make_recommender_prompt()
                       │                        │
                       ▼                        ▼
              embed query, cosine       CO-STAR template w/ XML
              over vectors.npy,         <candidate> blocks
              dedup by parent_id
                       │                        │
                       └───────────┬────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │  llm.get_completion()        │
                    │  gpt-4.1-mini, JSON mode     │
                    └──────────────┬───────────────┘
                                   ▼
                    Structured JSON
                    → defensive parse + parent_id guard
                    → RecommendationResponse dataclass
                                   ▼
                    UI cards (title, fit, why, quote,
                    verify-checklist, SGW link)
```

---

## Project structure

Categories (used in the file map below):

- 🟠 **Core application** — modules used on every recommendation request
- 🟢 **Data-pipeline scripts** — run once to build/refresh the SGW corpus
- ⚪ **Diagnostics / one-off probes** — forensics kept for transparency
- 🌲 **Config & data** — environment + persisted artefacts

### Stage 0 · Project setup

| # | File / Action | What it does | Bootcamp topic(s) | Category |
|---|---|---|---|---|
| 0a | `requirements.txt` | Pinned pip deps: playwright, openai, python-dotenv, numpy, streamlit | Topic 6.2 — pip + venv | 🌲 Config & data |
| 0b | `.venv/` (`python -m venv`) | Isolated Python environment | Topic 6.2 | 🌲 Config & data |
| 0c | `.env` (gitignored) | `OPENAI_API_KEY=…` loaded by python-dotenv | Topic 5.2 — Secure credentials | 🌲 Config & data |
| 0d | `.gitignore` | Excludes `.venv/`, `.env`, `__pycache__/` | Topic 8.3 — Git/GitHub | 🌲 Config & data |

### Stage 1 · Data acquisition (one-time build)

| # | File | What it does | Bootcamp topic(s) | Category |
|---|---|---|---|---|
| 1 | `scraper.py` | Playwright renders 296 `/schemes/` + `/services/` URLs; saves cleaned text | Topic 5.3 · Topic 2.7 | 🟢 Data-pipeline scripts |
| 2 | `chunker.py` | Splits each record into section-level chunks (tagline / who / apply / …) | Topic 4.2 · Topic 1.3 | 🟢 Data-pipeline scripts |
| 3 | `embed.py` | Embeds 2,147 chunks via `text-embedding-3-small`; saves `vectors.npy` | Topic 3.1 · Topic 3.2 | 🟢 Data-pipeline scripts |
| 4 | `topic_mapper.py` | Crawls 12 topic pages; intercepts XHR JSON for category metadata | Topic 4.2 — Pre-Retrieval | 🟢 Data-pipeline scripts |
| 4b | `scrape_missing.py` | Patches items present on SGW topic pages but absent from sitemap (11 found) | Topic 4.5 — Coverage | 🟢 Data-pipeline scripts |

### Stage 2 · Application layer

| # | File | What it does | Bootcamp topic(s) | Category |
|---|---|---|---|---|
| 5 | `llm.py` | OpenAI wrapper: `get_completion()` + `embed_batch()`; loads key from `.env` | Topic 1.3 · 5.2 · 2.7 | 🟠 Core application |
| 6 | `prompts.py` | CO-STAR template builder; XML-tag delimited candidate rendering | Topic 1.2 · 1.3 · 2.5 · Playbook p.26 | 🟠 Core application |
| 7 | `retriever.py` | Loads vectors + index + topic map; `search()` = cosine + dedup + filters | Topic 3.3 · 3.4 · 4.3 | 🟠 Core application |
| 8 | `recommender.py` | End-to-end UC#1: retrieve → render → generate → parse | Topic 2.6 · 4.4 · 2.7 | 🟠 Core application |

### Stage 3 · UI

| # | File | What it does | Bootcamp topic(s) | Category |
|---|---|---|---|---|
| 9 | `app.py` | Streamlit interface: sidebar filters, sample queries, recommendation cards, debug panels | Topic 6.1 · 6.3 · 8.1 | 🟠 Core application |

### Stage 4 · Diagnostics & probes

| # | File | What it does | Bootcamp topic(s) | Category |
|---|---|---|---|---|
| D1 | `probe_dom.py` | Initial DOM-structure investigation across 3 page types | Topic 8.5 — Vibe coding | ⚪ Diagnostics |
| D2 | `probe_topic.py` | Topic-page DOM probe (showed cards are JS-routed, not anchors) | Topic 8.5 | ⚪ Diagnostics |
| D3 | `diagnose_topic.py` + `find_missing.py` | Per-topic gap diagnosis — surfaced 11 missing items | Topic 4.5 | ⚪ Diagnostics |
| D4 | `inspect_corpus.py` | Pretty-print sample records for eyeball QA | Topic 4.5 | ⚪ Diagnostics |

### Stage 5 · Planned

| # | File | What it will do | Bootcamp topic(s) | Category |
|---|---|---|---|---|
| 10 | `evaluator.py` | Ground-truth pairs + retrieval@k + LLM-judge | Topic 4.5 | 🟠 Core application |
| 11 | UC#2 modules: `doc_parser.py` · `rules_extractor.py` · `eligibility_checker.py` | Pain Point #2 — eligibility verification (likely uses **agentic tool-calling**, see below) | Topic 2.5 · 2.6 · 4.4 · Topic 5/6 agents | 🟠 Core application |
| 12 | Streamlit Cloud deploy | Push repo, set OpenAI key as secret, optional password protect | Topic 8.2 · 8.3 · 8.4 | 🌲 Config & data |

---

## Bootcamp curriculum coverage

| Week / Topic | What the bootcamp teaches | Where it lives in this repo |
|---|---|---|
| Week 1 (Topic 1.x) | LLM foundations · Prompt Engineering · f-strings · Tokens · Hallucinations | `llm.py` · `prompts.py` (CO-STAR) |
| Week 2 (Topic 2.x) | Advanced prompting · Chaining · Multi-action · Exception handling | `recommender.py` (chained pipeline + JSON parse guard) |
| Week 3 (Topic 3.x) | Embeddings · Handling embeddings · RAG · Search beyond keywords | `embed.py` · `retriever.py` |
| Week 4 (Topic 4.x) | Advanced RAG · Pre/Post-retrieval · Evaluation | `chunker.py` (pre) · `recommender.py` (post) · planned `evaluator.py` |
| Week 5 (Topic 5.x) | Agents · Secure credentials · Python scripts | `.env` / `python-dotenv` · clean script structure · *agents deferred to UC#2* |
| Week 6 (Topic 6.x) | Streamlit basics · pip + venv · Debugging | `requirements.txt` · `.venv/` · `app.py` |
| Week 8 (Topic 8.x) | Streamlit Deep Dive · Password protect · Git · Deploy · Vibe coding | `app.py` (`@st.cache_resource`, session_state) · planned deployment |

---

## On agentic AI (intentionally deferred)

The bootcamp's **Use Case Archetype #4** covers LLM Agents with Tools (Week 6) and CrewAI multi-agent
systems (Week 5). UC#1 in this repo **does not use agentic patterns**, and that's a deliberate choice:

| Concern | Single-shot RAG (current UC#1) | Agentic |
|---|---|---|
| Latency | ~5 s | 15–60 s (loop iterations) |
| Cost per query | ~$0.003 | 3–10× more |
| Determinism | High (temperature=0, JSON mode) | Lower (loop variance) |
| Evaluability | Straightforward retrieval@k | Trace-based, harder |
| Fits the task? | ✅ matching is mostly retrieval | Overkill for UC#1 |

**Where agentic patterns will earn their keep — UC#2 (eligibility verification):**

- **Tools**: `extract_income_from_bank_statement(file)`, `check_scheme_rule(scheme_id, fact)`,
  `ask_sao_for_missing_doc(doc_type)`
- **Agent loop**: parse docs → identify missing info → ask SAO → re-evaluate → produce verdict
- **Possibly multi-agent**: a "doc parser" agent, a "rules engine" agent, a "summariser" agent

So Archetype #4 isn't skipped — it's parked for UC#2 where it adds value over a single-shot call.

---

## Data provenance

- **Source**: [supportgowhere.life.gov.sg](https://supportgowhere.life.gov.sg/) (public catalogue)
- **Scraped**: 27 May 2026 (sitemap + patch crawl of newly-added items)
- **Records**: 219 schemes + 87 services + 1 unlinked service = **307**
- **Section chunks**: **2,147** (avg ~525 chars per chunk)
- **Categories**: 12 (Family/Parenting · Financial · Disability · Caregiving · …)
- **Embeddings**: OpenAI `text-embedding-3-small`, 1,536-dim, float32 ≈ 12.5 MB
- **Dead URLs**: 6 (retired schemes); archived in `data/raw/dead/`
- **Provenance**: `data/manifest.json` records every scrape run's start/end times, counts, failures

---

## Roadmap

1. **Now → next session** — build `evaluator.py` (Topic 4.5): ~10 ground-truth client scenarios
   with expected schemes; retrieval@k metric; LLM-judge ranking quality.
2. **Then** — UC#2 (Pain Point #2): doc parsing + eligibility checking; this is where agentic
   tool-calling enters.
3. **Then** — UC#1 + UC#2 unified into a single Streamlit app with two pages (Stage 2 + Stage 3 of
   the SAO workflow).
4. **Then** — deploy to Streamlit Community Cloud with password protection (Topic 8.2, 8.4).
5. **Possibly** — containerise + deploy on GovTech CStack (Xtra Topic 1.1, 1.2).

---

## Disclaimers

- **Not affiliated with MSF or GovTech** in any official capacity. Capstone exercise only.
- **Public data only.** No sensitive client information is processed or stored.
- **OpenAI API.** API calls send the (synthetic) client situation + retrieved corpus text to OpenAI.
  For real deployment on Restricted-Sensitive data, swap the LLM/embeddings to a WOG-internal model
  (Topic Xtra 2.1 LLMaaS for WOG).
- **Last updated**: 28 May 2026. Bootcamp capstone deadline: 14 August 2026.
