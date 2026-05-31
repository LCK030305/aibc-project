"""Streamlit UI for UC#1 — the SAO Programme Matcher.

Bootcamp-principles cheat sheet
-------------------------------
- Week 7 § Streamlit basics       : main page + sidebar layout, st.text_area,
  st.button, st.spinner, st.metric, st.expander.
- Week 7 § Multi-page ready       : single page now, but the structure
  (one app.py importing pure modules) supports adding a UC#2 page later.
- Week 9 § State management       : ``@st.cache_resource`` caches the
  Retriever (heavy load) across reruns; ``session_state`` carries the
  client situation across button clicks.
- Week 9 § Project structure      : the UI imports from clean modules
  (``retriever``, ``recommender``) and contains no LLM/embedding logic
  itself.
- Week 1 § User-facing copy       : labels are plain English, no jargon.

Run locally
-----------
    .venv\\Scripts\\streamlit.exe run app.py

Deploy
------
Streamlit Community Cloud (Week 9): push to GitHub, secrets =
``OPENAI_API_KEY``, point Streamlit at this file.
"""

from __future__ import annotations

import streamlit as st

from recommender import recommend
from retriever import get_retriever

# ---------------------------------------------------------------------------
# Page config — must be the very first Streamlit call.
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="SAO Co-Pilot · Programme Matcher",
    page_icon="🤝",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Cached resources — retriever load (~50 ms but enough that we don't want
# to repeat it on every interaction). cache_resource is the right primitive
# for "expensive-to-init, share across sessions" objects (Week 9).
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner="Loading SupportGoWhere corpus…")
def load_retriever():
    return get_retriever()


retriever = load_retriever()


# ---------------------------------------------------------------------------
# Static reference data
# ---------------------------------------------------------------------------
SAMPLE_QUERIES = {
    "👩 Single mother, lost job":
        "Single mother of two young children, recently lost her job, "
        "needs financial help to pay rent and utilities.",
    "👴 Dementia respite care":
        "Elderly with dementia, family needs respite care during the day "
        "so they can work.",
    "🆘 Teen suicide warning signs":
        "Teenager showing suicide warning signs, family needs urgent support.",
}

