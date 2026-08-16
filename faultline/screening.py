"""Relevance screening — high volume, local, and deliberately recall-biased.

The asymmetry that governs this stage: a MISSED study can invalidate the whole
analysis, because a contradiction you never retrieved reads as consensus. A
falsely included study costs one extra pass later. So uncertainty resolves
toward `borderline`, never toward `exclude`.

This is also the stage that makes $0 possible. Thousands of judgements per run
happen here, on local hardware, unmetered. Hosted free tiers only ever see
calls that scale with conflict count.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from faultline.config import Role
from faultline.retrieval.models import Paper, RetrievalReport
from faultline.router import Router
from faultline.store.db import Store

SCREENING_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["include", "exclude", "borderline"]},
        "reason": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["decision", "reason", "confidence"],
}

SYSTEM = """You screen research papers for a review whose purpose is to find \
where a literature DISAGREES WITH ITSELF.

That purpose changes the job. You are building the pool of studies that will be \
compared against each other, so breadth is the point. You judge ONLY whether a \
paper bears on the question - not whether the study is good, whether you agree \
with it, or whether its finding is plausible.

Decision rule, and it is asymmetric on purpose:
- "include"    - reports an empirical result bearing on the question
- "borderline" - you are unsure, or the abstract is too thin to tell
- "exclude"    - genuinely a different question or intervention, or reports no
                 empirical result at all

INCLUDE a paper even when it differs in population, dose or intensity, setting, \
follow-up length, or outcome variant. Those differences are not grounds for \
exclusion - they are the candidate explanations for why studies conflict, and \
excluding them destroys the analysis before it starts.

Never exclude for: small sample, weak design, old publication date, a null \
result, or a finding that seems wrong. Null and surprising results are the most \
valuable inputs here.

Missing a relevant study is far worse than including an irrelevant one: a \
contradiction that was never retrieved looks exactly like consensus, and a \
narrow screen manufactures the false agreement this system exists to prevent. \
When in doubt, choose "borderline" - never "exclude".

Give a one-line reason. For anything not clearly included, that reason is what \
a reviewer will be asked to defend, so make it specific."""


@dataclass
class ScreeningDecision:
    paper_id: str
    decision: str
    reason: str
    confidence: float
    model_id: str
    lineage: str


def _prompt(paper: Paper, criteria: str) -> list[dict[str, str]]:
    abstract = (paper.abstract or "").strip()
    if len(abstract) > 4000:
        abstract = abstract[:4000] + " ...[truncated]"
    body = (
        f"INCLUSION CRITERIA\n{criteria}\n\n"
        f"PAPER\n"
        f"Title: {paper.title}\n"
        f"Year: {paper.year or 'unknown'}\n"
        f"Type: {paper.type or 'unknown'}\n"
        f"Venue: {paper.venue or 'unknown'}\n"
        f"Abstract: {abstract or '[no abstract available]'}\n\n"
        f"Does this paper meet the criteria?"
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": body}]


def screen_corpus(
    router: Router,
    store: Store,
    run_id: str,
    papers: list[Paper],
    criteria: str,
    report: RetrievalReport | None = None,
) -> tuple[list[Paper], list[Paper], list[ScreeningDecision]]:
    """Screen every paper. Returns (included, borderline, all_decisions).

    Borderline is returned separately rather than folded into either bucket:
    it is the queue a human should actually look at, and collapsing it would
    throw away the honest part of the answer.
    """
    items = [(p.id, _prompt(p, criteria)) for p in papers]
    results = router.batch(Role.SCREENING, items, SCREENING_SCHEMA, stage="screening")

    by_id = {p.id: p for p in papers}
    decisions: list[ScreeningDecision] = []
    included: list[Paper] = []
    borderline: list[Paper] = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []

    for paper in papers:
        res = results.get(paper.id)
        if res is None:
            # The model failed on this item. Treat that as borderline, never
            # as exclusion — an infrastructure failure must not silently
            # shrink the evidence base.
            d = ScreeningDecision(paper.id, "borderline",
                                  "screening failed; retained for human review",
                                  0.0, "none", "none")
        else:
            d = ScreeningDecision(
                paper_id=paper.id,
                decision=str(res.data.get("decision", "borderline")).lower(),
                reason=str(res.data.get("reason", ""))[:500],
                confidence=float(res.data.get("confidence", 0.0) or 0.0),
                model_id=res.model_id,
                lineage=res.lineage,
            )
        if d.decision not in ("include", "exclude", "borderline"):
            d.decision = "borderline"

        decisions.append(d)
        if d.decision == "include":
            included.append(paper)
        elif d.decision == "borderline":
            borderline.append(paper)

        rows.append({
            "run_id": run_id, "paper_id": paper.id, "decision": d.decision,
            "reason": d.reason, "confidence": d.confidence,
            "model_id": d.model_id, "lineage": d.lineage, "ts": now,
        })

    store.insert_many("screening", rows)
    store.insert_many("papers", [{**by_id[p.id].to_row(), "retrieved_at": now}
                                 for p in papers])

    if report is not None:
        report.screened = len(papers)
        report.included = len(included)
        report.borderline = len(borderline)
        report.excluded = len(papers) - len(included) - len(borderline)

    return included, borderline, decisions
