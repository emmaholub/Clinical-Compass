"""Wave 2: per-drug evidence extraction, with independent failures."""
from __future__ import annotations

import asyncio
import json
import logging
import httpx

from pydantic import Field

from backend.data_sources import CachedJsonClient, Document, label_documents, openfda_faers, published_findings
from backend.llm import generate
from backend.models import (
    AlternativeTreatment, AlternativeTreatmentsOutput, DrugChoice, LabelSafetyOutput,
    SafetyOutput, SourceMetadata, SourcedValue, StrictModel,
)
from backend.validation import checked_value, verified, value_problem

logger = logging.getLogger(__name__)


class ExtractedSafety(StrictModel):
    common_side_effects: list[str]
    common_side_effects_source: SourceMetadata | None
    discontinuation_rate: SourcedValue | None
    efficacy: SourcedValue | None
    published_trial_evidence: list[SourcedValue] = Field(default_factory=list, max_length=3)


def fetch_evidence(disease: str, drug: str):
    api = CachedJsonClient(request_limit=10)
    try:
        return _fetch_evidence(disease, drug, api)
    finally:
        api.close()


def _fetch_evidence(disease: str, drug: str, api: CachedJsonClient):
    title, labels = label_documents(drug, client=api)
    issues = []
    try:
        findings = published_findings(disease, drug, client=api)
    except Exception:
        findings = []
        issues.append("Published studies could not be retrieved; the selected FDA label is available.")
        logger.exception("Publication retrieval failed for %s", drug)
    # FAERS is supplemental; it cannot replace label adverse reactions or warnings.
    try:
        events = openfda_faers(drug, client=api)
        reactions = [row["term"] for row in events.get("results", [])]
    except Exception:
        reactions = []
        logger.info("FAERS unavailable for %s", drug)
    return title, labels, findings, reactions, issues


