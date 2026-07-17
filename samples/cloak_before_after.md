# CLOAK PII Guard — Before / After

A reference artefact showing exactly what the **CLOAK Free-Text Anonymisation
API** (GovTech Central Privacy Toolkit · Topic 5.5.2) does to a typical
welfare-officer interview note before any LLM sees it.

This is the **first stage** of the SAO Welfare Navigator pipeline — every
LLM-bound request passes through CLOAK first (`pii_filter.py` → `/prod/L4/transform`).
The system is **fail-CLOSED**: if CLOAK is unreachable, the request is
refused rather than letting raw PII reach an external model.

---

## Test sample

> **Note**: All values below are **deliberately synthetic** — see "Why these
> values" at the bottom for the rationale behind each placeholder.

### RAW input (what an SAO would type)

```
Mdm Aaaa Bbbb (S0000001A), born 1 January 1900, lives at Block 999
Test Avenue #00-00 Singapore 999999. Her mobile is 8000 0000 and
her email is test@example.com. Single mother of two children,
recently lost her cleaning job in March 2026, behind on rent.
```

### SANITISED output (what reaches OpenAI)

```
Mdm <PERSON> (<SG_NRIC_FIN>), born <DATE_TIME>, lives at <SG_ADDRESS>.
Her mobile is <PHONE_NUMBER> and her email is <EMAIL_ADDRESS>. Single
mother of two children, recently lost her cleaning job in <DATE_TIME>,
behind on rent.
```

---

## Entity-by-entity breakdown

CLOAK's response includes a per-entity audit trail. Verified output from
a live call against `https://ext-api.cloak.gov.sg/prod/L4/transform`:

| # | Original value | Entity type | Redacted to | CLOAK recogniser |
|---|---|---|---|---|
| 1 | `Aaaa Bbbb` | PERSON | `<PERSON>` | SpacyRecognizer |
| 2 | `S0000001A` | SG_NRIC_FIN | `<SG_NRIC_FIN>` | SgFinRecognizer |
| 3 | `1 January 1900` | DATE_TIME | `<DATE_TIME>` | (date) |
| 4 | `Block 999 Test Avenue #00-00 Singapore 999999` | SG_ADDRESS | `<SG_ADDRESS>` | SgAddressRecognizer |
| 5 | `8000 0000` | PHONE_NUMBER | `<PHONE_NUMBER>` | PhoneRecognizer |
| 6 | `test@example.com` | EMAIL_ADDRESS | `<EMAIL_ADDRESS>` | (email) |
| 7 | `March 2026` | DATE_TIME | `<DATE_TIME>` | (date) |

**Total: 7 entities redacted in a single API call.**

---

## What was DELIBERATELY preserved

Just as important as what got redacted is what didn't. CLOAK's
**replace-with-labelled-token** strategy preserves the *case
characteristics* the retrieval layer needs to match welfare schemes:

| Preserved phrase | Why it matters for matching |
|---|---|
| `"Single mother"` | Triggers MUIS-FAS, ComCare, single-parent priority schemes |
| `"two children"` | Family-size signal for KidSTART, BSG, childcare subsidies |
| `"lost her cleaning job"` | Triggers SkillsFuture Jobseeker Support, ComCare Interim |
| `"behind on rent"` | Triggers Public Rental Scheme, ComCare SMTA |

Without this preservation, the sanitised text would be useless for
matching. The trade-off is intentional: redact *who*, keep *what
happened*.

---

## How the redaction is generated

```
SAO interview notes
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│  pii_filter.sanitize()                                  │
│  ────────────────────                                   │
│  POST /prod/L4/transform                                │
│    auth     : CLOAK-AUTH HMAC-SHA256                    │
│    entities : PERSON, SG_NRIC_FIN, PHONE_NUMBER,        │
│               EMAIL_ADDRESS, SG_BANK_ACCOUNT_NUMBER,    │
│               SG_ADDRESS, DATE_TIME                     │
│    threshold: 0.3  (sidebar-tunable in Streamlit UI)    │
│    nric     : { checksum: False }                       │
└─────────────────────────────────────────────────────────┘
        │
        ▼
sanitised text → all downstream LLM stages (safety, router,
                  decomposer, retrieval, re-rank, faithfulness audit)
```

---

## Why these specific placeholder values

Every field in the test sample is **structurally synthetic** so no one
could mistake it for real PII:

| Field | Value | Why obviously fake |
|---|---|---|
| Name | `Mdm Aaaa Bbbb` | Alphabetical filler; no real Singaporean uses this name |
| NRIC | `S0000001A` | All-zeros pattern with arbitrary check digit; placeholder convention |
| Birthdate | `1 January 1900` | Pre-independence; no living person could plausibly have this DOB |
| Address | `Block 999 Test Avenue #00-00 Singapore 999999` | Real Singapore postal codes are < 838000; `999999` is invalid |
| Phone | `8000 0000` | All zeros after the prefix; no real subscriber would be assigned this |
| Email | `test@example.com` | `example.com` is reserved by IANA (RFC 2606); never routes to a real inbox |

**No part of this sample corresponds to a real person, address, or contact
detail.** It exists purely to verify the CLOAK integration.

---

## Reproducing this output

```bash
# From the project root, with the virtual environment activated:
python pii_filter.py
```

The script will:
1. Send `SMOKE_TEXT` through CLOAK's `/transform` endpoint
2. Print the original and sanitised text
3. List each entity that was redacted with its type

A successful run looks identical to the output above. If you see
`HTTP 403 — Invalid Authentication token!`, see
[CHANGELOG.md](../CHANGELOG.md) under v1.3 — the most common cause is a
JSON-serialisation whitespace mismatch in the HMAC signature (fixed in
this repo by `separators=(",", ":")` in the `json.dumps` call).

---

*This document is a reference artefact for the MSF / Singapore Polytechnic
AI Champions Bootcamp capstone submission. All sample data is synthetic.
For live runs, the same code path is exercised on every Streamlit query and
every `recommend()` call — see the* `🛡️ Privacy guard (CLOAK)` *expander
in the running app for the live equivalent of this static reference.*
