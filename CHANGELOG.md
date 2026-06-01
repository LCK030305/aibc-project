# Changelog

A chronological record of every block of work, grouped into milestones.
Each entry links to the commit SHA so a grader can `git checkout` any
point in the iteration story.

---

## v2.0 — Production-readiness layer  (current)

Polish layer that makes the project demoable, deployable, and defensible.

| Commit | Block | What it added | Bootcamp topic |
|---|---|---|---|
| `483b353` | **PWD + DEPLOY.md** | Password gate (`_require_password()`) at the top of `app.py`; reads `APP_PASSWORD` via `get_secret()`. Step-by-step GitHub + Streamlit Cloud deploy guide. | Topic 8.2 · 8.4 |
| `879b76b` | **README-V2 + PPTX-V2** | README rewrite reflecting all A1–A6 + EVAL; new file-map deck slide for Evaluation; expanded curriculum-coverage table to 15 rows. | Documentation polish |
| `65ab6aa` | **EVAL** | `evaluator.py` with two-metric framework (retrieval@k + LLM judge) over 10 hand-curated scenarios. Generates `eval/eval_report.{json,md}`. Headline metrics: **MRR 0.82 · precision@5 0.58 · recall@10 0.65**. | **Topic 4.5** — RAG Evaluation |

---

## v1.x — Advanced prompting layer (Container A)

The "promote from working to grade-A" pass. Six incremental blocks that
each add one bootcamp-named technique and ship as a stand-alone commit
with smoke tests.

| Commit | Block | What it added | Bootcamp topic |
|---|---|---|---|
| `5fda9fb` | **A7 + COST + A5b** | 5 sample buttons (incl. 🧩 complex + 🚨 malicious) · ⚡ token / latency / USD cost footer · HITL edit-gate that pauses for SAO review of the decomposition before retrieval runs. | demo polish · Topic 2.6 *Performance* + *Human-in-the-Loop* |
| `d8aa1e1` | **A6** | "🔬 Behind the scenes" debug panel — every pipeline stage rendered as a labelled expander, each with its bootcamp-topic annotation. Walks safety → router → decomposer → retrieval → CO-STAR prompt → re-ranker JSON. | UI polish · cross-topic |
| `11d409a` | **A5** | `decomposer.py` — `step_3_decompose()` Least-to-Most prompting. Simple cases pass through unchanged; complex cases split into 2-5 sub-needs, retrieval runs per-sub-need, results merged + deduped by parent. Proven on the 5-need stress case where it surfaces the SPED autism programme a single embedding query would have missed. | **Topic 2.4** — Least-to-Most |
| `a49d32a` | **A4** | Chain-of-Thought / Inner Monologue baked into the recommender prompt as a structured `reasoning_steps` JSON field — keeps JSON-mode parseability while exposing the LLM's thinking to the SAO. | Topic 2.4 · 2.5 |
| `4e8101e` | **A3** | `router.py` — `step_2_classify_query()` Decision Chain multi-class router (`client_case` / `scheme_lookup` / `general_question` / `out_of_scope`). Fail-OPEN so retrieval is never accidentally blocked. | **Topic 2.6** — Decision Chain |
| `3c0c3fb` | **A2** | `safety.py` — `step_1_safety_check()` Decision Chain guard against prompt injection / jailbreak; fail-CLOSED. Named OpenAI exception catches in `recommender.py` for `RateLimitError`, `APIConnectionError`, `AuthenticationError`, `BadRequestError` with friendly user-facing messages. | **Topic 2.6 + 2.7** |
| `e901131` | **A1** | Bootcamp-style helpers in `llm.py` — `get_completion_from_messages()` (messages-list with system+user roles), `num_tokens_from_message_rough()` (tiktoken), `get_secret()` (`st.secrets` → `.env` fallback). Foundation for A2–A6. | Topic 1.3 · 5.2 · 2.7 |

---

## v1.0 — Baseline  (`fc00fa9`)

End-to-end working pipeline: Playwright scraper → section-level chunker
→ OpenAI embeddings → cosine retriever with dedup + filters → CO-STAR
re-ranker (`gpt-4.1-mini`, JSON mode) → Streamlit UI.

Corpus: 307 records (219 schemes + 88 services) / 2,147 section chunks /
12 SGW topic categories. Topic mapping derived by Playwright-rendering
each `/topics/<slug>` page and intercepting the XHR JSON for item IDs.
Patched 11 corpus-missing items the sitemap had dropped (post-sitemap
SGW additions).

Initial bootcamp-principles in place: CO-STAR (Topic 1.2 + Playbook
p.26), XML delimiters (Topic 1.3), embeddings + RAG (Topic 3.4), single-
shot multi-action prompt (Topic 2.5), retrieval@k-ready retriever
(Topic 4.3), Streamlit UI (Topic 6.x).

---

## Rejected with reasons (in the spirit of mature engineering judgment)

| Considered | Rejected because | Topic |
|---|---|---|
| **LangChain** | The bootcamp explicitly teaches Native Prompt Chaining over LangChain for foundational understanding. Our raw-`get_completion` style matches the Week 2 Part 3 notebook exactly. | Topic 2.6 *"Our two cents"* |
| **Generated Knowledge** (Topic 2.5.3) | Conflicts with our RAG citation discipline — we ground every recommendation in verbatim SGW corpus text. Letting the LLM "generate knowledge" risks contradicting the official policy text. | Topic 2.5.3 |
| **Agentic tool-calling** for UC#1 | Single-shot RAG with CoT re-rank is faster, cheaper, more deterministic, and easier to evaluate. Agents add latency + cost + variance without measurable quality gain on this task. **Deferred to UC#2** (eligibility verification), where tool-calling is genuinely needed. | Topic 5.x · Week 6 Archetype #4 |
| **Regex fallback** if CLOAK is down | Fail-OPEN risks leaking PII the regex misses. For a public-sector demo, **block and tell the officer** is the correct stance. | Topic 5 |

---

## Coming next (Container B and beyond)

| Block | Status |
|---|---|
| **B1** `pii_filter.py` (CLOAK FTA `/transform`) | 🚧 pending CLOAK API key from LMS |
| **B2** UI: Raw / Sanitised side-by-side panes | 🚧 pending B1 |
| **B3** Sample interview notes with PII baked in | 🚧 pending B2 |
| **GitHub push + Streamlit Cloud deploy** | 🚧 pending owner action (see `DEPLOY.md`) |
| **UC#2** Eligibility verifier (Pain Point #2) | Future work |
| **Containerise** (Xtra Topic 1, Docker) | Future work |