async def treatment_evidence(disease: str, choice: DrugChoice) -> SafetyOutput:
    title, labels, findings, reactions, issues = await asyncio.to_thread(fetch_evidence, disease, choice.name)
    docs = labels + findings
    passages = {}
    for i, doc in enumerate(docs):
        for start in range(0, min(len(doc.text), 80000), 2800):
            passages[f"d{i}p{start}"] = Document(doc.source_url, doc.title, doc.text[start:start + 3600], doc.kind)
    def resolve_passages(data):
        sources = [data.common_side_effects_source]
        sources += [value.source for value in [data.efficacy, data.discontinuation_rate, *data.published_trial_evidence] if value]
        for source in sources:
            if source and source.passage_id in passages:
                passage = passages[source.passage_id]
                if str(source.source_url) == passage.source_url:
                    source.source_quote = passage.text
                    source.source_title = passage.title
    def validate(data):
        resolve_passages(data)
        problems = []
        for name in ("efficacy", "discontinuation_rate"):
            problem = value_problem(getattr(data, name), docs)
            if problem:
                problems.append(name + ": " + problem)
        if data.common_side_effects and not verified(data.common_side_effects_source, labels):
            problems.append("common_side_effects_source must quote the label")
        for i, value in enumerate(data.published_trial_evidence):
            problem = value_problem(value, findings)
            if problem:
                problems.append(f"published_trial_evidence[{i}]: {problem}")
        return problems
    extracted = await generate(
        ExtractedSafety,
        "Extract safety and efficacy ONLY for the requested drug in the requested disease. "
        "Use the FDA adverse-reactions section for common_side_effects, as plain-language names "
        "without numerical rates, and supply one exact supporting passage. Exclude other indications. "
        "For efficacy, prefer a randomized trial of this drug or its exact regimen in this disease. "
        "Prefer placebo-controlled monotherapy findings over comparisons between dose schedules. "
        "Report the actual endpoint (for example change on a memory scale or HbA1c), never relabel "
        "a score change or slowing of decline as a cure rate or percentage of patients helped. "
        "Include population, follow-up, and comparator in every numeric result when available. "
        "Discontinuation means stopping because of adverse events, not all-cause dropout; do not "
        "confuse the percentage affected by a side effect with the percentage who stopped. "
        "The exact quote must contain ALL numbers used anywhere in that result including time, "
        "dose, endpoint name and comparator. Use a contiguous passage including context. "
        "Published trial evidence is for additional safety or tolerability findings only. "
        "Use null for context fields whose numbers are not contained in the quote. A shorter "
        "fully supported statement is useful. Do not repeat the disease name with digits in "
        "a population field if that name does not appear in the cited passage. "
        "Every source MUST include the supplied passage_id of the supporting passage and its URL. "
        "The application copies that exact passage into source_quote; you may supply a short "
        "verbatim quote in source_quote. Select a passage containing all numbers and relevant "
        "context for the result. Do not combine numbers from different passages. "
        "If a finding is from combination therapy, explicitly name the regimen. "
        "Return null when the fetched findings do not support a value. Never synthesize an average "
        "across different populations or studies. Keep the result short.",
        json.dumps({"disease": disease, "drug": choice.name,
                    "passages": [dict(doc.prompt(), passage_id=key) for key, doc in passages.items()]}),
        validate=validate,
    )
    resolve_passages(extracted)
    common = extracted.common_side_effects
    common_source = extracted.common_side_effects_source
    if not verified(common_source, [d for d in labels if "adverse_reactions" in d.title]):
        common, common_source = [], None
        issues.append("The common-side-effect citation could not be verified.")
    fields = {}
    for name in ("efficacy", "discontinuation_rate"):
        raw = getattr(extracted, name)
        fields[name] = checked_value(raw, docs)
        if raw is not None and fields[name] is None:
            issues.append(f"An unsupported {name.replace('_', ' ')} claim was removed.")
    evidence = []
    for raw in extracted.published_trial_evidence:
        validated = checked_value(raw, findings)
        if validated:
            evidence.append(validated)
        else:
            issues.append("An unsupported published-trial claim was removed.")
    # Boxed warnings are copied from the selected label, never generated or taken from FAERS.
    warning_doc = next((d for d in labels if "boxed_warning" in d.title), None)
    warning = None
    if warning_doc:
        warning = SourcedValue(value=warning_doc.text, source=SourceMetadata(
            source_url=warning_doc.source_url, source_quote=warning_doc.text, source_title=warning_doc.title))
    return SafetyOutput(
        treatment_name=choice.name, label_name=title, label_url=labels[0].source_url,
        common_side_effects=common, common_side_effects_source=common_source,
        boxed_warning=warning,
        boxed_warning_status="present" if warning_doc else "not_in_selected_label",
        published_trial_evidence=evidence, faers_frequently_reported_reactions=reactions,
        faers_source_url=str(httpx.URL("https://api.fda.gov/drug/event.json", params={
            "search": f'patient.drug.medicinalproduct:"{choice.name.upper()}"',
            "count": "patient.reaction.reactionmeddrapt.exact", "limit": 10})) if reactions else None,
        issues=issues, **fields,
    )


async def _collect(disease: str, choices: list[DrugChoice]):
    async def one(choice):
        try:
            return choice, await asyncio.wait_for(treatment_evidence(disease, choice), timeout=100)
        except Exception:
            logger.exception("Treatment worker failed for %s", choice.name)
            return choice, None
    return await asyncio.gather(*(one(choice) for choice in choices))


async def label_safety_agent(disease: str, drug_names: list[str], *, choices: list[DrugChoice]) -> LabelSafetyOutput:
    rows = await _collect(disease, [d for d in choices if d.name in drug_names and d.role == "first_line"])
    return LabelSafetyOutput(disease=disease, treatments=[row for _, row in rows if row],
        issues=[f"Safety details for {choice.name} could not be retrieved." for choice, row in rows if row is None])


async def alt_treatments_agent(disease: str, drug_names: list[str], *, choices: list[DrugChoice]) -> AlternativeTreatmentsOutput:
    rows = await _collect(disease, [d for d in choices if d.name in drug_names and d.role == "alternative"])
    return AlternativeTreatmentsOutput(disease=disease, treatments=[
        AlternativeTreatment(**row.model_dump(), treatment_type="Medication", description=choice.description)
        for choice, row in rows if row],
        issues=[f"Details for {choice.name} could not be retrieved." for choice, row in rows if row is None])


async def run_wave_two(disease: str, drug_names: list[str], *, choices: list[DrugChoice]):
    return await asyncio.gather(label_safety_agent(disease, drug_names, choices=choices),
                                alt_treatments_agent(disease, drug_names, choices=choices))
