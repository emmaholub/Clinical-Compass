"""Two-wave orchestration with observable, independently failing sections."""
from __future__ import annotations

import asyncio
import logging

from backend.agents.wave1 import overview_agent, standard_of_care_agent, trials_agent
from backend.agents.wave2 import alt_treatments_agent, label_safety_agent
from backend.data_sources import normalize_disease
from backend.models import StandardOfCareOutput

logger = logging.getLogger(__name__)
WORKER_TIMEOUTS = {"overview": 60, "standard_of_care": 100, "trials": 60,
                   "label_safety": 110, "alternative_treatments": 110}


async def _run_bounded(name, worker):
    try:
        return name, await asyncio.wait_for(worker, timeout=WORKER_TIMEOUTS[name])
    except Exception:
        logger.exception("Worker failed: %s", name)
        return name, {"error": "The evidence source could not be retrieved or verified. Please try again."}


def _has_issues(value):
    if isinstance(value, dict):
        return bool(value.get("error"))
    return bool(getattr(value, "issues", [])) or any(
        bool(getattr(t, "issues", [])) for t in getattr(value, "treatments", [])
    )


async def run_disease_lookup(disease: str) -> dict:
    disease = normalize_disease(disease)
    page = dict(await asyncio.gather(
        _run_bounded("overview", overview_agent(disease)),
        _run_bounded("standard_of_care", standard_of_care_agent(disease)),
        _run_bounded("trials", trials_agent(disease)),
    ))
    standard = page["standard_of_care"]
    if isinstance(standard, StandardOfCareOutput):
        page.update(dict(await asyncio.gather(
            _run_bounded("label_safety", label_safety_agent(disease, standard.drug_names, choices=standard.drugs)),
            _run_bounded("alternative_treatments", alt_treatments_agent(disease, standard.drug_names, choices=standard.drugs)),
        )))
        safety = page["label_safety"]
        if hasattr(safety, "treatments"):
            representative = next((t for t in safety.treatments if t.efficacy), None)
            standard.efficacy = representative.efficacy if representative else None
            standard.efficacy_treatment_name = representative.treatment_name if representative else None
    else:
        for section in ("label_safety", "alternative_treatments"):
            page[section] = {"error": "Treatment details need a verified disease-specific guideline, which could not be retrieved."}
    page["partial"] = any(_has_issues(value) for value in page.values())
    page["disease"] = disease
    return page
