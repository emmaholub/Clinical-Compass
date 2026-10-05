"""Shared Pydantic schemas for Clinical Compass worker outputs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceMetadata(StrictModel):
    """A claim's source and the exact text supporting it."""

    source_url: HttpUrl
    source_quote: str = Field(min_length=1)
    source_title: str | None = None
    passage_id: str | None = None


class SourcedValue(StrictModel):
    """A value that must be traceable to a source."""

    value: str
    source: SourceMetadata
    evidence_type: Literal["FDA label", "Published trial", "Guideline"] = "FDA label"
    outcome: str | None = None
    population: str | None = None
    follow_up: str | None = None
    comparator: str | None = None


class OverviewOutput(StrictModel):
    """Plain-language disease overview for patients and caregivers."""

    disease: str
    plain_language_summary: str
    common_symptoms: list[str]
    causes_or_risk_factors: list[str]
    source: SourceMetadata | None = None


class DrugChoice(StrictModel):
    name: str = Field(min_length=1)
    role: Literal["first_line", "alternative"]
    description: str
    guideline_source: SourceMetadata


class StandardOfCareOutput(StrictModel):
    """First-line treatment and guideline evidence."""

    disease: str
    treatment_name: str
    treatment_type: str
    description: str
    efficacy: SourcedValue | None = None
    efficacy_treatment_name: str | None = None
    guideline_name: str
    guideline_source: SourceMetadata
    drugs: list[DrugChoice] = Field(min_length=1, max_length=6)
    drug_names: list[str] = Field(
        default_factory=list,
        description="Drug names passed to the Wave 2 safety workers.",
    )
    medical_disclaimer: str
    issues: list[str] = Field(default_factory=list)
    prescribing_volume_status: str = (
        "IQVIA National Prescription Audit data requires licensed access and is not connected."
    )

    @model_validator(mode="after")
    def drug_handoff(self):
        names = [drug.name.casefold() for drug in self.drugs]
        if len(set(names)) != len(names) or not any(d.role == "first_line" for d in self.drugs):
            raise ValueError("Require distinct drugs and at least one first-line option")
        self.drug_names = [drug.name for drug in self.drugs]
        return self


class SafetyOutput(StrictModel):
    """Safety information for one selected drug label."""

    treatment_name: str
    label_name: str
    label_url: HttpUrl
    common_side_effects: list[str]
    common_side_effects_source: SourceMetadata | None = None
    efficacy: SourcedValue | None = None
    discontinuation_rate: SourcedValue | None = None
    boxed_warning: SourcedValue | None = None
    faers_frequently_reported_reactions: list[str] = Field(default_factory=list)
    faers_source_url: HttpUrl | None = None
    published_trial_evidence: list[SourcedValue] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    boxed_warning_status: Literal["present", "not_in_selected_label", "unavailable"] = "unavailable"


class LabelSafetyOutput(StrictModel):
    """Safety worker result for all drugs supplied by Wave 1."""

    disease: str
    treatments: list[SafetyOutput]
    issues: list[str] = Field(default_factory=list)


class AlternativeTreatment(SafetyOutput):
    """One alternative treatment and its label-derived safety information."""

    treatment_type: str
    description: str


class AlternativeTreatmentsOutput(StrictModel):
    """Alternative-treatment worker result."""

    disease: str
    treatments: list[AlternativeTreatment]
    issues: list[str] = Field(default_factory=list)


class ClinicalTrial(StrictModel):
    """A qualifying US recruiting clinical trial."""

    title: str
    brief_summary: str
    phase: str
    enrollment: int | None = None
    location: str
    sponsor: str | None = None
    recruitment_status: str
    study_url: HttpUrl
    source: SourceMetadata


class TrialsOutput(StrictModel):
    """Clinical-trials worker result after required filters."""

    disease: str
    filters_applied: list[str]
    trials: list[ClinicalTrial]
