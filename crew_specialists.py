"""CrewAI Agent definitions — Topic 5.5 Multi-Agent Systems.

Defines 14 agents total:
- **1 Coordinator** (Manager / Triage) — reads the sanitised case, decides
  which 2-4 SGW category specialists are most relevant for this client.
- **12 Specialists** — one per SupportGoWhere topic category. Each has a
  role/goal/backstory tuned to its domain and a category-filtered
  retriever tool (Topic 5.5 §Tools, deterministic task-level placement).
- **1 Aggregator** — synthesises specialist drafts into a single ranked
  top-5 recommendation list, preserving our Topic 4.4 verbatim-citation
  discipline.

Topic 5.5 §Focus principle is followed strictly: each specialist sees
ONLY its own domain's candidates (via its category-filtered tool), not
the full 307-record corpus. Coordinator sees only category labels +
case text, not any scheme details. Aggregator sees only specialist
outputs, not the raw corpus.

Topic 5.5 §Memory:
- Short-term + entity memory are enabled at Crew level by default in
  modern CrewAI (1.x). Persisted long-term memory is OFF — appropriate
  for stateless welfare-matcher demos where each query is independent.
"""

from __future__ import annotations

from crewai import LLM, Agent

from llm import get_secret
from retriever_tool import CategoryRetrieverTool

# Single LLM instance reused across all agents — gpt-4.1-mini per Q5
# decision (consistency + cost control). CrewAI's LLM wraps LiteLLM under
# the hood; configuring the OpenAI key via env var (already loaded by
# llm.py's load_dotenv at import time).
SHARED_LLM = LLM(model="gpt-4.1-mini", temperature=0.0)


# ---------------------------------------------------------------------------
# 12 specialist agent definitions, one per SGW category
# ---------------------------------------------------------------------------

# (sgw_category_slug, display_role, focus_description)
SPECIALIST_SPECS: list[dict] = [
    {
        "category": "financial-support",
        "role": "Financial Welfare Specialist",
        "goal": (
            "Identify the most relevant financial-assistance schemes "
            "for this client — ComCare, MUIS-FAS, rental support, "
            "utility relief, employment grants."
        ),
        "backstory": (
            "Frontline ComCare officer with 10 years' experience at an "
            "MSF Social Service Office. Expert at gauging household "
            "income tiers and matching them to the right financial-aid "
            "scheme, including SkillsFuture Jobseeker Support and ad-hoc "
            "interim assistance."
        ),
    },
    {
        "category": "family-parenting",
        "role": "Family and Parenting Specialist",
        "goal": (
            "Surface the most relevant family-strengthening, parenting, "
            "and childcare support for this client."
        ),
        "backstory": (
            "Family Service Centre senior social worker. Familiar with "
            "KidSTART, Family Strengthening, Baby Support Grant, MOE-FAS, "
            "and the full childcare-subsidy landscape."
        ),
    },
    {
        "category": "caregiving-support",
        "role": "Caregiving Support Specialist",
        "goal": (
            "Identify respite care, caregiver grants, and home-care "
            "services for this client's caregiving load."
        ),
        "backstory": (
            "AIC (Agency for Integrated Care) liaison with deep knowledge "
            "of Home Caregiving Grant, EASE, dementia day care, home "
            "personal care, and the CREST network."
        ),
    },
    {
        "category": "healthcare",
        "role": "Healthcare Affordability Specialist",
        "goal": (
            "Find healthcare-cost relief: CHAS, MediFund, MediShield "
            "premium subsidies, Pioneer/Merdeka package items."
        ),
        "backstory": (
            "Polyclinic social-services attache with hands-on knowledge "
            "of subsidies for outpatient care, chronic-disease management, "
            "and means-tested medical financial assistance."
        ),
    },
    {
        "category": "mental-health",
        "role": "Mental Health Specialist",
        "goal": (
            "Match the client with appropriate mental-health and youth "
            "support services."
        ),
        "backstory": (
            "Clinical psychologist consultant to the IMH community-care "
            "network. Familiar with CREST-Youth, SOS, youth mental-health "
            "outreach, and school-based counselling pathways."
        ),
    },
    {
        "category": "counselling-crisis",
        "role": "Crisis and Counselling Specialist",
        "goal": (
            "Surface counselling, crisis-line, and family-violence "
            "support relevant for this client."
        ),
        "backstory": (
            "Senior counsellor at a Family Service Centre with experience "
            "in PAVE (family violence), Local Outreach to Suicide "
            "Survivors, and Maintenance Support frameworks."
        ),
    },
    {
        "category": "disability-support",
        "role": "Disability Support Specialist",
        "goal": (
            "Identify disability-related schemes: ATF, employment "
            "support for PWDs, SPED, transport subsidies."
        ),
        "backstory": (
            "SG Enable case manager familiar with the Assistive Technology "
            "Fund, Enabling Employment Credit, and the full PWD "
            "ecosystem."
        ),
    },
    {
        "category": "children-youth",
        "role": "Children and Youth Specialist",
        "goal": (
            "Find services and grants for children and youth: KidSTART, "
            "Baby Bonus, BSG, school assistance."
        ),
        "backstory": (
            "Early childhood social worker covering KidSTART, ECDA "
            "subsidies, and youth development schemes."
        ),
    },
    {
        "category": "education-learning",
        "role": "Education and Learning Specialist",
        "goal": (
            "Surface education subsidies, training grants, and "
            "SkillsFuture-related opportunities for this client."
        ),
        "backstory": (
            "MOE FAS officer turned community educator. Familiar with "
            "school-fee assistance, KIFAS, CDAC/SINDA support, "
            "Mendaki, and adult-learning grants."
        ),
    },
    {
        "category": "housing-shelters",
        "role": "Housing and Shelter Specialist",
        "goal": (
            "Identify public-rental, CPF housing grants, and emergency "
            "shelter options for this client."
        ),
        "backstory": (
            "HDB Branch Office case officer experienced with Public "
            "Rental, Fresh Start, CPF Housing Grant, and emergency "
            "shelter referrals."
        ),
    },
    {
        "category": "retirement-legacy",
        "role": "Senior Care and Retirement Specialist",
        "goal": (
            "Surface senior-care and retirement support: Silver Support, "
            "ElderFund, Pioneer/Merdeka, AAC services."
        ),
        "backstory": (
            "Council for Third Age coordinator familiar with senior "
            "financial support, Active Aging Centres, and end-of-life "
            "planning resources."
        ),
    },
    {
        "category": "work-employment",
        "role": "Work and Employment Specialist",
        "goal": (
            "Identify employment-related help: SkillsFuture, WorkPro, "
            "Workfare, retraining grants."
        ),
        "backstory": (
            "WSG / e2i case manager experienced with Jobseeker Support, "
            "training-allowance schemes, and job-matching for low-wage "
            "workers."
        ),
    },
]


