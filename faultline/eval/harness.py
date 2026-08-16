"""Replay published reviews and diff against what their authors concluded."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from faultline.config import SETTINGS, Role
from faultline.retrieval.openalex import reconstruct_abstract
from faultline.router import Router

OA = "https://api.openalex.org"

# Papers ABOUT systematic review methodology dominate any search containing
# the phrase "meta-analysis", so they are filtered by title rather than trusted
# to rank below the topical reviews. PRISMA alone has 28,000 citations.
_METHODOLOGY = re.compile(
    r"\b(prisma|moose|cochrane handbook|reporting guideline|risk of bias tool|"
    r"grade approach|how to (read|conduct)|methodological quality)\b", re.I)


@dataclass
class BenchmarkCase:
    """One replayed review."""
    question: str
    field: str
    review_query: str                 # topical terms, no "meta-analysis"
    review_doi: str | None = None     # pin a specific review if known
    min_citations: int = 50
    # Terms that MUST appear literally in the review title. Topic-word overlap
    # alone is too weak a gate: any two education reviews share "student".
    must_contain: tuple[str, ...] = ()
    notes: str = ""


@dataclass
class Review:
    id: str
    title: str
    doi: str | None
    year: int | None
    cited_by: int
    abstract: str | None
    referenced_works: list[str] = field(default_factory=list)


@dataclass
class EvalResult:
    case: BenchmarkCase
    review: Review | None = None

    # retrieval
    ground_truth_refs: int = 0
    retrieved_overlap: int = 0
    papers_retrieved: int = 0
    papers_included: int = 0

    # conflict analysis
    conflicts_found: int = 0
    explained: int = 0
    unresolved: int = 0
    dismissed: int = 0
    gaps: int = 0

    # agreement with the review's own conclusion
    review_reported_heterogeneity: bool | None = None
    review_moderator: str | None = None
    our_moderators: list[str] = field(default_factory=list)
    moderator_match: bool | None = None

    lineage_split_rate: float = 0.0
    hosted_calls: int = 0
    local_share: float = 0.0
    error: str | None = None

    @property
    def retrieval_recall(self) -> float | None:
        """Share of the review's cited works that our search also surfaced.

        A lower bound on true recall, not an exact figure: a review's
        reference list includes background and methods citations that were
        never candidate studies. Reported as such rather than dressed up.
        """
        if not self.ground_truth_refs:
            return None
        return self.retrieved_overlap / self.ground_truth_refs

    @property
    def false_conflict_rate(self) -> float | None:
        """Conflicts we raised that our own adjudicator then dismissed.

        The number that decides whether anyone would use this: a tool that
        cries contradiction on studies that agree gets uninstalled after one
        paper.
        """
        if not self.conflicts_found:
            return None
        return self.dismissed / self.conflicts_found

    @property
    def abstain_rate(self) -> float | None:
        if not self.conflicts_found:
            return None
        return self.unresolved / self.conflicts_found

    def row(self) -> dict[str, Any]:
        return {
            "question": self.case.question[:60],
            "field": self.case.field,
            "review": (self.review.title[:50] if self.review else "not found"),
            "gt_refs": self.ground_truth_refs,
            "recall": (None if self.retrieval_recall is None
                       else round(self.retrieval_recall, 3)),
            "retrieved": self.papers_retrieved,
            "included": self.papers_included,
            "conflicts": self.conflicts_found,
            "explained": self.explained,
            "unresolved": self.unresolved,
            "dismissed": self.dismissed,
            "false_conflict_rate": (None if self.false_conflict_rate is None
                                    else round(self.false_conflict_rate, 3)),
            "abstain_rate": (None if self.abstain_rate is None
                             else round(self.abstain_rate, 3)),
            "review_heterogeneity": self.review_reported_heterogeneity,
            "review_moderator": (self.review_moderator or "")[:48],
            "our_moderators": ", ".join(sorted(set(self.our_moderators)))[:40],
            "moderator_match": self.moderator_match,
            "lineage_split": round(self.lineage_split_rate, 3),
            "hosted_calls": self.hosted_calls,
            "local_share": round(self.local_share, 3),
            "error": self.error,
        }


# --- ground truth discovery ---------------------------------------------------

def _client() -> httpx.Client:
    return httpx.Client(timeout=90,
                        headers={"User-Agent": SETTINGS.user_agent},
                        follow_redirects=True)


def find_review(case: BenchmarkCase) -> Review | None:
    """Locate the published review whose conclusions we will diff against."""
    with _client() as c:
        params: dict[str, Any] = {"mailto": SETTINGS.polite_pool_email}
        if case.review_doi:
            r = c.get(f"{OA}/works/doi:{case.review_doi}", params=params)
            if r.status_code == 200:
                return _to_review(r.json())
            return None

        # Deliberately NOT sorted by citations. Sorting by cited_by_count
        # discards relevance ranking entirely and returns the most-cited paper
        # that vaguely matches — which chose "food prices and diet cost" as the
        # ground truth for a minimum-wage question. Relevance ranks first, and
        # topical fit is then checked against the title explicitly.
        r = c.get(f"{OA}/works", params={
            **params,
            "search": case.review_query,
            "filter": f"type:review,cited_by_count:>{case.min_citations}",
            "per-page": 50,
        })
        if r.status_code != 200:
            return None

        want = _content_words(case.review_query)
        best: Review | None = None
        best_score = 0.0
        for rank, raw in enumerate(r.json().get("results", [])):
            title = raw.get("display_name") or ""
            if _METHODOLOGY.search(title):
                continue                      # PRISMA and friends
            refs = raw.get("referenced_works") or []
            if len(refs) < 10:
                continue                      # too thin to be a real synthesis

            overlap = _content_words(title) & want
            # A review sharing fewer than 60% of the query's topical terms is
            # about something else, however well cited. The bar is high on
            # purpose: no ground truth is far better than wrong ground truth,
            # and a looser gate accepted "flipped classroom" for a class-size
            # question and "unpaid caregivers" for a minimum-wage one.
            if len(overlap) / max(len(want), 1) < 0.6:
                continue
            # The subject of the question must appear literally. Topic-word
            # overlap alone lets a review about students match any other review
            # about students.
            if case.must_contain and not any(
                    t in title.lower() for t in case.must_contain):
                continue

            review = _to_review(raw)
            score = (len(overlap) / len(want)) * 2.0 + 1.0 / (rank + 1)
            if score > best_score:
                best, best_score = review, score
        return best


_STOP = {"the", "of", "and", "in", "on", "for", "a", "an", "to", "with", "by",
         "effects", "effect", "trials", "randomized", "randomised", "controlled",
         "study", "studies", "review", "meta", "analysis", "systematic"}


def _content_words(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in _STOP}


def _to_review(raw: dict) -> Review:
    return Review(
        id=(raw.get("id") or "").rsplit("/", 1)[-1],
        title=raw.get("display_name") or "",
        doi=(raw.get("doi") or "").replace("https://doi.org/", "") or None,
        year=raw.get("publication_year"),
        cited_by=raw.get("cited_by_count", 0) or 0,
        abstract=reconstruct_abstract(raw.get("abstract_inverted_index")),
        referenced_works=[w.rsplit("/", 1)[-1] for w in (raw.get("referenced_works") or [])],
    )


# --- what did the review itself conclude? ------------------------------------

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "reported_heterogeneity": {"type": "boolean"},
        "heterogeneity_explained": {"type": "boolean"},
        "moderator": {"type": "string"},
        "stated_gap": {"type": "string"},
    },
    "required": ["reported_heterogeneity", "heterogeneity_explained", "moderator"],
}

REVIEW_SYSTEM = """Read this systematic review or meta-analysis abstract and \
report what ITS AUTHORS concluded about disagreement between the included \
studies.

