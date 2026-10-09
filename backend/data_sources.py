"""Public evidence retrieval with expiring caches and bounded requests."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from lxml import etree, html

DEFAULT_TIMEOUT = 15.0
DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "evidence-v2"
OPENFDA_LABELS_URL = "https://api.fda.gov/drug/label.json"
OPENFDA_FAERS_URL = "https://api.fda.gov/drug/event.json"
DAILYMED_SEARCH_URL = "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json"
CLINICAL_TRIALS_URL = "https://clinicaltrials.gov/api/v2/studies"
PUBMED_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_FETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_NCBI_LOCK = threading.Lock()
_NCBI_LAST = 0.0


@dataclass
class Document:
    source_url: str
    title: str
    text: str
    kind: str

    def __post_init__(self):
        # Canonical rendered text: HTML/XML whitespace is not medical content.
        self.text = " ".join(self.text.split())

    def prompt(self) -> dict:
        return asdict(self)


class CachedJsonClient:
    def __init__(self, cache_dir: Path = DEFAULT_CACHE_DIR,
                 timeout: float = DEFAULT_TIMEOUT, client: httpx.Client | None = None,
                 ttl: float = 86400, request_limit: int = 30):
        self.cache_dir, self.timeout, self.ttl = Path(cache_dir), timeout, ttl
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)
        self.request_limit, self.requests = request_limit, 0

    def _read(self, url: str, params: dict | None, mode: str):
        key = hashlib.sha256(json.dumps([url, params or {}, mode], sort_keys=True).encode()).hexdigest()
        path = self.cache_dir / (key + ".json")
        try:
            cached = json.loads(path.read_text())
            if time.time() - cached["fetched_at"] < self.ttl:
                return cached["payload"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if self.requests >= self.request_limit:
            raise RuntimeError("Evidence request limit reached")
        self.requests += 1
        if "ncbi.nlm.nih.gov" in url:
            global _NCBI_LAST
            with _NCBI_LOCK:
                time.sleep(max(0, .36 - (time.monotonic() - _NCBI_LAST)))
                _NCBI_LAST = time.monotonic()
        response = self.client.get(url, params=params, timeout=self.timeout)
        if response.status_code in {429, 502, 503} and self.requests < self.request_limit:
            self.requests += 1
            time.sleep(1.0)
            response = self.client.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json() if mode == "json" else response.text
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=self.cache_dir, delete=False) as f:
            json.dump({"fetched_at": time.time(), "payload": payload}, f)
            temp = f.name
        os.replace(temp, path)
        return payload

    def get(self, url: str, params: dict | None = None) -> dict:
        return self._read(url, params, "json")

    def text(self, url: str, params: dict | None = None) -> str:
        return self._read(url, params, "text")

    def close(self):
        self.client.close()


@contextmanager
def _client(client):
    api = client or CachedJsonClient()
    try:
        yield api
    finally:
        if client is None:
            api.close()


def normalize_disease(name: str) -> str:
    name = " ".join(name.strip().replace("’", "'").lower().split())
    aliases = {"ra": "rheumatoid arthritis", "alzheimer's": "Alzheimer's disease",
               "alzheimers": "Alzheimer's disease", "alzheimer": "Alzheimer's disease",
               "alzheimers disease": "Alzheimer's disease", "alzheimer's disease": "Alzheimer's disease",
               "alzheimer disease": "Alzheimer's disease", "rheumatoid arthritis (ra)": "rheumatoid arthritis",
               "t2d": "type 2 diabetes", "t2dm": "type 2 diabetes", "type ii diabetes": "type 2 diabetes",
               "type 2 diabetes mellitus": "type 2 diabetes", "diabetes mellitus type 2": "type 2 diabetes",
               "type 2 diabetes in adults": "type 2 diabetes", "type 2 diabetes mellitus in adults": "type 2 diabetes"}
    return aliases.get(name, name)


def _quoted(value: str) -> str:
    return value.replace('"', "").replace("\\", "").strip()


# Selects label products, never treatment recommendations.
BRANDS = {"methotrexate": "Trexall", "tofacitinib": "Xeljanz", "upadacitinib": "Rinvoq",
          "adalimumab": "Humira", "etanercept": "Enbrel", "hydroxychloroquine": "Plaquenil",
          "sulfasalazine": "Azulfidine", "leflunomide": "Arava", "metformin": "Glucophage",
          "empagliflozin": "Jardiance", "dapagliflozin": "Farxiga", "semaglutide": "Ozempic",
          "sitagliptin": "Januvia", "donepezil": "Aricept", "rivastigmine": "Exelon",
          "galantamine": "Razadyne", "memantine": "Namenda", "lecanemab": "Leqembi",
          "donanemab": "Kisunla", "trofinetide": "Daybue"}


def openfda_label(drug_name: str, *, client: CachedJsonClient | None = None,
                  prefer_brand: bool = True) -> dict:
    with _client(client) as api:
        brand = BRANDS.get(drug_name.casefold(), drug_name)
        ingredients = [part.strip().casefold() for part in re.split(r"\s*(?:/|\band\b)\s*", drug_name, flags=re.I) if part.strip()]
        queries = [("brand_name", brand), ("generic_name", drug_name)] if prefer_brand else [("generic_name", drug_name)]
        for field, name in queries:
            try:
                search = f'openfda.{field}:"{_quoted(name)}"'
                if field == 'generic_name' and len(ingredients) > 1:
                    search = ' AND '.join(f'openfda.generic_name:"{_quoted(part)}"' for part in ingredients)
                payload = api.get(OPENFDA_LABELS_URL, {"search": search, "limit": 100})
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    continue
                raise
            candidates = payload.get("results", [])
            # openFDA phrase search also matches combination products. Never use
            # a combination label to describe the safety of a single ingredient.
            def matches_product(label):
                names = label.get('openfda', {}).get('generic_name', [])
                if len(ingredients) == 1:
                    return not any(re.search(r"\b(?:and|with)\b|[/;,]", name, re.I) for name in names)
                return any(all(part in name.casefold() for part in ingredients)
                           and len(re.split(r"\band\b|[/;,]", name, flags=re.I)) == len(ingredients)
                           for name in names)
            candidates = [label for label in candidates if matches_product(label)]
            if not candidates:
                continue
            def score(label):
                info = label.get("openfda", {})
                brand_match = brand.casefold() in [b.casefold() for b in info.get("brand_name", [])]
                innovator = any(n.startswith(("NDA", "BLA")) for n in info.get("application_number", []))
                complete = bool(label.get("adverse_reactions")) and bool(label.get("indications_and_usage"))
                return (complete, brand_match, innovator, label.get("effective_time", ""), label.get("id", ""))
            return max(candidates, key=score)
    raise LookupError(f"No FDA label found for {drug_name}")


def openfda_faers(drug_name: str, *, client: CachedJsonClient | None = None, limit: int = 10) -> dict:
    with _client(client) as api:
        return api.get(OPENFDA_FAERS_URL, {"search": f'patient.drug.medicinalproduct:"{_quoted(drug_name.upper())}"',
            "count": "patient.reaction.reactionmeddrapt.exact", "limit": limit})


def dailymed_labels(drug_name: str, *, client: CachedJsonClient | None = None) -> dict:
    with _client(client) as api:
        return api.get(DAILYMED_SEARCH_URL, {"drug_name": drug_name, "pagesize": 20})


def _xml(text: str):
    return etree.fromstring(text.encode(), parser=etree.XMLParser(resolve_entities=False, no_network=True))


def _text(element) -> str:
    return " ".join(" ".join(element.itertext()).split())


def label_documents(drug_name: str, *, client: CachedJsonClient | None = None) -> tuple[str, list[Document]]:
    with _client(client) as api:
        try:
            label = openfda_label(drug_name, client=api)
            if not label.get("adverse_reactions"):
                raise LookupError("Incomplete label")
            set_id = label.get("set_id") or label.get("openfda", {}).get("spl_set_id", [None])[0]
            if not set_id:
                raise LookupError("Label has no stable identifier")
            url = f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}"
            title = ", ".join(label.get("openfda", {}).get("brand_name", [drug_name]))
            docs = [Document(url, title + " — " + section, "\n".join(label[section]), "FDA label")
                    for section in ("indications_and_usage", "adverse_reactions", "boxed_warning", "clinical_studies") if label.get(section)]
            return title, docs
        except (LookupError, httpx.HTTPError):
            rows = dailymed_labels(BRANDS.get(drug_name.casefold(), drug_name), client=api).get("data", [])
            if not rows:
                rows = dailymed_labels(drug_name, client=api).get("data", [])
            if not rows:
                raise LookupError(f"No public label available for {drug_name}")
            row = max(rows, key=lambda r: (BRANDS.get(drug_name.casefold(), drug_name).upper() in r.get("title", "").upper(), r.get("published_date", "")))
            set_id = row["setid"]
            tree = _xml(api.text(f"https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/{set_id}.xml"))
            url = f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}"
            codes = {"34067-9": "indications_and_usage", "34084-4": "adverse_reactions",
                     "34066-1": "boxed_warning", "34092-2": "clinical_studies"}
            docs = []
            for section in tree.xpath('//*[local-name()="section"]'):
                code = section.xpath('./*[local-name()="code"]/@code')
                if code and code[0] in codes:
                    docs.append(Document(url, row["title"] + " — " + codes[code[0]], _text(section), "FDA label"))
            if not docs:
                raise LookupError("DailyMed SPL contains no usable sections")
            return row["title"], docs


def pubmed_search(query: str, *, client: CachedJsonClient | None = None, limit: int = 5,
                  publication_filter: str = "clinical trial[pt] OR randomized controlled trial[pt]") -> dict:
    with _client(client) as api:
        return api.get(PUBMED_SEARCH_URL, {"db": "pubmed", "term": f"({query}) AND ({publication_filter})",
            "retmode": "json", "retmax": limit, "sort": "relevance"})


def published_findings(disease: str, drug: str, *, client: CachedJsonClient | None = None,
                       guidelines: bool = False) -> list[Document]:
    with _client(client) as api:
        query = f'"{_quoted(disease)}" {_quoted(drug)}'
        if not guidelines:
            query += ' (placebo[Title/Abstract] OR monotherapy[Title/Abstract])'
        filters = "practice guideline[pt] OR guideline[pt]" if guidelines else "clinical trial[pt] OR randomized controlled trial[pt]"
        ids = pubmed_search(query, client=api, publication_filter=filters).get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        raw = api.text(PUBMED_FETCH_URL, {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"})
        docs = []
        for article in _xml(raw).findall(".//PubmedArticle"):
            pmid = article.findtext(".//MedlineCitation/PMID")
            title_el = article.find(".//ArticleTitle")
            abstract = article.findall(".//Abstract/AbstractText")
            if pmid and title_el is not None and abstract:
                title = _text(title_el)
                text = title + "\n" + "\n".join(_text(a) for a in abstract)
                docs.append(Document(f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", title, text,
                                     "Guideline" if guidelines else "Published trial"))
        return docs


def _html_text(raw: str) -> str:
    tree = html.fromstring(raw)
    for el in tree.xpath("//script|//style|//nav|//footer"):
        el.drop_tree()
    main = tree.xpath("//main")
    return _text(main[0] if main else tree)


GUIDELINES = {
    "rheumatoid arthritis": [("NICE (UK): Rheumatoid arthritis in adults", "https://www.nice.org.uk/guidance/ng100/chapter/Recommendations")],
    "type 2 diabetes": [("NICE (UK): Type 2 diabetes in adults", "https://www.nice.org.uk/guidance/ng28/chapter/Recommendations")],
    "alzheimer's disease": [("NICE (UK): Dementia management", "https://www.nice.org.uk/guidance/ng97/chapter/Recommendations")],
}


def search_guidelines(disease: str, *, max_results: int = 5,
                      client: CachedJsonClient | None = None) -> list[Document]:
    disease = normalize_disease(disease)
    docs = []
    with _client(client) as api:
        candidates = GUIDELINES.get(disease.casefold(), [])
        if not candidates:
            try:
                search_page = api.text("https://www.nice.org.uk/search", {"q": disease})
                links = html.fromstring(search_page).xpath('//a[@href]')
                tokens = [t for t in re.findall(r"[a-z]+", disease.casefold()) if len(t) > 3 and t != 'disease']
                for link in links:
                    href, title = link.get('href'), _text(link)
                    if re.fullmatch(r"/guidance/(?:ng|cg)\d+", href, re.I) and all(t in title.casefold() for t in tokens):
                        if not any(word in title.casefold() for word in ('suspected', 'familial')):
                            pair = ("NICE (UK): " + title, "https://www.nice.org.uk" + href.lower() + "/chapter/Recommendations")
                            if pair not in candidates:
                                candidates.append(pair)
                candidates = candidates[:3]
            except httpx.HTTPError:
                pass
        for title, url in candidates:
            try:
                raw = api.text(url)
                docs.append(Document(url, title, _html_text(raw), "Guideline"))
                if disease == "type 2 diabetes":
                    links = html.fromstring(raw).xpath('//a/@href')
                    links = sorted({urljoin(url, link) for link in links if "/chapter/" in link and any(w in link.lower() for w in ("medicine", "drug", "pharmacological"))})
                    for link in links[:3]:
                        if urlparse(link).hostname == "www.nice.org.uk":
                            docs.append(Document(link, title, _html_text(api.text(link)), "Guideline"))
            except httpx.HTTPError:
                continue
        if not docs:
            try:
                docs.extend(published_findings(disease, "treatment", client=api, guidelines=True))
            except httpx.HTTPError:
                pass
        # Rare diseases often have no NICE guideline page. Use an authoritative
        # US government disease page plus an FDA label as a clearly identified
        # evidence fallback; the model must not call this a universal guideline.
        if not docs and disease.casefold() == "rett syndrome":
            try:
                url = "https://www.ninds.nih.gov/health-information/disorders/rett-syndrome"
                docs.append(Document(url, "NINDS: Rett Syndrome", _html_text(api.text(url)), "NIH disease information"))
            except httpx.HTTPError:
                pass
            try:
                _, label_docs = label_documents("trofinetide", client=api)
                docs.extend(label_docs)
            except (LookupError, httpx.HTTPError):
                pass
    return docs[:max_results]


def overview_documents(disease: str, *, client: CachedJsonClient | None = None,
                       max_results: int = 4) -> list[Document]:
    """Fetch plain-language disease evidence for overview generation.

    Named government pages are preferred for rare diseases; PubMed abstracts
    are a bounded fallback when no disease page is available.
    """
    disease = normalize_disease(disease)
    with _client(client) as api:
        docs: list[Document] = []
        urls = {
            "rett syndrome": ("NINDS: Rett Syndrome", "https://www.ninds.nih.gov/health-information/disorders/rett-syndrome"),
            "rheumatoid arthritis": ("NIAMS: Rheumatoid Arthritis", "https://www.niams.nih.gov/health-topics/rheumatoid-arthritis"),
        }
        if disease.casefold() in urls:
            title, url = urls[disease.casefold()]
            try:
                docs.append(Document(url, title, _html_text(api.text(url)), "NIH disease information"))
            except httpx.HTTPError:
                pass
        if not docs:
            try:
                docs = published_findings(disease, "disease overview", client=api, guidelines=False)
            except httpx.HTTPError:
                docs = []
        return docs[:max_results]


def clinical_trials(disease: str, *, client: CachedJsonClient | None = None, page_size: int = 100) -> dict:
    with _client(client) as api:
        params = {"query.cond": disease, "filter.overallStatus": "RECRUITING", "filter.advanced":
            'AREA[LocationCountry]"United States" AND (AREA[Phase]PHASE2 OR AREA[Phase]PHASE3 OR AREA[Phase]PHASE4) AND AREA[EnrollmentCount]RANGE[100, MAX]',
            "pageSize": page_size, "format": "json"}
        studies = []
        for _ in range(3):
            payload = api.get(CLINICAL_TRIALS_URL, params)
            studies.extend(payload.get("studies", []))
            if not payload.get("nextPageToken"):
                return {"studies": studies, "truncated": False}
            params["pageToken"] = payload["nextPageToken"]
        return {"studies": studies, "truncated": True}


def close_client(client: CachedJsonClient) -> None:
    client.close()
