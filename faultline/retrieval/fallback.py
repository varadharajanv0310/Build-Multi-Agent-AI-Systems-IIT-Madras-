"""Crossref and Europe PMC — keyless retrieval sources.

OpenAlex moved to a metered credit model (1000 credits/day free, 10 per
search, reset at midnight UTC). Exhausting it hard-stops retrieval for hours,
and a system whose entire input depends on one metered API has a single point
of failure that looks, from the inside, exactly like "the literature is thin".

Crossref and Europe PMC are genuinely keyless and unmetered for polite use.
Neither is as rich as OpenAlex — Crossref has no abstracts for much of its
corpus, Europe PMC is biomedical-leaning — so they are a fallback rather than
a replacement. But a degraded corpus beats no corpus.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterator

import httpx

from faultline.config import SETTINGS
from faultline.retrieval.models import Paper
from faultline.retrieval.openalex import clean_query


class _Base:
    name = "base"
    base_url = ""

    def __init__(self, timeout: float = 60.0, min_interval: float = 0.25):
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": SETTINGS.user_agent, "Accept": "application/json"},
            follow_redirects=True)
        self._min_interval = min_interval
        self._last = 0.0

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        gap = time.monotonic() - self._last
        if gap < self._min_interval:
            time.sleep(self._min_interval - gap)
        self._last = time.monotonic()
        r = self._client.get(f"{self.base_url}{path}", params=params)
        r.raise_for_status()
        return r.json()

    def close(self) -> None:
        self._client.close()


class CrossrefClient(_Base):
    """All fields, ~150M works, keyless. Abstracts are patchy."""

    name = "crossref"
    base_url = "https://api.crossref.org"

    def search(self, query: str, *, limit: int = 50,
               from_year: int | None = None, **_: Any) -> Iterator[Paper]:
        params: dict[str, Any] = {
            "query.bibliographic": clean_query(query),
            "rows": min(100, limit),
            "select": "DOI,title,abstract,issued,container-title,author,type,is-referenced-by-count",
            "mailto": SETTINGS.polite_pool_email,
        }
        if from_year:
            params["filter"] = f"from-pub-date:{from_year}-01-01"
        try:
            data = self._get("/works", params)
        except Exception:
            return
        for item in data.get("message", {}).get("items", [])[:limit]:
            yield self._to_paper(item)

    @staticmethod
    def _to_paper(item: dict) -> Paper:
        title = (item.get("title") or [""])[0]
        year = None
        parts = (item.get("issued") or {}).get("date-parts") or [[]]
        if parts and parts[0]:
            year = parts[0][0]
        abstract = item.get("abstract")
        if abstract:
            # Crossref ships JATS-tagged abstracts.
            import re
            abstract = re.sub(r"<[^>]+>", " ", abstract)
            abstract = " ".join(abstract.split())
        authors = [" ".join(filter(None, [a.get("given"), a.get("family")]))
                   for a in (item.get("author") or [])][:25]
        doi = item.get("DOI")
        return Paper(
            id=f"crossref:{doi}", title=title, year=year, doi=doi,
            venue=(item.get("container-title") or [None])[0],
            authors=authors, abstract=abstract,
            cited_by_count=item.get("is-referenced-by-count", 0) or 0,
            type=item.get("type"), source="crossref",
            fulltext_source="abstract_only" if abstract else "none")


class EuropePMCClient(_Base):
    """Biomedical-leaning, keyless, and reliably carries abstracts."""

    name = "europepmc"
    base_url = "https://www.ebi.ac.uk/europepmc/webservices/rest"

    def search(self, query: str, *, limit: int = 50,
               from_year: int | None = None, **_: Any) -> Iterator[Paper]:
        q = clean_query(query)
        if from_year:
            q = f"{q} AND (FIRST_PDATE:[{from_year}-01-01 TO 2030-12-31])"
        try:
            data = self._get("/search", {
                "query": q, "format": "json",
                "pageSize": min(100, limit), "resultType": "core"})
        except Exception:
            return
        for item in (data.get("resultList", {}) or {}).get("result", [])[:limit]:
            yield self._to_paper(item)

    @staticmethod
    def _to_paper(item: dict) -> Paper:
        year = item.get("pubYear")
        return Paper(
            id=f"epmc:{item.get('id')}",
            title=item.get("title") or "",
            year=int(year) if str(year).isdigit() else None,
            doi=item.get("doi"),
            venue=item.get("journalTitle"),
            authors=[a.strip() for a in (item.get("authorString") or "").split(",")][:25],
            abstract=item.get("abstractText"),
            pmid=item.get("pmid"), pmcid=item.get("pmcid"),
            cited_by_count=item.get("citedByCount", 0) or 0,
            oa_status="gold" if item.get("isOpenAccess") == "Y" else None,
            type=item.get("pubType"), source="europepmc",
            fulltext_source="abstract_only" if item.get("abstractText") else "none")


class ArxivClient(_Base):
    """Computer science, physics, maths and quantitative biology.

    The keyless sources are not interchangeable. Europe PMC is biomedical and
    Crossref has patchy abstracts, so a query about adversarial machine
    learning returned eight off-domain papers that screening rightly threw
    out — the corpus was empty not because the work does not exist but
    because nobody asked arXiv, where that literature actually lives.
    """

    name = "arxiv"
    base_url = "https://export.arxiv.org/api"

    # arXiv asks for ~3s between requests. Being impolite here gets IP-banned,
    # which is a far worse outcome than a slow search.
    def __init__(self, timeout: float = 60.0, min_interval: float = 3.0):
        super().__init__(timeout=timeout, min_interval=min_interval)

    def _get(self, path: str, params: dict[str, Any]) -> str:  # type: ignore[override]
        gap = time.monotonic() - self._last
        if gap < self._min_interval:
            time.sleep(self._min_interval - gap)
        self._last = time.monotonic()
        r = self._client.get(f"{self.base_url}{path}", params=params)
        r.raise_for_status()
        return r.text

    def search(self, query: str, *, limit: int = 50,
               from_year: int | None = None, **_: Any) -> Iterator[Paper]:
        terms = clean_query(query).split()
        if not terms:
            return
        # Field-scoped AND across terms: `all:` alone matches far too loosely
        # and returns unrelated preprints for multi-word topics.
        expr = " AND ".join(f'all:"{t}"' if " " in t else f"all:{t}" for t in terms[:8])
        try:
            body = self._get("/query", {
                "search_query": expr,
                "start": 0,
                "max_results": min(100, limit * 2),
                "sortBy": "relevance",
            })
        except Exception:
            return

        ns = {"a": "http://www.w3.org/2005/Atom"}
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return

        count = 0
        for entry in root.findall("a:entry", ns):
            paper = self._to_paper(entry, ns)
            if paper is None:
                continue
            if from_year and paper.year and paper.year < from_year:
                continue
            yield paper
            count += 1
            if count >= limit:
                return

    @staticmethod
    def _to_paper(entry, ns) -> Paper | None:
        def text(tag: str) -> str:
            el = entry.find(f"a:{tag}", ns)
            return " ".join((el.text or "").split()) if el is not None else ""

        title = text("title")
        summary = text("summary")
        if not title or not summary:
            return None
        raw_id = text("id")
        arxiv_id = raw_id.rstrip("/").rsplit("/", 1)[-1] if raw_id else ""
        published = text("published")
        year = int(published[:4]) if published[:4].isdigit() else None
        authors = [" ".join((a.findtext("a:name", "", ns) or "").split())
                   for a in entry.findall("a:author", ns)][:25]
        doi = entry.findtext("{http://arxiv.org/schemas/atom}doi") or None
        return Paper(
            id=f"arxiv:{arxiv_id}", title=title, year=year, doi=doi,
            venue="arXiv", authors=authors, abstract=summary,
            arxiv_id=arxiv_id, oa_status="green", source="arxiv",
            type="preprint", fulltext_source="abstract_only")


def search_with_fallback(query: str, *, limit: int = 50,
                         from_year: int | None = None,
                         primary=None, log=None) -> tuple[list[Paper], list[str]]:
    """Search every source concurrently and merge.

    This used to return OpenAlex's hits the moment they were non-empty, which
    made the other three databases a failure path rather than part of the
    corpus. The cost was invisible and large: a creatine question answered from
    OpenAlex alone included 0 of 28 screened papers, where the same question
    across Crossref and Europe PMC had produced a usable answer. Whichever
    database happens to answer first is not the same as the literature.

    They cover different literatures — arXiv for CS and physics, Europe PMC for
    biomedicine, Crossref for the rest, OpenAlex across all of it — so all four
    run concurrently and every hit is merged. Concurrency means covering four
    sources costs about what covering one did.

    Returns (papers, sources_used). Sources are reported rather than hidden:
    which databases produced a corpus is part of what makes a review defensible.
    """
    say = log or (lambda _m: None)
    papers: list[Paper] = []
    used: list[str] = []

    def _fetch_primary():
        if primary is None:
            return "openalex", []
        try:
            return "openalex", list(primary.search(query, limit=limit,
                                                   from_year=from_year))
        except Exception as e:
            say(f"      openalex unavailable ({type(e).__name__}); using other sources")
            return "openalex", []

    def _fetch(cls):
        client = cls()
        try:
            return cls.name, [p for p in client.search(query, limit=limit,
                                                       from_year=from_year)
                              if p.abstract]
        except Exception:
            return cls.name, []
        finally:
            client.close()

    per_source: list[list[Paper]] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_fetch_primary)]
        futures += [pool.submit(_fetch, c)
                    for c in (ArxivClient, EuropePMCClient, CrossrefClient)]
        for f in futures:
            name, hits = f.result()
            if hits:
                per_source.append(list(hits))
                used.append(name)

    # Interleave before truncating. Concatenating would put one database first,
    # so `limit` would discard whole literatures — the same single-source
    # failure this function now exists to prevent. Round-robin gives every
    # database a share of the budget, in relevance order within each.
    while len(papers) < limit and any(per_source):
        for bucket in per_source:
            if bucket:
                papers.append(bucket.pop(0))
                if len(papers) >= limit:
                    break

    return papers[:limit], used or ["none"]
