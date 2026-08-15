"""Retrieval data types."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Paper:
    id: str                       # OpenAlex work id, else DOI
    title: str
    year: int | None = None
    doi: str | None = None
    venue: str | None = None
    authors: list[str] = field(default_factory=list)
    abstract: str | None = None
    oa_status: str | None = None          # gold | green | hybrid | bronze | closed
    oa_url: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    arxiv_id: str | None = None
    cited_by_count: int = 0
    type: str | None = None               # article | review | preprint ...
    retracted: bool = False
    source: str = "openalex"
    fulltext: str | None = None
    fulltext_source: str | None = None    # pmc_xml | arxiv_tex | pdf | abstract_only | none

    @property
    def has_text(self) -> bool:
        return bool(self.fulltext or self.abstract)

    @property
    def norm_title(self) -> str:
        """Aggressively normalised title for dedup across sources that
        disagree about punctuation, case, and trailing periods."""
        return re.sub(r"[^a-z0-9]+", " ", (self.title or "").lower()).strip()

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "doi": self.doi,
            "title": self.title,
            "year": self.year,
            "venue": self.venue,
            "authors_json": self.authors,
            "oa_status": self.oa_status,
            "fulltext_source": self.fulltext_source,
            "retracted": int(self.retracted),
            "metadata_json": {
                "pmid": self.pmid, "pmcid": self.pmcid, "arxiv_id": self.arxiv_id,
                "cited_by_count": self.cited_by_count, "type": self.type,
                "oa_url": self.oa_url, "source": self.source,
            },
        }


@dataclass
class RetrievalReport:
    """The denominator. This is the number no chat interface can produce, and
    it is reported on the main output rather than buried in a log."""

    query_strings: list[str] = field(default_factory=list)
    databases: list[str] = field(default_factory=list)
    raw_hits: int = 0
    after_dedup: int = 0
    screened: int = 0
    included: int = 0
    excluded: int = 0
    borderline: int = 0
    fulltext_acquired: int = 0
    abstract_only: int = 0
    no_text: int = 0
    known_targets: int = 0        # e.g. a replayed review's included studies
    known_targets_found: int = 0

    @property
    def recall_estimate(self) -> float | None:
        """Measured against a known target set when replaying a published
        review. None when there is no ground truth — reported honestly as
        unknown rather than guessed at."""
        if not self.known_targets:
            return None
        return self.known_targets_found / self.known_targets

    @property
    def workload_reduction(self) -> float:
        """Share of the retrieved pool a human no longer has to read."""
        if not self.after_dedup:
            return 0.0
        return 1 - (self.included + self.borderline) / self.after_dedup

    def summary(self) -> dict[str, Any]:
        d = asdict(self)
        d["recall_estimate"] = self.recall_estimate
        d["workload_reduction"] = round(self.workload_reduction, 4)
        return d

    def render(self) -> str:
        recall = ("unknown (no ground-truth set)" if self.recall_estimate is None
                  else f"{self.recall_estimate:.1%} "
                       f"({self.known_targets_found}/{self.known_targets} known studies)")
        return "\n".join([
            "",
            "=" * 68,
            "RETRIEVAL",
            "=" * 68,
            f"  databases          {', '.join(self.databases) or 'none'}",
            f"  queries            {len(self.query_strings)}",
            f"  raw hits           {self.raw_hits}",
            f"  after dedup        {self.after_dedup}",
            f"  screened           {self.screened}",
            f"  included           {self.included}",
            f"  borderline         {self.borderline}",
            f"  excluded           {self.excluded}",
            f"  full text          {self.fulltext_acquired} "
            f"(abstract-only {self.abstract_only}, none {self.no_text})",
            f"  workload reduction {self.workload_reduction:.1%}",
            f"  recall             {recall}",
            "=" * 68,
        ])
