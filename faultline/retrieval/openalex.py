"""OpenAlex client — the domain-general backbone.

OpenAlex indexes ~250M works across every field, which is what lets the system
stay domain-general instead of being pinned to one literature. PubMed and
arXiv are enrichment layers on top, not the backbone.
"""
from __future__ import annotations

import re
import time
from typing import Any, Iterator

import httpx

from faultline.config import SETTINGS
from faultline.retrieval.models import Paper

BASE = "https://api.openalex.org"


class RateLimited(RuntimeError):
    """Quota is spent for the day. Not retryable — fall back to another source."""


def reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str | None:
    """OpenAlex ships abstracts as an inverted index for licensing reasons.

    Reconstructing them is not optional: the abstract is the entire input to
    the screening stage, and without it every paper would have to be fetched
    in full text just to decide relevance.
    """
    if not inverted:
        return None
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted.items():
        positions.extend((i, word) for i in idxs)
    if not positions:
        return None
    positions.sort()
    return " ".join(word for _, word in positions)


_STOPWORDS = {
    "does", "do", "did", "is", "are", "was", "were", "can", "could", "should",
    "would", "the", "a", "an", "of", "for", "on", "in", "to", "and", "or",
    "what", "which", "how", "why", "when", "there", "any", "effect", "effects",
}


def clean_query(question: str, drop_stopwords: bool = True) -> str:
    """Turn a natural-language question into something OpenAlex will accept.

    Its search parser rejects punctuation that any real question carries — a
    trailing '?' alone returns HTTP 400. Interrogative stopwords are also
    dropped because they contribute nothing to relevance ranking and dilute
    the terms that do.
    """
    cleaned = re.sub(r"[^\w\s-]", " ", question)
    tokens = [t for t in cleaned.split() if t]
    if drop_stopwords:
        kept = [t for t in tokens if t.lower() not in _STOPWORDS]
        # Never strip a query down to nothing; fall back to the raw tokens.
        if len(kept) >= 2:
            tokens = kept
    return " ".join(tokens).strip()


