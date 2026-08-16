"""The two things a researcher actually wants.

    review_paper(...)   paste your paper, get it reviewed before a referee does
    answer_question(...) ask a question, get an answer grounded in the papers

Both reuse the same engine: field calibration, retrieval, screening, and claim
extraction with qualifiers. What differs is what the council does with the
findings at the end.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from faultline.agents.answer import Answer, answer_question as _synthesise
from faultline.agents.extraction import extract_claims, usable_for_conflict
from faultline.agents.framing import calibrate_field, criteria_text, frame_question
from faultline.agents.paper_mode import load_paper
from faultline.agents.review import PaperReview, appraise, position, run_reviewer_panel
from faultline.config import ROSTER
from faultline.instrumentation import Ledger
from faultline.retrieval.fallback import search_with_fallback
from faultline.retrieval.models import Paper, RetrievalReport
from faultline.retrieval.openalex import OpenAlexClient, dedupe
from faultline.router import Router
from faultline.screening import screen_corpus
from faultline.store.db import Store

Log = Callable[[str], None]


def _gather(router, store, run_id, question, *, per_query, from_year,
            max_papers, log: Log) -> tuple[list[dict], RetrievalReport, dict]:
    """Calibrate → frame → retrieve → screen → extract. Shared by both modes."""
    log("Calibrating the field…")
    calibration = calibrate_field(router, question)
    log(f"Field: {calibration.get('field', 'unknown')}")

    log("Building the search strategy…")
    spec = frame_question(router, question, calibration)
    queries = spec.get("search_queries") or [question]

    log(f"Searching ({len(queries[:5])} queries)…")
    client = OpenAlexClient()
    report = RetrievalReport(query_strings=queries)
    papers: list[Paper] = []
    sources: set[str] = set()
    for q in queries[:5]:
        hits, used = search_with_fallback(q, limit=per_query,
                                          from_year=from_year, primary=client, log=log)
        papers.extend(hits)
        sources.update(used)
    client.close()
    report.raw_hits = len(papers)
    papers = dedupe(papers)[:max_papers]
    report.after_dedup = len(papers)
    report.databases = sorted(sources - {"none"}) or ["none"]
    log(f"Found {report.raw_hits} papers → {len(papers)} unique "
        f"(via {', '.join(report.databases)})")

    if not papers:
        return [], report, calibration

    log(f"Screening {len(papers)} papers…")
    included, borderline, _ = screen_corpus(
        router, store, run_id, papers, criteria_text(spec), report)
    log(f"{len(included)} relevant, {len(borderline)} borderline")

    targets = (included + borderline)[:12]
    log(f"Extracting findings from {len(targets)} papers…")
    claims = extract_claims(router, store, run_id, targets, question)
    usable = [c for c in claims if usable_for_conflict(c)]
    log(f"Extracted {len(claims)} findings ({len(usable)} usable)")
    return usable, report, calibration


# --- Mode 1: review my paper --------------------------------------------------

@dataclass
class ReviewResult:
    run_id: str
    paper: Any = None
    review: PaperReview = field(default_factory=PaperReview)
    report: RetrievalReport = field(default_factory=RetrievalReport)
    calibration: dict = field(default_factory=dict)
    ledger: Ledger | None = None
    error: str = ""
    degraded: str = ""


def review_paper(source: str, *, per_query: int = 8, from_year: int = 2000,
                 max_papers: int = 24, store: Store | None = None,
                 log: Log = print) -> ReviewResult:
    store = store or Store()
    ledger = Ledger()

    log("Loading your paper…")
    try:
        paper = load_paper(source)
    except Exception as e:
        return ReviewResult(run_id="", error=f"Could not read that paper: {e}")

    run_id = store.start_run(mode="paper", paper_ref=paper.id,
                             config={r.value: f"{s.provider}/{s.model_id}"
                                     for r, s in ROSTER.items()})
    router = Router(store, run_id, ledger)
    res = ReviewResult(run_id=run_id, paper=paper, ledger=ledger)
    res.review.paper_title = paper.title or "your paper"

    try:
        log("Reading your claims…")
        own = extract_claims(router, store, run_id, [paper], paper.title or "this paper")
        res.review.claims = own
        if not own:
            res.error = ("No empirical claims could be extracted. If you pasted a "
                         "title or DOI, try the full abstract or upload the PDF.")
            return res
        log(f"Found {len(own)} claims in your paper")

        topic = (paper.title or "") + ". " + (own[0].get("text", "") if own else "")
        # Literature is valuable but not required. Three reviewers can critique
        # a paper on its own merits, and losing the whole review because a free
        # tier ran out is the worst possible failure mode.
        try:
            literature, report, calibration = _gather(
                router, store, run_id, topic, per_query=per_query,
                from_year=from_year, max_papers=max_papers, log=log)
            res.review.literature = literature
            res.report = report
            res.calibration = calibration
        except Exception as e:
            log(f"Could not search the literature ({type(e).__name__}). "
                f"Reviewing your paper on its own merits.")
            res.degraded = (
                "The literature search failed, so this review covers your paper "
                "alone. Positioning and must-cite lists need the literature and "
                "are therefore unavailable.")

        log("Convening the reviewer panel (3 lineages)…")
        res.review.objections = run_reviewer_panel(router, res.review)
        log(f"{len(res.review.objections)} objections raised")

        log("Appraising the evidence base…")
        res.review.appraisal = appraise(router, res.review)

        if res.review.literature:
            log("Positioning your contribution…")
            res.review.positioning = position(router, res.review)

    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
    finally:
        store.finish_run(run_id, ledger.summary(), field=res.calibration.get("field"))
        router.close()
    return res


# --- Mode 2: answer a question ------------------------------------------------

@dataclass
class AnswerResult:
    run_id: str
    answer: Answer | None = None
    report: RetrievalReport = field(default_factory=RetrievalReport)
    calibration: dict = field(default_factory=dict)
    claims: list[dict] = field(default_factory=list)
    ledger: Ledger | None = None
    error: str = ""


def answer_question(question: str, *, per_query: int = 10, from_year: int = 2000,
                    max_papers: int = 30, store: Store | None = None,
                    log: Log = print) -> AnswerResult:
    store = store or Store()
    ledger = Ledger()
    run_id = store.start_run(mode="question", question=question,
                             config={r.value: f"{s.provider}/{s.model_id}"
                                     for r, s in ROSTER.items()})
    router = Router(store, run_id, ledger)
    res = AnswerResult(run_id=run_id, ledger=ledger)

    try:
        claims, report, calibration = _gather(
            router, store, run_id, question, per_query=per_query,
            from_year=from_year, max_papers=max_papers, log=log)
        res.claims, res.report, res.calibration = claims, report, calibration

        log("Synthesising an answer…")
        res.answer = _synthesise(router, question, claims)
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
    finally:
        store.finish_run(run_id, ledger.summary(), field=res.calibration.get("field"))
        router.close()
    return res
