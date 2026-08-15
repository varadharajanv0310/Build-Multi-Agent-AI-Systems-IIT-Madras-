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
        for q in queries[:6]:
            try:
                papers.extend(client.search(q, limit=per_query, from_year=from_year))
            except Exception as e:
                log(f"      query failed ({type(e).__name__}): {q[:50]}")
        client.close()
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
