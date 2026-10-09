"""Wave 1: grounded treatment planning, overview, and trial discovery."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from backend.data_sources import CachedJsonClient, clinical_trials, normalize_disease, overview_documents, search_guidelines
from backend.llm import generate
from backend.models import ClinicalTrial, OverviewOutput, StandardOfCareOutput, TrialsOutput
from backend.validation import checked_value, verified

DISCLAIMER = "Educational only, not medical advice. Talk with your doctor."


async def overview_agent(disease: str) -> OverviewOutput:
    docs = await asyncio.to_thread(overview_documents, disease)
    if not docs:
        raise LookupError("No authoritative disease overview source could be retrieved")
    return await generate(
        OverviewOutput,
        "Write an overview at a sixth-grade reading level using only the supplied authoritative disease document. "
        "Explain what it is, common symptoms, and known causes or risk factors in calm language. "
        "Copy one contiguous source quote exactly and never fill gaps from memory.",
        json.dumps({"disease": disease, "documents": [doc.prompt() for doc in docs]}),
    )


async def standard_of_care_agent(disease: str) -> StandardOfCareOutput:
    disease = normalize_disease(disease)
    docs = await asyncio.to_thread(search_guidelines, disease)
    if not docs:
        raise LookupError("No disease-specific guideline could be retrieved")
    def validate(data):
        problems = []
        if normalize_disease(data.disease) != disease:
            problems.append(f"Copy the requested disease name exactly: {disease}")
        if not verified(data.guideline_source, docs):
            problems.append("guideline_source must match a fetched guideline")
        for drug in data.drugs:
            if not verified(drug.guideline_source, docs):
                problems.append(f"The quote for {drug.name} must match a fetched guideline")
        return problems
    result = await generate(
        StandardOfCareOutput,
        "Identify treatment options ONLY for the requested disease from the supplied guideline or authoritative government/FDA evidence. "
        "Copy the input disease name exactly in the output disease field. "
        "Describe the population, disease stage, and conditions that change first-line choices. "
        "A guideline recommendation is not a prescription for this person. "
        "Name the evidence type accurately (for example, NIH disease information or FDA label rather than calling it a clinical guideline). Choose at most five named generic "
        "medicines (not classes or doses), including one representative first-line option "
        "and the other guideline-supported options as alternatives. Explain equivalent first-line "
        "alternatives accurately; do not imply they are inferior. "
        "A fixed-dose combination must be named as the combination, using the exact name in "
        "the guideline. Never represent components of a mandatory combination regimen as "
        "stand-alone alternatives. State all required companion treatments prominently in the "
        "treatment_name and descriptions. Every medicine must have a quote "
        "from the guideline that names it and supports its use in this disease. Do not recommend "
        "a drug named only in a 'do not offer' passage. Return disease, treatment_name, treatment_type, "
        "description, drugs, guideline_name, guideline_source, medical_disclaimer and drug_names. "
        "Set efficacy to null here; a later worker supplies outcome-specific trial results. "
        "Do not supply prescribing rankings. Keep descriptions concise and avoid numerical claims "
        "outside sourced fields. For stage-dependent conditions, explicitly say there is no single "
        "first-line treatment for every patient.",
        json.dumps({"disease": disease, "documents": [d.prompt() for d in docs],
                    "medical_disclaimer": DISCLAIMER}), validate=validate,
    )
    if normalize_disease(result.disease) != disease:
        raise ValueError("Treatment evidence belongs to another disease")
    if not verified(result.guideline_source, docs):
        raise ValueError("Guideline quote did not match the fetched source")
    valid = []
    result.issues = []
    for drug in result.drugs:
        if verified(drug.guideline_source, docs) and drug.name.casefold() in drug.guideline_source.source_quote.casefold():
            valid.append(drug)
        else:
            result.issues.append(f"Evidence for {drug.name} could not be verified.")
    result.drugs = valid
    if not any(drug.role == "first_line" for drug in valid):
        raise ValueError("No first-line option had a verified guideline citation")
    result.drug_names = [drug.name for drug in valid]
    result.efficacy = checked_value(result.efficacy, docs)
    result.medical_disclaimer = DISCLAIMER
    result.prescribing_volume_status = "IQVIA National Prescription Audit / National Sales and Prescription Insights requires licensed access and is not connected."
    return result


def _trial_from_study(study: dict[str, Any]) -> ClinicalTrial | None:
    protocol = study.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    design = protocol.get("designModule", {})
    contacts = protocol.get("contactsLocationsModule", {})
    enrollment = design.get("enrollmentInfo", {}).get("count")
    phase_values = design.get("phases", [])
    locations = contacts.get("locations", [])
    us_locations = [
        loc for loc in locations if loc.get("country", "").lower() == "united states"
    ]
    if (
        status.get("overallStatus") != "RECRUITING"
        or not any(phase in {"PHASE2", "PHASE3", "PHASE4"} for phase in phase_values)
        or type(enrollment) is not int
        or enrollment < 100
        or not us_locations
    ):
        return None
    loc = us_locations[0]
    nct_id = identification.get("nctId", "")
    return ClinicalTrial(
        title=identification.get("briefTitle", "Untitled study"),
        brief_summary=protocol.get("descriptionModule", {}).get("briefSummary", ""),
        phase=", ".join(phase_values),
        enrollment=enrollment,
        location=", ".join(filter(None, [loc.get("city"), loc.get("state"), loc.get("country")])),
        sponsor=protocol.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name"),
        recruitment_status=status.get("overallStatus", ""),
        study_url=f"https://clinicaltrials.gov/study/{nct_id}",
        source={
            "source_url": f"https://clinicaltrials.gov/api/v2/studies/{nct_id}",
            "source_quote": json.dumps(design.get("enrollmentInfo", {})),
        },
    )


async def trials_agent(
    disease: str, *, data_client: CachedJsonClient | None = None
) -> TrialsOutput:
    """Return only qualifying US recruiting phase 2/3 trials with enrollment >= 100."""
    payload = await asyncio.to_thread(clinical_trials, disease, client=data_client)
    trials = [
        trial
        for study in payload.get("studies", [])
        if (trial := _trial_from_study(study)) is not None
    ]
    return TrialsOutput(
        disease=disease,
        filters_applied=[
            "United States location",
            "RECRUITING",
            "Phase 2, Phase 3 or Phase 4",
            "Enrollment >= 100",
        ],
        trials=trials,
    )


async def run_wave_one(disease: str) -> tuple[
    OverviewOutput, StandardOfCareOutput, TrialsOutput
]:
    """Run all Wave 1 workers concurrently."""
    return await asyncio.gather(
        overview_agent(disease),
        standard_of_care_agent(disease),
        trials_agent(disease),
    )
