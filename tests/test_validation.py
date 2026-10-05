import pytest
from pydantic import ValidationError
from backend.data_sources import Document, normalize_disease
from backend.models import SourceMetadata, SourcedValue
from backend.validation import verified, checked_value


def test_quote_must_match_its_own_url():
    docs = [Document('https://example.org/a', 'A', '40% improved', 'Published trial'),
            Document('https://example.org/b', 'B', '20% improved', 'Published trial')]
    assert not verified(SourceMetadata(source_url='https://example.org/b', source_quote='40% improved'), docs)
    assert verified(SourceMetadata(source_url='https://example.org/a', source_quote='40% improved'), docs)


def test_valid_quote_does_not_allow_invented_number_or_follow_up():
    docs = [Document('https://example.org/a', 'A', '40% improved at 24 weeks', 'Published trial')]
    claim = SourcedValue(value='90% improved', source=SourceMetadata(source_url='https://example.org/a', source_quote=docs[0].text))
    assert checked_value(claim, docs) is None
    claim.value = '40% improved'
    claim.follow_up = '52 weeks'
    assert checked_value(claim, docs) is None
    claim.follow_up = '24 weeks'
    assert checked_value(claim, docs).evidence_type == 'Published trial'


def test_unexpected_model_fields_rejected():
    with pytest.raises(ValidationError):
        SourceMetadata(source_url='https://example.org', source_quote='evidence', made_up=True)


def test_disease_aliases_do_not_trigger_false_cross_disease_rejections():
    assert normalize_disease('Type 2 diabetes mellitus') == 'type 2 diabetes'
    assert normalize_disease('Alzheimer’s') == "Alzheimer's disease"
    assert normalize_disease('rheumatoid arthritis') != normalize_disease('type 2 diabetes')