CATEGORIES = [
    "(any)",
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

KINDS = ["(both)", "scheme", "service"]


# ---------------------------------------------------------------------------
# Sidebar — filters + corpus stats + provenance footer.
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("SAO Co-Pilot")
    st.caption("UC#1 — Programme Matcher")

    st.divider()
    st.subheader("Filters")

    selected_category = st.selectbox(
        "Category",
        CATEGORIES,
        index=0,
        help="Restrict search to one SupportGoWhere topic. Leave as '(any)' "
             "to search across all 12 categories.",
    )
    selected_kind = st.radio(
        "Kind",
        KINDS,
        index=0,
        help="`scheme` = government programmes (grants, subsidies). "
             "`service` = community/NGO services (counselling, day-care, etc.).",
    )

    st.divider()
    st.subheader("Tuning")
    k_candidates = st.slider(
        "Candidates the LLM considers",
        min_value=5,
        max_value=30,
        value=15,
        help="Larger pool → more thoroughness, slightly higher cost / latency.",
    )
    n_recommendations = st.slider(
        "Recommendations to return",
        min_value=1,
        max_value=10,
        value=5,
    )
    show_debug = st.checkbox(
        "Show debug panels",
        value=False,
        help="Reveals retrieved candidates, raw LLM output, and full response.",
    )

    st.divider()
    st.subheader("Corpus")
    col_a, col_b = st.columns(2)
    col_a.metric("Records", retriever.n_records)
    col_b.metric("Chunks", retriever.n_chunks)

    st.divider()
    st.caption(
        "**Stack**: OpenAI `text-embedding-3-small` (retrieval) + "
        "`gpt-4.1-mini` (re-ranking, JSON mode). CO-STAR prompting, "
        "section-level chunking, post-retrieval re-ranking. "
        "Built for the MSF/SGPoly AI Champions Bootcamp."
    )


# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------
st.title("🤝 SAO Co-Pilot — Programme Matcher")
st.markdown(
    "**Use Case #1** — surface the most relevant SupportGoWhere schemes and "
    "services for a client's situation, with evidence and eligibility flags. "
    "Reduces SAO time spent resource-hunting so more time goes to families."
)

# ---- Sample query buttons --------------------------------------------------
# Streamlit's text_area can't be modified after instantiation, so we route
# sample buttons through a separate session_state key that becomes the
# default value of the text_area on the *next* rerun.
if "preset_query" not in st.session_state:
    st.session_state.preset_query = ""

st.markdown("**Sample client situations** (click to load, then edit if needed):")
sample_cols = st.columns(len(SAMPLE_QUERIES))
for col, (label, query) in zip(sample_cols, SAMPLE_QUERIES.items()):
    if col.button(label, use_container_width=True):
        st.session_state.preset_query = query
        st.rerun()  # so the text_area picks up the new value

# ---- The text input + submit -----------------------------------------------
client_situation = st.text_area(
    "Client situation",
    value=st.session_state.preset_query,
    height=120,
    placeholder="Describe the client's situation in 1–2 sentences "
                "(e.g. 'Single mother, lost her job, two young children')",
)

submitted = st.button(
    "🔍 Find recommendations",
    type="primary",
    disabled=not client_situation.strip(),
)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
if submitted:
    category = None if selected_category == "(any)" else selected_category
    kind = None if selected_kind == "(both)" else selected_kind

    with st.spinner("Retrieving candidates and re-ranking with the LLM…"):
        try:
            response = recommend(
                client_situation,
                k_candidates=k_candidates,
                n_recommendations=n_recommendations,
                category=category,
                kind=kind,
            )
        except Exception as exc:  # noqa: BLE001 - surface to user
            st.error(f"{type(exc).__name__}: {exc}")
            st.stop()

    # ---- Safety refusal (Topic 2.6 Decision Chain block) -----------------
    if response.blocked:
        st.divider()
        st.error(
            f"🛡️ **Input refused by safety check.**\n\n"
            f"{response.block_reason}",
            icon="🚫",
        )
        st.stop()

    # ---- Case summary -----------------------------------------------------
    st.divider()
    st.subheader("📋 Case summary")
    if response.overall_summary:
        st.markdown(f"_{response.overall_summary}_")
    if response.categories_touched:
        cats_md = " ".join(f"`{c}`" for c in response.categories_touched)
        st.markdown(f"**Categories touched:** {cats_md}")

    # ---- Decomposition (Topic 2.4 Least-to-Most) -------------------------
    if response.decomposition and response.decomposition.get("is_complex"):
        with st.expander(
            f"🧩 Least-to-Most decomposition "
            f"({len(response.decomposition['sub_needs'])} sub-needs)",
            expanded=True,
        ):
            st.caption(
                "This case has multiple distinct needs. We retrieved against "
                "each sub-need separately, then merged candidates."
            )
            for i, sub in enumerate(response.decomposition["sub_needs"], 1):
                st.markdown(f"**Sub-need {i}.** {sub}")

    # ---- Reasoning chain (Topic 2.4 / 2.5) -------------------------------
    if response.reasoning_steps:
        with st.expander("🧠 AI's reasoning (Chain-of-Thought)", expanded=False):
            for i, step in enumerate(response.reasoning_steps, 1):
                # Strip a leading "Step N: " if the LLM included it, to avoid
                # double-numbering with our own enumeration.
                clean = step
                for prefix in (f"Step {i}:", f"Step {i}.", f"{i}.", f"{i})"):
                    if clean.lstrip().startswith(prefix):
                        clean = clean.lstrip()[len(prefix):].strip()
                        break
                st.markdown(f"**Step {i}.** {clean}")

    # ---- Recommendations --------------------------------------------------
    st.divider()
    if not response.recommendations:
        st.info("No recommendations returned. Try widening filters or "
                "rephrasing the situation.")
    else:
        st.subheader(f"🎯 Top {len(response.recommendations)} recommendations")
        for rec in response.recommendations:
            with st.container(border=True):
                head_cols = st.columns([4, 1])
                with head_cols[0]:
                    st.markdown(f"### {rec.title}")
                    st.caption(
                        f"{rec.kind} · ID `{rec.parent_id}` · "
                        f"retrieval score {rec.retrieval_score:.3f}"
                    )
                with head_cols[1]:
                    st.metric("Fit", f"{rec.fit_score}/5")

                st.markdown(f"**Why it fits:** {rec.rationale}")

                if rec.evidence_quote:
                    st.markdown(f"> _{rec.evidence_quote}_")

                if rec.eligibility_flags:
                    st.markdown("**SAO to verify:**")
                    for flag in rec.eligibility_flags:
                        st.markdown(f"- {flag}")

                if rec.categories:
                    cats_inline = " ".join(f"`{c}`" for c in rec.categories)
                    st.caption(f"Categories: {cats_inline}")

                if rec.url:
                    st.link_button("View on SupportGoWhere ↗", rec.url)

    # ---- 🔬 Behind the scenes — every pipeline stage's input/output -----
    if show_debug:
        st.divider()
        st.subheader("🔬 Behind the scenes")
        st.caption(
            "Walk-through of every stage of the prompt chain. Each block "
            "is annotated with the bootcamp topic(s) it implements."
        )

        # Stage 1 — Safety check (Topic 2.6 Decision Chain · Topic 2.7)
        with st.expander(
            "Stage 1 · Safety check  (Topic 2.6 Decision Chain · Topic 2.7 Exception Handling)",
            expanded=False,
        ):
            sr = response.safety_result or {}
            verdict = "✅ safe" if sr.get("is_safe") else "🛡️ unsafe"
            st.markdown(f"**Verdict:** {verdict}")
            if sr.get("reason"):
                st.markdown(f"**Reason:** {sr['reason']}")
            st.caption(
                "Binary Y/N classifier with few-shot exemplars and "
                "`max_tokens=1`. Fail-CLOSED: errors treated as unsafe."
            )

        # Stage 2 — Router classification (Topic 2.6 Decision Chain)
        with st.expander(
            "Stage 2 · Query classifier  (Topic 2.6 Decision Chain — multi-class)",
            expanded=False,
        ):
            cls = response.classification or {}
            st.markdown(f"**Category:** `{cls.get('category', '(none)')}`")
            if cls.get("reason"):
                st.markdown(f"**Reason:** {cls['reason']}")
            st.caption(
                "Multi-class router with JSON-mode output. Fail-OPEN: "
                "errors default to `client_case` so the user still gets results."
            )

        # Stage 3 — Least-to-Most decomposition (Topic 2.4)
        with st.expander(
            "Stage 3 · Decomposition  (Topic 2.4 Least-to-Most)",
            expanded=False,
        ):
            dc = response.decomposition or {}
            st.markdown(
                f"**Is complex:** "
                f"`{dc.get('is_complex', False)}` · "
                f"**Sub-needs:** {len(dc.get('sub_needs', []))}"
            )
            for i, sn in enumerate(dc.get("sub_needs", []), 1):
                st.markdown(f"  {i}. {sn}")
            st.caption(
                "Simple cases get 1 sub-need (pipeline identical to before). "
                "Complex cases get 2–5 sub-needs; retrieval runs per "
                "sub-need then results are merged + deduped."
            )

        # Stage 4 — Retrieval (Topic 3.4 RAG · Topic 4.3 retrieval)
        with st.expander(
            f"Stage 4 · Retrieval  ({len(response.retrieved_candidates)} merged candidates · Topic 3.4 RAG)",
            expanded=False,
        ):
            st.caption(
                "Cosine similarity over text-embedding-3-small vectors. "
                "Deduplicated by parent_id (best section wins). For complex "
                "cases, candidates are the merged top-K across all sub-needs."
            )
            for c in response.retrieved_candidates:
                cats = ", ".join(c.categories) if c.categories else "—"
                st.markdown(
                    f"**{c.title}** · `{c.kind}` · score `{c.score:.3f}` · "
                    f"matched section `{c.best_section}` · id `{c.parent_id}`"
                )
                st.caption(cats)
                st.markdown("---")

        # Stage 5 — CO-STAR prompt sent (Topic 1.2 · Playbook p.26)
        with st.expander(
            "Stage 5a · CO-STAR prompt sent to LLM  (Topic 1.2 / Playbook p.26)",
            expanded=False,
        ):
            st.caption(
                "Six labelled sections (Context, Objective, Style, Tone, "
                "Audience, Response Format) plus XML-delimited candidate "
                "blocks. Same template lives in `prompts.py`."
            )
            st.code(response.prompt_sent or "(empty)", language="markdown")

        # Stage 5 (cont.) — Re-ranker raw JSON  (Topic 2.4/2.5 CoT)
        with st.expander(
            "Stage 5b · Re-ranker raw JSON output  (Topic 2.4 CoT · Topic 2.5 Inner Monologue)",
            expanded=False,
        ):
            st.caption(
                "JSON mode guarantees parseability. `reasoning_steps` is "
                "the Inner Monologue surfaced as a structured field, not "
                "a step-delimiter parse."
            )
            st.code(response.raw_llm_output or "(empty)", language="json")

        # Final — full response object (handy for eval replay)
        with st.expander("Full RecommendationResponse object (JSON dump)"):
            st.json(response.to_dict())
