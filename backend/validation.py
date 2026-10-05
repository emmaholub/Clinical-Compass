"""Citation checks scoped to the claimed URL, rather than pooled source text."""
from __future__ import annotations

import re
from backend.data_sources import Document
from backend.models import SourceMetadata, SourcedValue


def validate_source_quote(quote: str, fetched_text: str) -> bool:
    return bool(quote.strip()) and quote in fetched_text


def verified(source: SourceMetadata | None, docs: list[Document]) -> bool:
    return source is not None and any(
        str(source.source_url) == doc.source_url and validate_source_quote(source.source_quote, doc.text)
        for doc in docs
    )


def checked_value(value: SourcedValue | None, docs: list[Document]) -> SourcedValue | None:
    if value is None or value_problem(value, docs):
        return None
    doc = next(d for d in docs if d.source_url == str(value.source.source_url) and value.source.source_quote in d.text)
    value.evidence_type = doc.kind
    return value


def value_problem(value: SourcedValue | None, docs: list[Document]) -> str | None:
    if value is None:
        return None
    if not verified(value.source, docs):
        return "The quote is not an exact passage at its cited URL"
    claim = " ".join(filter(None, [value.value, value.outcome, value.population, value.follow_up, value.comparator]))
    numbers = re.findall(r"\d+(?:\.\d+)?", claim.replace(",", ""))
    quote_numbers = re.findall(r"\d+(?:\.\d+)?", value.source.source_quote.replace(",", ""))
    if any(number not in quote_numbers for number in numbers):
        return "Quote is missing numbers used in the claim or its context: " + str(sorted(set(numbers) - set(quote_numbers)))
    return None
