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

    # ---- Case summary -----------------------------------------------------
    st.divider()
    st.subheader("📋 Case summary")
    if response.overall_summary:
        st.markdown(f"_{response.overall_summary}_")
    if response.categories_touched:
        cats_md = " ".join(f"`{c}`" for c in response.categories_touched)
        st.markdown(f"**Categories touched:** {cats_md}")

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

    # ---- Debug panels (optional) -----------------------------------------
    if show_debug:
        st.divider()
        st.subheader("🔍 Debug")

        with st.expander(
            f"All {len(response.retrieved_candidates)} retrieved candidates "
            "(before LLM re-rank)",
        ):
            for c in response.retrieved_candidates:
                st.markdown(
                    f"**{c.title}** · {c.kind} · score `{c.score:.3f}` · "
                    f"matched section `{c.best_section}` · "
                    f"id `{c.parent_id}`"
                )
                if c.categories:
                    st.caption(", ".join(c.categories))
                st.markdown("---")

        with st.expander("Raw LLM output (JSON)"):
            st.code(response.raw_llm_output or "(empty)", language="json")

        with st.expander("Full RecommendationResponse object"):
            st.json(response.to_dict())
