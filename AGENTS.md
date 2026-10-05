# Clinical Compass — MGT 409 final project

Patient-facing disease lookup. User types a disease → site shows, in order:
1. **Overview** — plain language for a 10–15-year-old
2. **Standard of care** — first-line treatment + efficacy ("success rate") + guideline citation
3. **Safety of standard of care** — common side effects, discontinuation rate, boxed warning
4. **Other common treatments** — same safety fields for each
5. **Questions for your Doctor** — three calm, disease-aware prompts for the patient's next doctor visit
6. **Clinical trials** — US, recruiting, Phase 2+, enrollment ≥ 100

Test disease while building: **rheumatoid arthritis** (methotrexate first-line; JAK inhibitors like tofacitinib/upadacitinib have boxed warnings).

## Stack
- Frontend: React + Vite + TypeScript in `frontend/`
- Backend: FastAPI + PydanticAI in `backend/` (from project root, run `.venv/bin/uvicorn backend.main:app --port 8000`)
- LLM via Portkey (`PORTKEY_API_KEY` in `.env`)
- Python virtual environment in `.venv/`; dependencies in `requirements.txt`
- Deploy later on Render (backend = web service, frontend = static site)

## Agent design (hierarchy)
- **Boss agent**: normalizes the disease name, delegates to workers in parallel (async), assembles the final page JSON
- **Workers** (one per section): `overview_agent`, `standard_of_care_agent`, `label_safety_agent`, `alt_treatments_agent`, `trials_agent`
- Every worker returns a strict Pydantic model. No free-text blobs.

## Data sources (free, no key required)
- **openFDA drug labels**: `https://api.fda.gov/drug/label.json?search=openfda.generic_name:"<drug>"`
  - Use fields `boxed_warning`, `adverse_reactions`, `clinical_studies`, `indications_and_usage`
  - Prefer the innovator/brand label (search `openfda.brand_name`); generic ER labels can differ
  - Discontinuation rate is a sentence inside `adverse_reactions` — extract it with the LLM, quote the source sentence
- **openFDA FAERS**: `https://api.fda.gov/drug/event.json` with `count=patient.reaction.reactionmeddrapt.exact`
  - Label FAERS results "most frequently reported," never as rates or incidence
- **DailyMed SPL API** (backup for full label text + link users can click)
- **ClinicalTrials.gov API v2**: `https://clinicaltrials.gov/api/v2/studies` — filter condition, country = United States, status = RECRUITING, phase 2/3, enrollment ≥ 100
- **Standard of care**: no API — the agent uses web search and must cite a guideline (e.g., ACR for RA)

## House rules
- **Never invent numbers.** Every number has a `source_url` and a `source_quote`. If not found, return `null` and show "Not reported in label."
- Boxed warnings come from the label, not FAERS.
- Show a medical disclaimer at the top: educational only, not medical advice, talk to your doctor.
- Overview: short sentences, no jargon, ~6th-grade reading level.
- Never commit `.env` or secrets; keep a `.gitignore`.
- Build and test each data tool as a plain Python function before wrapping it in an agent.
- Cache API responses locally while developing (openFDA has rate limits).
- UI: clean, calm, trustworthy (medical, not flashy). Each section is a card; boxed warnings in a red-bordered callout.

## Product context

- Clinical Compass helps newly diagnosed patients and their families understand a disease and its treatment options in plain language.
- Audience: patients and caregivers, not clinicians. Tone: calm, clear, trustworthy, never alarming.
- Business model (for context only): free for patients/hospitals; future revenue from payer partnerships. Don't build payments or logins yet.
- Include three patient-friendly questions for the doctor visit after other common treatments and before clinical trials. Keep them educational and avoid telling patients which treatment to choose.

## Evidence and verification requirements

- Read the fetched guideline before choosing drugs. Keep disease-stage and comorbidity qualifications. Identify the guideline's country; do not describe NICE recommendations as US guidance.
- Wave 1 returns individual drug names, first-line/alternative roles, and a guideline citation for each. Wave 2 splits the same list by role.
- PubMed search IDs are not evidence: fetch the abstract findings. Use disease-specific trial outcomes, population, comparator and follow-up instead of a universal "success rate."
- Exact quotes are checked against canonical rendered source text at the cited URL. Clinical findings may reference a supplied passage ID; the backend copies the actual fetched passage. Never accept an LLM's invented passage.
- A failed retrieval is not proof a rate is unreported. UI missing-data messages must explain the retrieval/verification limit. Do not hide failures by returning empty successful treatment arrays.
- Boxed warnings come only from the selected FDA/DailyMed label. FAERS reports do not establish rates, causation, prescribing volume, or boxed warnings.
- IQVIA NPA/NSPI prescription-volume rankings require licensed data and appropriate usage rights. No licensed source is currently connected. Guidelines are not prescription-volume rankings.
- Backend regression tests must exercise the real two-wave coordinator with fixture providers. Live browser checks must assert populated treatment/evidence fields, not just HTTP 200.
