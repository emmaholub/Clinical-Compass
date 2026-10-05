# Clinical Compass

Clinical Compass translates a new diagnosis into plain language, explains treatment options and their evidence and safety context, prepares patients for conversations with their doctor, and helps them find larger recruiting US clinical trials. It is for patient and caregiver education, not clinical decision-making.

## Run locally

From this directory, activate the existing virtual environment or use its executables directly:

```sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Set `PORTKEY_API_KEY` in `.env` (or your shell environment). `.env.example` contains the supported settings. The API loads `.env` without overwriting existing environment values. No key belongs in frontend code. `PORTKEY_MODEL` is a gateway model alias; the gateway's routing determines the actual provider/model and its price. Disease searches have a configurable in-memory per-connection rate limit. API access logs are disabled in the Render start command because the requested condition appears in the URL.

In a second terminal:

```sh
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Open http://127.0.0.1:5173. The development proxy forwards `/api` to port 8000. The API docs at `/docs` are developer documentation, not the patient website.

## Audit of the original build

The earlier test suite mocked the entire boss and only checked overview fields. Consequently, HTTP 200, empty safety arrays, and unsupported treatment defaults could all pass. Those checks did not establish that the treatment sections worked.

| Plan steps | Corrected behavior |
| --- | --- |
| 1–2: setup and schemas | Environment is loaded; actual PydanticAI calls receive the output schema; unexpected fields are rejected. First-line and alternative roles are explicit. |
| 3: API tools/cache | JSON and text caches expire after a day and are written atomically. PubMed search is followed by abstract retrieval. DailyMed fallback fetches the SPL. |
| 4–6: two waves | Overview, guideline plan and trial search run concurrently. The verified drug list feeds separate first-line and alternative safety workers. |
| 7: one label per drug | Brand name is resolved from the generic name where known; a 404 triggers generic fallback. Combination-product labels are excluded for single-drug searches. Complete labels, brand/innovator status and revision date determine selection. The selected formulation's label is linked. |
| 8: source validation | URL-specific passage/quote checks apply to guideline choices, common side effects, efficacy, discontinuation and published safety findings. Numerical claims must occur in the supporting quote. One bounded model retry can correct invalid citations. Unsupported claims are removed and flagged. |
| 9–10: limits/partial results | Overview: 60 seconds; guideline plan: 100; trial search: 60; each safety section: 110. Each structured extraction has at most two LLM requests. At most six drugs are allowed; each drug has a 100-second timeout and a shared limit of ten evidence HTTP attempts. Guideline retrieval is capped at 30 attempts; recruiting-trial retrieval is capped at three pages, with one transient retry per page. Failed dependencies are skipped and per-drug failures retain other results. |
| 11–12: API/UI | The page displays readable treatment cards, evidence context and expandable exact quotes, label warnings, qualified FAERS reports, and honest missing-data notes. API failures no longer masquerade as successful empty results. |
| 13: testing | Automated tests exercise both waves for RA, diabetes and Alzheimer's, including source validation, wrong-label prevention, unknown diseases, request limits and partial failures. Opt-in live browser checks assert actual populated fields. |
| 14: deployment | Build dependencies are pinned. Render uses `npm ci`, API health checks, a configured frontend API URL, and an explicit CORS origin. No deployment has been performed. |

## Sources and limits

Guideline retrieval uses public NICE recommendations, with a cached NICE search for additional diseases and a PubMed guideline search/abstract fallback. These public searches have no paid per-call search fee; Portkey LLM calls are billed separately. Known disease URLs accelerate retrieval; no disease treatment recommendations are hardcoded. The UI explicitly identifies NICE as a UK source. UK and US recommendations and availability can differ; this is not a comprehensive US guideline database.

Published evidence comes from fetched PubMed abstracts plus FDA label clinical-study sections. The app currently does not retrieve every paywalled/full-text article or the entire published literature. A missing rate means it was not verified in the retrieved evidence, not that it does not exist. Findings may come from different populations, formulations and regimens; the UI shows the study context. Quote and number validation establish traceability, not a guarantee of clinical interpretation. Clinical review is needed before presenting this prototype as a clinically validated service.

FAERS is supplemental voluntary reporting. Reports are not incidence rates or proof of causation. FDA boxed warnings are copied from the selected label. IQVIA NPA/NSPI is not connected: authentic prescribing rankings need a licensed dataset/API contract and permission for this product's use. It would be misleading to manufacture rankings from labels, guidelines or FAERS.

ClinicalTrials.gov discovery includes studies with US locations, recruiting overall status, Phase 2/3/4 and planned enrollment at least 100. It is limited to three pages. A study team confirms individual eligibility and whether a specific US site has openings.

## Verify

```sh
.venv/bin/python -m pytest -q
cd frontend
npm run build
```

With both servers running and Chrome installed, opt-in live browser tests query public sources and make billable Portkey calls:

```sh
LIVE_EVIDENCE_TESTS=1 npm run test:browser
```

The audit includes 21 backend tests and three live browser lookups (RA, type 2 diabetes, Alzheimer's). Guideline retrieval was also checked for asthma and breast cancer; those checks are not full end-to-end clinical validation.

## Render configuration

Use `render.yaml` to create the backend and static frontend services. Set the backend's `PORTKEY_API_KEY` secret and its `CORS_ORIGINS` to the actual frontend HTTPS origin. Set the frontend's build-time `VITE_API_BASE_URL` to the backend HTTPS origin and rebuild the frontend after changing it. Keep `VITE_API_BASE_URL` blank locally. The local disk cache is disposable and may reset on redeploy. The request limiter is process-local; it reduces accidental/high-frequency use but does not enforce a durable account-wide spending cap across restarts or multiple backend instances. Set a Portkey budget alert/limit before opening the endpoint to broad public traffic.
