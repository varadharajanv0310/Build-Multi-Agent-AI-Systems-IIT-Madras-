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


def search_with_fallback(query: str, *, limit: int = 50,
                         from_year: int | None = None,
                         primary=None, log=None) -> tuple[list[Paper], list[str]]:
    """Try OpenAlex, then fall back to keyless sources.

    Returns (papers, sources_used). Sources are reported rather than hidden:
    which database produced a corpus is part of what makes a review defensible,
    and a fallback corpus is not equivalent to the primary one.
    """
    say = log or (lambda _m: None)
    papers: list[Paper] = []
    used: list[str] = []

    if primary is not None:
        try:
            papers = list(primary.search(query, limit=limit, from_year=from_year))
            if papers:
                return papers, ["openalex"]
        except Exception as e:
            say(f"      openalex unavailable ({type(e).__name__}); falling back")

    for client_cls in (EuropePMCClient, CrossrefClient):
        client = client_cls()
        try:
            hits = [p for p in client.search(query, limit=limit, from_year=from_year)
                    if p.abstract]
            if hits:
                papers.extend(hits)
                used.append(client.name)
        except Exception:
            pass
        finally:
            client.close()
        if len(papers) >= limit:
            break

    return papers[:limit], used or ["none"]