class OpenAlexClient:
    def __init__(self, timeout: float = 60.0, max_retries: int = 5,
                 min_interval: float = 0.15):
        self.max_retries = max_retries
        # Client-side throttle. Cheaper than discovering the limit via 429s,
        # which cost a corpus rather than a request.
        self._min_interval = min_interval
        self._last_request = 0.0
        # Once the daily budget is gone it is gone. Re-checking on every
        # query wastes a round-trip each time.
        self._exhausted = False
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": SETTINGS.user_agent, "Accept": "application/json"},
            follow_redirects=True,
        )
        # The polite pool is materially faster and far less likely to 429.
        self._mailto = SETTINGS.polite_pool_email or None

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._exhausted:
            raise RateLimited('OpenAlex daily credit already exhausted this run')
        if self._mailto:
            params = {**params, "mailto": self._mailto}

        # OpenAlex's polite pool allows ~10 requests/second. Firing queries back
        # to back trips it, and the resulting 429s silently shrink the corpus —
        # a run that should have returned 100+ papers came back with 14, which
        # is indistinguishable from "the literature is thin" unless you look.
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

        last: Exception | None = None
        for attempt in range(self.max_retries):
            self._last_request = time.monotonic()
            try:
                r = self._client.get(f"{BASE}{path}", params=params)
            except httpx.HTTPError as e:
                last = e
                time.sleep(1.5 ** attempt)
                continue

            if r.status_code == 429:
                retry_after = float(r.headers.get("Retry-After") or 0)
                # OpenAlex meters by daily credit, and an exhausted budget
                # returns Retry-After in HOURS (observed: 57036 seconds).
                # Retrying that is not backoff, it is waiting until tomorrow —
                # and sleeping through it burned ~150s per search before
                # anything fell through to the keyless sources. Give up
                # immediately so the caller can use Crossref or Europe PMC.
                if retry_after > 60:
                    self._exhausted = True
                    raise RateLimited(
                        f"OpenAlex daily credit exhausted; resets in "
                        f"{retry_after / 3600:.1f}h")
                wait = retry_after or min(2 ** attempt, 8)
                last = RuntimeError(f"rate limited (429), waited {wait:.0f}s")
                time.sleep(wait)
                continue
            if r.status_code >= 500:
                last = RuntimeError(f"server error {r.status_code}")
                time.sleep(1.5 ** attempt)
                continue
            try:
                r.raise_for_status()
            except httpx.HTTPError as e:
                raise RuntimeError(f"openalex {path}: {e}") from e
            return r.json()

        raise RuntimeError(
            f"openalex {path} failed after {self.max_retries} attempts: "
            f"{last or 'no response'}")

    def search(
        self,
        query: str,
        *,
        limit: int = 200,
        from_year: int | None = None,
        to_year: int | None = None,
        types: tuple[str, ...] = ("article", "review", "preprint"),
        require_abstract: bool = True,
    ) -> Iterator[Paper]:
        """Cursor-paginated search. Yields lazily so a wide query can be cut
        off by the caller without paying for pages it will not screen."""
        filters = [f"type:{'|'.join(types)}"]
        if from_year:
            filters.append(f"from_publication_date:{from_year}-01-01")
        if to_year:
            filters.append(f"to_publication_date:{to_year}-12-31")
        if require_abstract:
            filters.append("has_abstract:true")

        query = clean_query(query)
        cursor = "*"
        seen = 0
        while cursor and seen < limit:
            page = self._get("/works", {
                "search": query,
                "filter": ",".join(filters),
                "per-page": min(200, limit - seen),
                "cursor": cursor,
            })
            results = page.get("results", [])
            if not results:
                return
            for raw in results:
                seen += 1
                yield self.to_paper(raw)
                if seen >= limit:
                    return
            cursor = page.get("meta", {}).get("next_cursor")

    def count(self, query: str, **kw: Any) -> int:
        """How many works match, before we fetch any. This is the denominator
        for the retrieval report."""
        filters = ["type:article|review|preprint"]
        if kw.get("from_year"):
            filters.append(f"from_publication_date:{kw['from_year']}-01-01")
        if kw.get("to_year"):
            filters.append(f"to_publication_date:{kw['to_year']}-12-31")
        page = self._get("/works", {
            "search": clean_query(query), "filter": ",".join(filters), "per-page": 1})
        return page.get("meta", {}).get("count", 0)

    def by_doi(self, doi: str) -> Paper | None:
        doi = doi.strip().replace("https://doi.org/", "")
        try:
            return self.to_paper(self._get(f"/works/doi:{doi}", {}))
        except Exception:
            return None

    @staticmethod
    def to_paper(raw: dict[str, Any]) -> Paper:
        ids = raw.get("ids", {}) or {}
        loc = raw.get("primary_location") or {}
        source = loc.get("source") or {}
        oa = raw.get("open_access", {}) or {}

        pmid = (ids.get("pmid") or "").rsplit("/", 1)[-1] or None
        pmcid = (ids.get("pmcid") or "").rsplit("/", 1)[-1] or None

        arxiv_id = None
        landing = (loc.get("landing_page_url") or "")
        if "arxiv.org" in landing:
            arxiv_id = landing.rstrip("/").rsplit("/", 1)[-1]

        return Paper(
            id=(raw.get("id") or "").rsplit("/", 1)[-1] or raw.get("doi") or "unknown",
            title=raw.get("display_name") or raw.get("title") or "",
            year=raw.get("publication_year"),
            doi=(raw.get("doi") or "").replace("https://doi.org/", "") or None,
            venue=source.get("display_name"),
            authors=[a.get("author", {}).get("display_name", "")
                     for a in (raw.get("authorships") or [])][:25],
            abstract=reconstruct_abstract(raw.get("abstract_inverted_index")),
            oa_status=oa.get("oa_status"),
            oa_url=oa.get("oa_url"),
            pmid=pmid,
            pmcid=pmcid,
            arxiv_id=arxiv_id,
            cited_by_count=raw.get("cited_by_count", 0) or 0,
            type=raw.get("type"),
            # A retracted source cited as live evidence is exactly the kind of
            # defect this system should surface rather than silently inherit.
            retracted=bool(raw.get("is_retracted")),
            source="openalex",
        )

    def close(self) -> None:
        self._client.close()


def dedupe(papers: list[Paper]) -> list[Paper]:
    """Collapse duplicates by DOI, then by normalised title.

    Cross-database retrieval routinely returns the same study three times.
    Left in, duplicates would inflate the denominator and, worse, let a study
    appear to 'replicate' itself during conflict analysis.
    """
    by_doi: dict[str, Paper] = {}
    by_title: dict[str, Paper] = {}
    out: list[Paper] = []
    for p in papers:
        if p.doi:
            key = p.doi.lower()
            if key in by_doi:
                continue
            by_doi[key] = p
        title = p.norm_title
        if title and title in by_title:
            continue
        if title:
            by_title[title] = p
        out.append(p)
    return out
