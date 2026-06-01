# SAO Co-Pilot — MSF Programme Matcher

> *Reduce the time Social Assistance Officers spend resource-hunting, so more time goes to the families they serve.*

A Streamlit + RAG capstone for the **Singapore Polytechnic AI Champions Bootcamp** (MSF / GovTech, 2026).
**Use Case #1** addresses Pain Point #3 in the SAO workflow: matching a client's situation to the right
MSF schemes and community services from the
[SupportGoWhere](https://supportgowhere.life.gov.sg/) catalogue
(~307 records across 12 categories).

---

## What it does

A SAO types a 1–2 sentence client situation. The app runs a **5-stage prompt chain**:

1. **Safety check** (`safety.py`) — binary Decision Chain classifier blocks prompt-injection /
   jailbreak attempts. Fail-CLOSED: errors treated as unsafe.
2. **Query classifier** (`router.py`) — multi-class Decision Chain routes input to
   `client_case` / `scheme_lookup` / `general_question` / `out_of_scope`. Fail-OPEN: defaults to
   `client_case` if the call errors so the user still gets recommendations.
3. **Least-to-Most decomposition** (`decomposer.py`) — complex multi-need cases split into 2–5
   discrete sub-needs; simple cases pass through as 1 sub-need. The retriever runs once per
   sub-need; results are merged + deduped before re-ranking.
4. **Retrieval** (`retriever.py`) — `text-embedding-3-small` cosine similarity over 2,147 section
   chunks. Optional category / kind filters.
5. **CO-STAR re-rank with Inner Monologue** (`recommender.py` + `prompts.py`) — `gpt-4.1-mini`
   in JSON mode produces structured output containing `reasoning_steps` (Chain-of-Thought) +
   selected recommendations with rationale + eligibility flags + verbatim evidence quote.

Optional **Human-in-the-Loop edit-gate** between steps 3 and 4 lets the SAO review and edit the
AI's decomposition before retrieval runs (Topic 2.6 HITL advantage).

End-to-end response is **~5 seconds** for simple cases, **~8 seconds** for complex multi-need
cases (extra LLM call for decomposition). Cost **~$0.003–0.01 per query** on the OpenAI API.

**Evaluation (`evaluator.py`)**: 10 hand-curated scenarios with broadened expected-answer sets.
Current metrics: **MRR 0.82** · **precision@5 0.58** · **recall@10 0.65**.

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
   SAO text input
        │
        ▼
   ┌────────────────────────────────────────────┐
   │  app.py (Streamlit) — calls recommend()    │
   └────────────────────┬───────────────────────┘
                        │
   ┌────────────────────▼──────────────────────────────────────┐
   │  step_1_safety_check     (Decision Chain · Topic 2.6)     │
   │    fail-CLOSED · max_tokens=1 · few-shot exemplars        │
   │    "Y" → 🛡️ block & show refusal banner                   │
   │    "N" → continue                                          │
   └────────────────────┬──────────────────────────────────────┘
                        │
   ┌────────────────────▼──────────────────────────────────────┐
   │  step_2_classify_query  (Decision Chain · Topic 2.6)      │
   │    fail-OPEN · multi-class JSON output                    │
   │    client_case / scheme_lookup → continue                 │
   │    general_question / out_of_scope → polite redirect      │
   └────────────────────┬──────────────────────────────────────┘
                        │
   ┌────────────────────▼──────────────────────────────────────┐
   │  step_3_decompose      (Least-to-Most · Topic 2.4)        │
   │    Simple case  → [original text]                          │
   │    Complex case → 2–5 sub-need strings                     │
   │    HITL gate (optional): SAO can edit before continue      │
   └────────────────────┬──────────────────────────────────────┘
                        │
   ┌────────────────────▼──────────────────────────────────────┐
   │  retriever.search() per sub-need  (RAG · Topic 3.4)       │
   │    text-embedding-3-small · cosine · dedup by parent_id   │
   │    Merge across sub-needs, keep best score per parent     │
   └────────────────────┬──────────────────────────────────────┘
                        │
   ┌────────────────────▼──────────────────────────────────────┐
   │  CO-STAR re-rank with Inner Monologue                      │
   │    (Topic 1.2 + 2.4 + 2.5 · Playbook p.26)                 │
   │    prompts.make_recommender_prompt() — XML <candidate>s   │
   │    llm.get_completion(response_format=json_object)         │
   │    Specific catches: RateLimitError, APIConnectionError,   │
   │      AuthenticationError, BadRequestError                  │
   │    JSON output: reasoning_steps + recommendations +        │
   │      categories_touched + overall_summary                  │
   └────────────────────┬──────────────────────────────────────┘
                        │
                        ▼
      RecommendationResponse dataclass (also exposes all
      intermediate stage outputs for the "Behind the scenes"
      debug panel)
                        │
                        ▼
      UI cards: title · fit_score · rationale · evidence quote
                · SAO-verify checklist · SGW link
      + cost footer  ⚡  + reasoning chain expander
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

### Stage 2 · Application layer (the prompt chain)

| # | File | What it does | Bootcamp topic(s) | Category |
|---|---|---|---|---|
| 5 | `llm.py` | OpenAI wrapper: `get_completion()` + `get_completion_from_messages()` + `embed_batch()` + `num_tokens_from_message_rough()` + `get_secret()`. Streamlit-Cloud-ready secret resolution. | Topic 1.3 · 5.2 · 2.7 | 🟠 Core application |
| 6 | `safety.py` | `step_1_safety_check()` — Decision Chain binary guard against prompt injection / jailbreak. Few-shot Y/N classifier, `max_tokens=1`, fail-CLOSED. | Topic 2.6 (Decision Chain) · 2.7 | 🟠 Core application |
| 7 | `router.py` | `step_2_classify_query()` — Decision Chain multi-class router: `client_case` / `scheme_lookup` / `general_question` / `out_of_scope`. JSON-mode output, fail-OPEN. | Topic 2.6 (Decision Chain) | 🟠 Core application |
| 8 | `decomposer.py` | `step_3_decompose()` — Least-to-Most prompting. Simple cases pass through as 1 sub-need; complex cases split into 2–5 sub-needs for separate retrieval. Fail-OPEN. | Topic 2.4 (Least-to-Most) | 🟠 Core application |
| 9 | `prompts.py` | CO-STAR template builder with `reasoning_steps` array for Inner Monologue. XML-tag delimited candidate rendering. | Topic 1.2 · 1.3 · 2.4 · 2.5 · Playbook p.26 | 🟠 Core application |
| 10 | `retriever.py` | Loads vectors + index + topic map; `search()` = cosine + dedup + category/kind filters. | Topic 3.3 · 3.4 · 4.3 | 🟠 Core application |
| 11 | `recommender.py` | Orchestrates the full 5-stage chain. Returns `RecommendationResponse` with safety_result, classification, decomposition, reasoning_steps, recommendations, prompt_sent, cost-relevant fields. Named OpenAI exception catches. | Topic 2.4 · 2.5 · 2.6 · 2.7 · 4.4 | 🟠 Core application |

### Stage 3 · UI

| # | File | What it does | Bootcamp topic(s) | Category |
|---|---|---|---|---|
| 12 | `app.py` | Streamlit UI: sidebar filters + tuning sliders + HITL toggle + debug toggle, 5 sample buttons (incl. 🧩 complex + 🚨 malicious), recommendation cards, reasoning expander, cost footer (⚡ tokens + USD + wall-time), "🔬 Behind the scenes" panel showing every pipeline stage with bootcamp-topic annotations. | Topic 6.1 · 6.3 · 8.1 (state, `@st.cache_resource`, `session_state`) | 🟠 Core application |

### Stage 4 · Evaluation (Topic 4.5)

| # | File | What it does | Bootcamp topic(s) | Category |
|---|---|---|---|---|
| 13 | `evaluator.py` | Two-metric framework: retrieval@k (recall, precision, MRR) over 10 hand-curated scenarios; LLM-as-judge rubric (relevance, evidence, flags) on `recommend()` outputs. Generates `eval/eval_report.{json,md}`. | Topic 4.5 — RAG Evaluation | 🟠 Core application |
| 14 | `eval/eval_data.json` | 10 scenarios spanning all 12 SGW categories, each with broadened expected-answer ground truth. | Topic 4.5 | 🌲 Config & data |
| 15 | `eval/eval_report.{json,md}` | Latest run output (regenerated by `python evaluator.py`). | Topic 4.5 | 🌲 Config & data |

### Stage 5 · Diagnostics & one-off probes

| # | File | What it does | Bootcamp topic(s) | Category |
|---|---|---|---|---|
| D1 | `probe_dom.py` | Initial DOM-structure investigation across 3 page types | Topic 8.5 — Vibe coding | ⚪ Diagnostics |
| D2 | `probe_topic.py` | Topic-page DOM probe (showed cards are JS-routed, not anchors) | Topic 8.5 | ⚪ Diagnostics |
| D3 | `diagnose_topic.py` + `find_missing.py` | Per-topic gap diagnosis — surfaced 11 missing items | Topic 4.5 | ⚪ Diagnostics |
| D4 | `inspect_corpus.py` | Pretty-print sample records for eyeball QA | Topic 4.5 | ⚪ Diagnostics |

### Stage 6 · Planned (future work)

| # | File | What it will do | Bootcamp topic(s) | Category |
|---|---|---|---|---|
| F1 | `pii_filter.py` (CLOAK) | PII detection + anonymisation via CLOAK FTA `/transform` endpoint. Sanitised text feeds the existing chain unchanged. | Topic 5 (WOG tooling) | 🟠 Core application |
| F2 | UC#2 modules: `doc_parser.py` · `rules_extractor.py` · `eligibility_checker.py` | Pain Point #2 — eligibility verification (likely uses **agentic tool-calling**, see below) | Topic 2.5 · 2.6 · 4.4 · Topic 5/6 agents | 🟠 Core application |
| F3 | Streamlit Cloud deploy + password protect | Push repo, set OpenAI key as secret, optional password protect | Topic 8.2 · 8.3 · 8.4 | 🌲 Config & data |

---

## Evaluation results (Topic 4.5)

Current run on the 10-scenario ground truth set (`python evaluator.py --no-llm`):

| Metric | Value |
|---|---:|
| recall@5 | 0.41 |
| **precision@5** | **0.58** |
| recall@10 | 0.65 |
| precision@10 | 0.47 |
| **MRR** | **0.82** |

**Reading these:** MRR 0.82 means the first relevant scheme is found at rank 1–2 on average.
Precision@5 of 0.58 means more than half of the top-5 retrieved schemes are in the expected
answer set. Recall@5 of 0.41 is the weakest number — but the per-scenario breakdown
(`eval/eval_report.md`) shows that the complex multi-need scenario (S10) is the main drag,
which is by design: pure retrieval over one embedding can't surface schemes for ALL sub-needs
of a multi-need case. The full `recommend()` pipeline — with decomposer + multi-retrieval merge
— recovers that gap. A v2 of `evaluator.py` should add a pipeline-level metric to capture
that gain.

LLM-as-judge: implemented but currently uninformative (uniform 5/5 across scenarios — the rubric
needs calibration). Useful as a structural placeholder; refinement is queued.

---

## Bootcamp curriculum coverage

| Week / Topic | What the bootcamp teaches | Where it lives in this repo |
|---|---|---|
| **W1 · Topic 1.x** | LLM foundations · Prompt Engineering · f-strings · Delimiters · CO-STAR · Tokens · Hallucinations | `llm.py` · `prompts.py` (CO-STAR + Inner Monologue field) · helpers tested against `tiktoken` |
| **W2 · Topic 2.4** | Chain-of-Thought · Least-to-Most · Better-reasoning techniques | `decomposer.py` (Least-to-Most) · `prompts.py reasoning_steps` field (CoT) |
| **W2 · Topic 2.5** | Multi-action prompts · Inner Monologue · Generated knowledge | Recommender prompt does 7 actions in one call · `reasoning_steps` field is Inner Monologue surfaced as structured data · *Generated Knowledge intentionally not used (see below)* |
| **W2 · Topic 2.6** | Prompt chaining · Decision Chains · Human-in-the-Loop | 5-stage chain (safety → router → decomposer → retrieval → re-rank) · two Decision Chains in `safety.py` + `router.py` · HITL edit-gate on decomposition |
| **W2 · Topic 2.7** | Exception handling · Specific exception types | `_parse_llm_json()` fallback · parent_id hallucination guard · named catches for `RateLimitError`/`APIConnectionError`/`AuthenticationError`/`BadRequestError` · fail-CLOSED vs fail-OPEN choices documented per chain step |
| **W3 · Topic 3.x** | Embeddings · Handling embeddings · RAG · Search beyond keywords | `embed.py` · `retriever.py` · `text-embedding-3-small` with cosine similarity |
| **W4 · Topic 4.2/4.3** | Pre-retrieval optimization · Retrieval improvement | `chunker.py` section-based chunks · `topic_mapper.py` category metadata · multi-sub-need retrieval in `recommender.py` |
| **W4 · Topic 4.4** | Post-retrieval re-rank | CO-STAR re-ranker in `recommender.py` |
| **W4 · Topic 4.5** | RAG Evaluation | `evaluator.py` + 10-scenario ground truth + retrieval@k + LLM-judge framework |
| **W5 · Topic 5.2** | Secure credentials | `.env` via `python-dotenv` · `get_secret()` helper falls back to `st.secrets` for Streamlit Cloud |
| **W5 · Topic 5.3** | Writing & running Python scripts | Modular structure, each `step_N` function in its own module |
| **W6 · Topic 6.x** | Streamlit basics · pip + venv | `requirements.txt` · `.venv/` · `app.py` |
| **W8 · Topic 8.1** | Streamlit deep dive · State · Callbacks | `@st.cache_resource` for retriever · `st.session_state` for HITL state machine and sample-button presets |
| **W8 · Topic 8.3** | Git/GitHub | 8 commits to date; clean per-block history |
| **W8 · Topic 8.5** | Vibe coding | The whole development workflow with the AI coding assistant |
| **W8 · Topic 8.4** | Streamlit Cloud deploy | 🚧 *planned next* |
| **W8 · Topic 8.2** | Password protection | 🚧 *planned next* |

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
