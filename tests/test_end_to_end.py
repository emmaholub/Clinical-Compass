"""Exercise the real endpoint, boss, workers and citation checks with fixture providers."""
import asyncio
import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.data_sources import Document
from backend.models import DrugChoice, OverviewOutput, StandardOfCareOutput, SourceMetadata, SourcedValue
from backend.agents.wave2 import ExtractedSafety


@pytest.fixture
def anyio_backend():
    return 'asyncio'


CASES = [('rheumatoid arthritis', 'methotrexate', 'hydroxychloroquine'),
         ('type 2 diabetes', 'metformin', 'empagliflozin'),
         ("alzheimer's", 'donepezil', 'memantine')]


def wire_providers(monkeypatch, disease, first, other):
    """Fictional figures live only in tests; no medical fixtures ship in the app."""
    guide = Document('https://example.org/guideline', 'Fixture guideline',
                     f'For {disease}, offer {first}; consider {other}.', 'Guideline')
    source = SourceMetadata(source_url=guide.source_url, source_quote=guide.text)
    choices = [DrugChoice(name=name, role=role, description='Fixture option', guideline_source=source)
               for name, role in [(first, 'first_line'), (other, 'alternative')]]
    monkeypatch.setattr('backend.agents.wave1.search_guidelines', lambda d: [guide])
    monkeypatch.setattr('backend.agents.wave1.clinical_trials', lambda *a, **k: {'studies': []})

    async def generate_one(output, instructions, evidence, **kwargs):
        import json
        if output is OverviewOutput:
            return OverviewOutput(disease=disease, plain_language_summary='Fixture overview', common_symptoms=[], causes_or_risk_factors=[])
        normalized = json.loads(evidence)['disease']
        return StandardOfCareOutput(disease=normalized, treatment_name=first, treatment_type='Medicine',
            description='Fixture guideline statement', guideline_name='Fixture guideline',
            guideline_source=source, drugs=choices, medical_disclaimer='Educational only')
    monkeypatch.setattr('backend.agents.wave1.generate', generate_one)

    def fetch(disease, drug):
        label = Document(f'https://example.org/label/{drug}', 'Fixture adverse_reactions',
                         'Nausea was common. 6% stopped due to side effects at 24 weeks.', 'FDA label')
        trial = Document(f'https://example.org/trial/{drug}', 'Fixture trial',
                         '40% improved at 24 weeks compared with 20% on placebo.', 'Published trial')
        return drug, [label], [trial], [], []
    monkeypatch.setattr('backend.agents.wave2.fetch_evidence', fetch)

    async def generate_two(output, instructions, evidence, **kwargs):
        import json
        data = json.loads(evidence)
        label, trial = data['passages']
        def cite(p):
            return SourceMetadata(source_url=p['source_url'], source_quote=p['text'], passage_id=p['passage_id'])
        result = ExtractedSafety(common_side_effects=['nausea'], common_side_effects_source=cite(label),
            discontinuation_rate=SourcedValue(value='6% stopped due to side effects', source=cite(label)),
            efficacy=SourcedValue(value='40% improved compared with 20% on placebo', source=cite(trial), follow_up='24 weeks'))
        assert not kwargs['validate'](result)
        return result
    monkeypatch.setattr('backend.agents.wave2.generate', generate_two)


@pytest.mark.anyio
@pytest.mark.parametrize('disease,first,other', CASES)
async def test_full_two_wave_lookup_populates_treatments(monkeypatch, disease, first, other):
    wire_providers(monkeypatch, disease, first, other)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get(f'/api/disease/{disease}')
    assert response.status_code == 200
    page = response.json()
    assert page['partial'] is False
    assert page['standard_of_care']['drug_names'] == [first, other]
    assert page['standard_of_care']['efficacy']['source']['source_quote']
    assert [t['treatment_name'] for t in page['label_safety']['treatments']] == [first]
    assert [t['treatment_name'] for t in page['alternative_treatments']['treatments']] == [other]
    assert page['label_safety']['treatments'][0]['discontinuation_rate']['value']


@pytest.mark.anyio
async def test_missing_guideline_skips_dependent_workers(monkeypatch):
    from backend.boss import run_disease_lookup
    wire_providers(monkeypatch, 'unknown condition', 'first', 'other')
    monkeypatch.setattr('backend.agents.wave1.search_guidelines', lambda d: [])
    async def must_not_run(*a, **k):
        pytest.fail('Dependent worker should not run without a drug plan')
    monkeypatch.setattr('backend.boss.label_safety_agent', must_not_run)
    monkeypatch.setattr('backend.boss.alt_treatments_agent', must_not_run)
    page = await run_disease_lookup('unknown condition')
    assert page['partial'] is True
    assert 'error' in page['standard_of_care']
    assert 'error' in page['label_safety']
    assert isinstance(page['overview'], OverviewOutput)


@pytest.mark.anyio
async def test_one_drug_failure_retains_other_drugs(monkeypatch):
    from backend.agents.wave2 import alt_treatments_agent
    from backend.models import SafetyOutput
    source = SourceMetadata(source_url='https://example.org', source_quote='fixture')
    choices = [DrugChoice(name=n, role='alternative', description='fixture', guideline_source=source) for n in ['available', 'missing']]
    async def evidence(disease, choice):
        if choice.name == 'missing':
            raise LookupError('No label')
        return SafetyOutput(treatment_name=choice.name, label_name='Fixture', label_url='https://example.org', common_side_effects=['nausea'])
    monkeypatch.setattr('backend.agents.wave2.treatment_evidence', evidence)
    result = await alt_treatments_agent('condition', ['available', 'missing'], choices=choices)
    assert len(result.treatments) == 1
    assert 'missing' in result.issues[0]


@pytest.mark.anyio
async def test_workers_run_in_parallel_and_timeout_is_partial(monkeypatch):
    import backend.boss as boss
    wire_providers(monkeypatch, 'condition', 'first', 'other')
    started = set()
    async def worker(name):
        started.add(name)
        while len(started) < 3:
            await asyncio.sleep(0)
        raise RuntimeError('Fixture failure after all three started')
    for key, name in [('overview', 'overview_agent'), ('standard_of_care', 'standard_of_care_agent'), ('trials', 'trials_agent')]:
        monkeypatch.setattr(boss, name, lambda disease, key=key: worker(key))
    page = await asyncio.wait_for(boss.run_disease_lookup('condition'), timeout=1)
    assert len(started) == 3
    assert page['partial'] is True
    monkeypatch.setitem(boss.WORKER_TIMEOUTS, 'overview', .01)
    _, result = await boss._run_bounded('overview', asyncio.sleep(1))
    assert 'error' in result


def test_trial_filters_reject_small_non_us_nonrecruiting_studies():
    from backend.agents.wave1 import _trial_from_study
    study = {'protocolSection': {'identificationModule': {'nctId': 'NCT00000001', 'briefTitle': 'Fixture'},
        'statusModule': {'overallStatus': 'RECRUITING'}, 'designModule': {'phases': ['PHASE3'], 'enrollmentInfo': {'count': 200}},
        'contactsLocationsModule': {'locations': [{'country': 'United States'}]}}}
    assert _trial_from_study(study)
    study['protocolSection']['designModule']['enrollmentInfo']['count'] = 99
    assert _trial_from_study(study) is None
    study['protocolSection']['designModule']['enrollmentInfo']['count'] = 200
    study['protocolSection']['contactsLocationsModule']['locations'][0]['country'] = 'Canada'
    assert _trial_from_study(study) is None