Report only what the abstract states. Do not infer from your own knowledge of \
the topic.

- reported_heterogeneity: did the authors report that the included studies \
varied or disagreed in their findings? Statistical heterogeneity, inconsistent \
results, conflicting trials all count.
- heterogeneity_explained: did they identify something that ACCOUNTS for the \
variation - a subgroup, dose threshold, population characteristic, design
difference?
- moderator: name it in a few words if so, otherwise "none identified".
- stated_gap: what the authors say still needs research, if anything."""


def read_review_conclusion(router: Router, review: Review) -> dict:
    if not review.abstract:
        return {}
    try:
        res = router.complete(
            Role.ADJUDICATION,
            [{"role": "system", "content": REVIEW_SYSTEM},
             {"role": "user", "content":
                 f"TITLE: {review.title}\n\nABSTRACT:\n{review.abstract[:6000]}"}],
            REVIEW_SCHEMA, stage="eval_ground_truth")
        return res.data
    except Exception:
        return {}


# --- scoring ------------------------------------------------------------------

_STANCE_TO_WORDS = {
    "population": {"population", "subgroup", "baseline", "deficien", "severity",
                   "age", "sex", "risk", "status"},
    "dose_exposure": {"dose", "dosage", "duration", "regimen", "formulation",
                      "intensity", "frequency", "adherence", "exposure"},
    "measurement": {"outcome", "endpoint", "measure", "definition", "timepoint",
                    "follow-up", "assessment"},
    "power_design": {"power", "sample", "design", "quality", "bias", "trial",
                     "analysis", "method"},
}


def moderator_agrees(review_moderator: str, our_stances: list[str]) -> bool | None:
    """Does our winning stance describe the same moderator the review named?

    Compared at the level of moderator TYPE rather than exact wording: a review
    saying "baseline 25(OH)D status" and our "population" stance are the same
    finding expressed at different granularity.
    """
    if not review_moderator or review_moderator.strip().lower() in (
            "none identified", "none", "n/a", ""):
        return None
    text = review_moderator.lower()
    for stance in our_stances:
        for word in _STANCE_TO_WORDS.get(stance, set()):
            if word in text:
                return True
    return False


def evaluate(case: BenchmarkCase, router: Router, result_obj, review: Review | None,
             ) -> EvalResult:
    """Score one pipeline run against one published review."""
    ev = EvalResult(case=case, review=review)

    retrieved_ids = {p.id for p in result_obj.papers}
    ev.papers_retrieved = len(retrieved_ids)
    ev.papers_included = len(result_obj.included)

    if review:
        ev.ground_truth_refs = len(review.referenced_works)
        ev.retrieved_overlap = len(retrieved_ids & set(review.referenced_works))
        conclusion = read_review_conclusion(router, review)
        ev.review_reported_heterogeneity = conclusion.get("reported_heterogeneity")
        ev.review_moderator = conclusion.get("moderator")

    ev.conflicts_found = len(result_obj.verdicts)
    ev.explained = len(result_obj.explained)
    ev.unresolved = len(result_obj.unresolved)
    ev.dismissed = len(result_obj.dismissed)
    ev.gaps = len(result_obj.gaps)
    ev.our_moderators = [v["winning_stance"] for v in result_obj.verdicts
                         if v.get("winning_stance")]
    ev.moderator_match = moderator_agrees(ev.review_moderator or "", ev.our_moderators)

    pairs = result_obj.pairs or []
    if pairs:
        ev.lineage_split_rate = sum(
            1 for p in pairs if p.lineage_agreement is False) / len(pairs)

    if result_obj.ledger:
        ev.hosted_calls = result_obj.ledger.hosted_calls
        ev.local_share = result_obj.ledger.local_share
    return ev


def render_table(results: list[EvalResult]) -> str:
    rows = [r.row() for r in results]
    lines = ["", "=" * 78, "EVALUATION vs PUBLISHED REVIEWS", "=" * 78]
    for r in rows:
        lines.append(f"\n  {r['question']}")
        lines.append(f"    field            {r['field']}")
        lines.append(f"    review           {r['review']}")
        if r["error"]:
            lines.append(f"    ERROR            {r['error']}")
            continue
        recall = "n/a" if r["recall"] is None else f"{r['recall']:.1%}"
        lines.append(f"    retrieval recall {recall}  "
                     f"({r['gt_refs']} works cited by the review)")
        lines.append(f"    corpus           {r['retrieved']} retrieved, "
                     f"{r['included']} included")
        lines.append(f"    conflicts        {r['conflicts']}  "
                     f"(explained {r['explained']}, unresolved {r['unresolved']}, "
                     f"dismissed {r['dismissed']})")
        fcr = "n/a" if r["false_conflict_rate"] is None else f"{r['false_conflict_rate']:.1%}"
        abst = "n/a" if r["abstain_rate"] is None else f"{r['abstain_rate']:.1%}"
        lines.append(f"    false-conflict   {fcr}     abstain {abst}")
        lines.append(f"    review said      heterogeneity={r['review_heterogeneity']}  "
                     f"moderator: {r['review_moderator'] or 'none'}")
        lines.append(f"    we said          {r['our_moderators'] or 'none'}  "
                     f"-> match={r['moderator_match']}")
        lines.append(f"    lineage split    {r['lineage_split']:.1%}   "
                     f"hosted calls {r['hosted_calls']}   "
                     f"local {r['local_share']:.0%}")
    lines.append("\n" + "=" * 78)
    return "\n".join(lines)


def to_json(results: list[EvalResult]) -> str:
    return json.dumps([r.row() for r in results], indent=2)
