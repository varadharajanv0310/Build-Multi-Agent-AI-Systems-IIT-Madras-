"""Dataclasses → the JSON shape the web pages render.

Kept out of server.py so the demo recorder can produce byte-identical payloads
without starting a web app. If this drifts from what the pages expect, both the
live run and the recorded demo drift together — which is the point.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any


def clean(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {k: clean(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def review_payload(res) -> dict[str, Any]:
    rv = res.review
    groups: list[dict[str, Any]] = []
    for name, label in (("R1 — framing", "Framing"),
                        ("R2 — method", "Method"),
                        ("R3 — significance", "Significance")):
        items = [o for o in rv.objections if o.reviewer == name]
        if not items:
            continue
        groups.append({
            "name": label,
            "lineage": items[0].lineage,
            "objections": [{"severity": o.severity.upper(),
                            "text": o.objection,
                            "fix": o.minimum_fix} for o in items],
        })

    pos = rv.positioning or {}
    ap = rv.appraisal or {}
    ledger = res.ledger.summary() if res.ledger else {}
    words = len((res.paper.fulltext or res.paper.abstract or "").split()) if res.paper else 0

    return {
        "kind": "review",
        "paper": {
            "title": rv.paper_title,
            "meta": f"READ FROM YOUR DOCUMENT · {words:,} WORDS" if words else "",
        },
        "counts": [
            {"n": len(rv.claims), "label": "YOUR CLAIMS FOUND", "accent": False},
            {"n": len(rv.literature), "label": "LITERATURE FINDINGS", "accent": False},
            {"n": len(rv.fatal), "label": "FATAL OBJECTIONS", "accent": bool(rv.fatal)},
            {"n": len(rv.major), "label": "MAJOR OBJECTIONS", "accent": False},
        ],
        "fatalAlert": rv.fatal[0].objection if rv.fatal else "",
        "novelty": {
            "verdict": str(pos.get("novelty_risk", "unclear")).replace("_", " ").upper(),
            "placement": pos.get("placement", ""),
            "draftSentence": pos.get("novelty_claim", ""),
            "dismissalRisk": pos.get("collapse_risk", ""),
            "mustCite": [{"title": str(m), "why": ""} for m in (pos.get("must_cite") or [])],
        },
        "panel": groups,
        "base": {
            "quality": str(ap.get("evidence_base", "unknown")).upper(),
            "assessment": ap.get("assessment", ""),
            "systemic": [{"text": str(s)} for s in (ap.get("systemic_issues") or [])],
            "construct": ap.get("construct_validity", ""),
        },
        "claims": [{
            "n": f"{i:02d}",
            "text": c.get("text", ""),
            "direction": c.get("direction", ""),
            "population": c.get("population", ""),
            "scope": ", ".join(c.get("scope_conditions_json") or [])
                     if isinstance(c.get("scope_conditions_json"), list)
                     else str(c.get("scope_conditions_json") or ""),
        } for i, c in enumerate(rv.claims, 1)],
        "run": {
            "modelCalls": ledger.get("total_calls", 0),
            "localShare": ledger.get("local_share", 0),
            "cost": "$0.00",
        },
        "degraded": res.degraded,
        "error": res.error,
        "runId": res.run_id,
    }


def answer_payload(res) -> dict[str, Any]:
    a = res.answer
    ledger = res.ledger.summary() if res.ledger else {}
    r = res.report
    return {
        "kind": "answer",
        "question": a.question if a else "",
        "headline": a.headline if a else "",
        "answer": a.answer if a else "",
        "confidence": (a.confidence if a else "insufficient_evidence").replace("_", " "),
        "consensus": (a.consensus if a else "no_consensus").replace("_", " "),
        "caveats": a.caveats if a else [],
        "disagreements": a.disagreements if a else [],
        "whatWouldSettleIt": a.what_would_settle_it if a else [],
        "evidence": [{
            "text": c.get("text", ""),
            "direction": c.get("direction", ""),
            "magnitude": c.get("magnitude", ""),
            "population": c.get("population", ""),
            "outcome": c.get("outcome_measure", ""),
            "source": c.get("source_title") or c.get("paper_title") or "",
        } for c in (a.evidence if a else [])],
        "corpus": {
            "databases": r.databases,
            "raw": r.raw_hits, "unique": r.after_dedup, "screened": r.screened,
            "included": r.included, "borderline": r.borderline, "excluded": r.excluded,
            "field": res.calibration.get("field", ""),
        },
        "run": {
            "modelCalls": ledger.get("total_calls", 0),
            "localShare": ledger.get("local_share", 0),
            "cost": "$0.00",
        },
        "error": res.error,
        "runId": res.run_id,
    }
