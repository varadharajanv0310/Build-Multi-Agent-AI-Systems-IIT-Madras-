"""End-to-end orchestration: question in, disagreement map out."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from faultline.agents.council import (
    adjudicate, assess_commensurability, candidate_pairs, classify_gap,
    detect_conflicts, run_panel)
from faultline.agents.extraction import extract_claims, usable_for_conflict
from faultline.agents.framing import (
    calibrate_field, contract_text, criteria_text, frame_question)
from faultline.config import ROSTER, Role
from faultline.instrumentation import Ledger
from faultline.retrieval.models import Paper, RetrievalReport
from faultline.retrieval.fallback import search_with_fallback
from faultline.retrieval.openalex import OpenAlexClient, dedupe
from faultline.router import Router
from faultline.screening import screen_corpus
from faultline.store.db import Store


@dataclass
class Result:
    run_id: str
    question: str
    calibration: dict = field(default_factory=dict)
    spec: dict = field(default_factory=dict)
    report: RetrievalReport = field(default_factory=RetrievalReport)
    papers: list[Paper] = field(default_factory=list)
    included: list[Paper] = field(default_factory=list)
    borderline: list[Paper] = field(default_factory=list)
    claims: list[dict] = field(default_factory=list)
    pairs: list[Any] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    verdicts: list[dict] = field(default_factory=list)
    gaps: list[dict] = field(default_factory=list)
    ledger: Ledger | None = None

    @property
    def unresolved(self) -> list[dict]:
        return [v for v in self.verdicts if v.get("verdict") == "unresolved"]

    @property
    def explained(self) -> list[dict]:
        return [v for v in self.verdicts if v.get("verdict") == "explained"]

    @property
    def dismissed(self) -> list[dict]:
        return [v for v in self.verdicts if v.get("verdict") == "not_a_conflict"]


def run(
    question: str,
    *,
    per_query: int = 8,
    from_year: int = 2000,
    max_extract: int = 8,
    max_pairs: int = 24,
    max_conflicts: int = 6,
    store: Store | None = None,
    log: Callable[[str], None] = print,
) -> Result:
    store = store or Store()
    ledger = Ledger()
    run_id = store.start_run(
        mode="question", question=question,
        config={r.value: f"{s.provider}/{s.model_id}" for r, s in ROSTER.items()})
    router = Router(store, run_id, ledger)
    res = Result(run_id=run_id, question=question, ledger=ledger)

    try:
        # 1-2. Calibrate the field, then frame the question --------------------
        log("[1/7] field calibration")
        res.calibration = calibrate_field(router, question)
        log(f"      field: {res.calibration.get('field')}")

        log("[2/7] question framing + commensurability contract")
        res.spec = frame_question(router, question, res.calibration)

        # 3. Retrieve with generated, primary-study-targeted queries -----------
        log("[3/7] retrieval")
        client = OpenAlexClient()
        queries = res.spec.get("search_queries", []) or [question]
        res.report = RetrievalReport(query_strings=queries, databases=["openalex"])
        papers: list[Paper] = []
        sources: set[str] = set()
        for q in queries[:6]:
            hits, used = search_with_fallback(
                q, limit=per_query, from_year=from_year, primary=client, log=log)
            papers.extend(hits)
            sources.update(used)
        client.close()
        res.report.databases = sorted(sources - {"none"}) or ["none"]
        res.report.raw_hits = len(papers)
        res.papers = dedupe(papers)
        res.report.after_dedup = len(res.papers)
        res.report.abstract_only = sum(1 for p in res.papers if p.abstract)
        log(f"      {res.report.raw_hits} raw -> {len(res.papers)} unique")

        # 4. Screen (local, unmetered) -----------------------------------------
        log("[4/7] screening")
        res.included, res.borderline, _ = screen_corpus(
            router, store, run_id, res.papers, criteria_text(res.spec), res.report)
        log(f"      included {len(res.included)}, borderline {len(res.borderline)}, "
            f"excluded {res.report.excluded}")

        # 5. Extract qualified claims -------------------------------------------
        log("[5/7] claim extraction")
        targets = (res.included + res.borderline)[:max_extract]
        res.claims = extract_claims(router, store, run_id, targets, question)
        usable = [c for c in res.claims if usable_for_conflict(c)]
        log(f"      {len(res.claims)} claims, {len(usable)} usable")

        # 6. The council --------------------------------------------------------
        log("[6/7] commensurability (two opposed lineages)")
        contract = contract_text(res.spec)
        res.pairs = assess_commensurability(
            router, store, run_id, candidate_pairs(usable, max_pairs), contract)
        splits = sum(1 for p in res.pairs if p.lineage_agreement is False)
        log(f"      {len(res.pairs)} pairs assessed, {splits} lineage disagreements")

        res.conflicts = detect_conflicts(store, run_id, res.pairs)[:max_conflicts]
        log(f"      {len(res.conflicts)} genuine conflicts")

        log("[7/7] explanation panel + adjudication")
        for conflict in res.conflicts:
            explanations = run_panel(router, store, run_id, conflict)
            verdict = adjudicate(router, store, run_id, conflict, explanations)
            verdict["conflict"] = conflict
            verdict["explanations"] = explanations
            res.verdicts.append(verdict)
            if gap := classify_gap(router, store, run_id, conflict, verdict):
                gap["conflict"] = conflict
                res.gaps.append(gap)
        log(f"      explained {len(res.explained)}, unresolved {len(res.unresolved)}, "
            f"dismissed {len(res.dismissed)}, gaps {len(res.gaps)}")

    finally:
        store.finish_run(run_id, ledger.summary(), field=res.calibration.get("field"))
        router.close()

    return res


# --- paper mode ---------------------------------------------------------------

@dataclass
class PaperResult:
    run_id: str
    paper: Any
    claims: list[dict] = field(default_factory=list)
    positions: list[Any] = field(default_factory=list)
    ledger: Ledger | None = None

    @property
    def contradicted(self) -> list:
        return [p for p in self.positions if p.position == "contradicted"]

    @property
    def isolated(self) -> list:
        return [p for p in self.positions if p.position == "isolated"]

    @property
    def warnings(self) -> list:
        return [p for p in self.positions if p.strength_warning]


def run_paper(
    source: str,
    *,
    max_claims: int = 4,
    per_query: int = 10,
    from_year: int = 2000,
    store: Store | None = None,
    log: Callable[[str], None] = print,
) -> PaperResult:
    """Position a paper's own claims against its literature.

    Question mode asks where a field disagrees. This asks the sharper question a
    researcher actually has before submitting: is my finding corroborated,
    contradicted, or standing alone?
    """
    from faultline.agents.paper_mode import derive_question, load_paper, position_claim

    store = store or Store()
    ledger = Ledger()

    log("[1/6] loading paper")
    paper = load_paper(source)
    log(f"      {paper.title[:70]}")

    run_id = store.start_run(
        mode="paper", question=None, paper_ref=paper.id,
        config={r.value: f"{s.provider}/{s.model_id}" for r, s in ROSTER.items()})
    router = Router(store, run_id, ledger)
    res = PaperResult(run_id=run_id, paper=paper, ledger=ledger)

    try:
        log("[2/6] extracting this paper's own claims")
        res.claims = extract_claims(router, store, run_id, [paper],
                                    paper.title or "this paper")
        own = [c for c in res.claims if usable_for_conflict(c)][:max_claims]
        log(f"      {len(res.claims)} claims, checking {len(own)}")

        client = OpenAlexClient()
        for i, claim in enumerate(own, 1):
            log(f"[{2 + i}/6] claim {i}: deriving question and searching literature")
            try:
                derived = derive_question(router, claim, paper.title or "")
            except Exception as e:
                log(f"      skipped ({type(e).__name__})")
                continue
            if not derived.get("is_testable"):
                log("      not an empirical claim; skipped")
                continue
            question = derived["question"]
            log(f"      Q: {question[:66]}")

            # Retrieve and extract from the surrounding literature, excluding
            # the paper itself — a claim cannot corroborate itself.
            others: list[Paper] = []
            try:
                hits, used = search_with_fallback(
                    question, limit=per_query, from_year=from_year,
                    primary=client, log=log)
                log(f"      sources: {', '.join(used)}")
                others = [p for p in hits
                          if p.id != paper.id and (not p.doi or p.doi != paper.doi)]
            except Exception as e:
                # Never swallow this. An empty corpus from a failed search looks
                # identical to a claim that genuinely stands alone, and quietly
                # reporting "isolated" would be a false result.
                log(f"      retrieval FAILED ({type(e).__name__}: {e}) - "
                    f"positioning skipped rather than reported as isolated")
                continue
            others = dedupe(others)[:per_query]
            lit_claims = extract_claims(router, store, run_id, others, question) if others else []
            comparable = [c for c in lit_claims if usable_for_conflict(c)]
            log(f"      {len(others)} papers -> {len(comparable)} comparable findings")

            res.positions.append(position_claim(router, claim, question, comparable))
        client.close()

    finally:
        store.finish_run(run_id, ledger.summary())
        router.close()

    return res