def _build_specialist(spec: dict) -> Agent:
    """Construct one specialist Agent with its category-filtered tool."""
    tool = CategoryRetrieverTool(category=spec["category"])
    return Agent(
        role=spec["role"],
        goal=spec["goal"],
        backstory=spec["backstory"],
        tools=[tool],
        llm=SHARED_LLM,
        allow_delegation=False,
        verbose=False,
        max_iter=3,  # Cap reasoning loops — focus principle (Topic 5.5)
    )


# Map: sgw_category_slug -> ready-to-run Agent
SPECIALISTS: dict[str, Agent] = {
    spec["category"]: _build_specialist(spec) for spec in SPECIALIST_SPECS
}

# Convenience: category label (for the Coordinator's triage prompt)
CATEGORY_LABELS = [spec["category"] for spec in SPECIALIST_SPECS]


# ---------------------------------------------------------------------------
# Coordinator (Triage Manager) and Aggregator agents
# ---------------------------------------------------------------------------

COORDINATOR = Agent(
    role="Case Triage Coordinator",
    goal=(
        "Read the sanitised client case and decide which 2 to 4 SGW "
        "category specialists should be engaged. Respond ONLY with a "
        "JSON object: {\"categories\": [\"category-slug\", ...]}. "
        "Select from this exact list: "
        + ", ".join(CATEGORY_LABELS)
    ),
    backstory=(
        "Senior MSF case-conference supervisor with 15 years' experience "
        "triaging diverse welfare cases. Skilled at distilling complex "
        "multi-need situations into a small set of high-value specialist "
        "consultations — never wastes specialist time on irrelevant "
        "domains."
    ),
    llm=SHARED_LLM,
    allow_delegation=False,
    verbose=False,
    max_iter=2,
)


AGGREGATOR = Agent(
    role="Recommendation Aggregator",
    goal=(
        "Synthesise the specialist drafts into a single ranked top-5 "
        "recommendation list. Preserve VERBATIM evidence quotes from "
        "each specialist's source text. Drop duplicates. If specialists "
        "disagree on fit, weigh by specificity of evidence."
    ),
    backstory=(
        "Senior MSF case-conference chair who has spent a decade "
        "synthesising multidisciplinary recommendations into clean, "
        "evidence-grounded action plans for frontline officers."
    ),
    llm=SHARED_LLM,
    allow_delegation=False,
    verbose=False,
    max_iter=2,
)


CASE_DOCUMENTATION_OFFICER = Agent(
    role="Case Documentation Officer",
    goal=(
        "Take the Aggregator's ranked top-5 and produce a single "
        "plain-English case summary — written FOR THE FAMILY "
        "(empathetic, no jargon, no scheme codes in the flowing prose) "
        "but complete enough that the SAO can also file it as the "
        "case-record entry. Cover: what schemes were recommended, why "
        "they suit this family, what the family can expect next, "
        "what the SAO will follow up on."
    ),
    backstory=(
        "MSF Social Assistance Officer with 8 years' practice. Uses "
        "the same plain-English summary for both case-record filing "
        "and communication with families — MSF's approach favours "
        "accessible language that any reader can understand, whether "
        "an internal auditor, another SAO on handover, or the family "
        "receiving the help. Skilled at explaining eligibility gates "
        "and next steps in warm, direct language."
    ),
    llm=SHARED_LLM,
    allow_delegation=False,
    verbose=False,
    max_iter=2,
)
