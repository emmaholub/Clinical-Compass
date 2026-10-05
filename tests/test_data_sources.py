from pathlib import Path

import httpx
import pytest

from backend.data_sources import (
    CachedJsonClient,
    clinical_trials,
    dailymed_labels,
    openfda_faers,
    openfda_label,
    label_documents,
    published_findings,
    search_guidelines,
)


def make_client(tmp_path: Path, requests: list[httpx.Request]) -> CachedJsonClient:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"results": [{"id": "fixture"}]})

    return CachedJsonClient(
        cache_dir=tmp_path / "cache",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_openfda_label_prefers_brand_and_caches(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    client = make_client(tmp_path, requests)
    assert openfda_label("methotrexate", client=client)["id"] == "fixture"
    openfda_label("methotrexate", client=client)
    assert len(requests) == 1
    assert "brand_name" in str(requests[0].url)


def test_faers_dailymed_and_trials_use_expected_endpoints(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    client = make_client(tmp_path, requests)
    openfda_faers("methotrexate", client=client)
    dailymed_labels("methotrexate", client=client)
    clinical_trials("rheumatoid arthritis", client=client)
    urls = [str(request.url) for request in requests]
    assert any("drug/event.json" in url for url in urls)
    assert any("dailymed" in url for url in urls)
    assert any("clinicaltrials.gov" in url for url in urls)


def test_brand_404_uses_generic_and_excludes_combinations(tmp_path):
    requests = []
    def handler(request):
        requests.append(request)
        if 'brand_name' in request.url.params['search']:
            return httpx.Response(404, json={'error': {'code': 'NOT_FOUND'}})
        return httpx.Response(200, json={'results': [
            {'id': 'combo', 'effective_time': '20261001', 'openfda': {'generic_name': ['alogliptin and metformin hydrochloride']}},
            {'id': 'single', 'openfda': {'generic_name': ['metformin hydrochloride']}}
        ]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        result = openfda_label('metformin', client=CachedJsonClient(tmp_path, client=http))
    assert result['id'] == 'single'
    assert len(requests) == 2
    assert 'Glucophage' in requests[0].url.params['search']


def test_latest_brand_label_selected_deterministically(tmp_path):
    rows = [{'id': key, 'effective_time': date, 'openfda': {'brand_name': ['Aricept'], 'generic_name': ['donepezil'], 'application_number': ['NDA020690']},
             'adverse_reactions': ['nausea'], 'indications_and_usage': ['dementia']}
            for key, date in [('older', '20200101'), ('newer', '20260101')]]
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'results': rows})))
    assert openfda_label('donepezil', client=CachedJsonClient(tmp_path, client=http))['id'] == 'newer'
    http.close()


def test_dailymed_fallback_fetches_spl_text(tmp_path):
    def handler(request):
        if request.url.host == 'api.fda.gov':
            return httpx.Response(404)
        if request.url.path.endswith('spls.json'):
            return httpx.Response(200, json={'data': [{'setid': 'abc', 'title': 'ARICEPT'}]})
        return httpx.Response(200, text='<document xmlns="urn:hl7-org:v3"><section><code code="34084-4"/><text>Nausea is common.</text></section></document>')
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        title, docs = label_documents('donepezil', client=CachedJsonClient(tmp_path, client=http))
    assert title == 'ARICEPT'
    assert 'Nausea is common.' in docs[0].text
    assert 'setid=abc' in docs[0].source_url


def test_pubmed_fetches_abstract_not_just_identifiers(tmp_path):
    def handler(request):
        if request.url.path.endswith('esearch.fcgi'):
            return httpx.Response(200, json={'esearchresult': {'idlist': ['123']}})
        return httpx.Response(200, text='<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>A randomized trial</ArticleTitle><Abstract><AbstractText>At 24 weeks, 40% improved.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>')
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        docs = published_findings('condition', 'drug', client=CachedJsonClient(tmp_path, client=http))
    assert docs[0].text == 'A randomized trial At 24 weeks, 40% improved.'
    assert docs[0].source_url == 'https://pubmed.ncbi.nlm.nih.gov/123/'


def test_failed_response_not_cached_and_request_limit_enforced(tmp_path):
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400)))
    api = CachedJsonClient(tmp_path, client=http, request_limit=1)
    with pytest.raises(httpx.HTTPStatusError):
        api.get('https://example.org')
    assert not list(tmp_path.glob('*.json'))
    with pytest.raises(RuntimeError, match='request limit'):
        api.get('https://example.org')
    http.close()


def test_expired_and_corrupt_caches_refetch(tmp_path):
    requests = []
    api = make_client(tmp_path, requests)
    api.get('https://example.org')
    api.ttl = -1
    api.get('https://example.org')
    assert len(requests) == 2
    next((tmp_path / 'cache').glob('*.json')).write_text('broken')
    api.get('https://example.org')
    assert len(requests) == 3
    api.close()


def test_explicit_combination_does_not_select_a_single_component(tmp_path):
    def handler(request):
        if 'brand_name' in request.url.params['search']:
            return httpx.Response(404)
        return httpx.Response(200, json={'results': [
            {'id': 'single', 'openfda': {'generic_name': ['budesonide']}},
            {'id': 'combo', 'openfda': {'generic_name': ['budesonide and formoterol fumarate dihydrate']}}
        ]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        result = openfda_label('budesonide/formoterol', client=CachedJsonClient(tmp_path, client=http))
    assert result['id'] == 'combo'


def test_discovers_recommendations_for_another_disease(tmp_path):
    def handler(request):
        if request.url.path == '/search':
            return httpx.Response(200, text='<a href="/guidance/ng245">Asthma: diagnosis and management</a><a href="https://evil.example/guidance/ng245">Asthma</a>')
        assert request.url.host == 'www.nice.org.uk'
        return httpx.Response(200, text='<main>Asthma recommendations with treatment evidence.</main>')
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        docs = search_guidelines('asthma', client=CachedJsonClient(tmp_path, client=http))
    assert len(docs) == 1
    assert docs[0].source_url == 'https://www.nice.org.uk/guidance/ng245/chapter/Recommendations'
