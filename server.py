"""HTTP layer for the Faultline web UI.

Runs are long (30–90s) and stream progress, so the contract is: POST starts a
job and returns immediately with an id; the client polls status for the stage
log; the finished result is served from the same endpoint once ready.

Nothing here contains analysis logic — it adapts faultline.modes to JSON.
"""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from faultline import modes
from faultline.config import PROJECT_ROOT, ROSTER, lineages_in_play
from faultline.store.db import Store

WEB = PROJECT_ROOT / "web"
UPLOADS = PROJECT_ROOT / "data" / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Faultline")

# One store for the process. SQLite with check_same_thread=False, and jobs run
# on worker threads.
_store = Store()
_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


class ReviewRequest(BaseModel):
    source: str = ""
    papers: int = 25
    year: int = 2005


class AskRequest(BaseModel):
    question: str
    papers: int = 25
    year: int = 2005


def _new_job(kind: str, title: str = "") -> str:
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {
            "id": job_id, "kind": kind, "phase": "running", "title": title,
            "stages": [], "warning": "", "started": time.time(),
            "result": None, "error": "",
        }
    return job_id


def _log(job_id: str):
    def emit(message: str) -> None:
        with _lock:
            job = _jobs.get(job_id)
            if not job:
                return
            text = str(message).strip()
            # Retrieval degradation is surfaced as a banner, not another log
            # line — the run continues and the user should see that it did.
            if "unavailable" in text.lower() or "could not search" in text.lower():
                job["warning"] = text
                return
            job["stages"].append({
                "label": text,
                "at": round(time.time() - job["started"]),
            })
    return emit


def _run(job_id: str, fn, *args, **kwargs) -> None:
    try:
        result = fn(*args, log=_log(job_id), store=_store, **kwargs)
        with _lock:
            _jobs[job_id]["result"] = result
            _jobs[job_id]["phase"] = "result"
    except Exception as e:  # noqa: BLE001 — surface, never swallow
        traceback.print_exc()
        with _lock:
            _jobs[job_id]["error"] = f"{type(e).__name__}: {e}"
            _jobs[job_id]["phase"] = "error"


# --- serialisation ------------------------------------------------------------

def _clean(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _clean(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _review_payload(res) -> dict[str, Any]:
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


def _answer_payload(res) -> dict[str, Any]:
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


# --- API ----------------------------------------------------------------------

@app.post("/api/review")
def start_review(req: ReviewRequest):
    if not req.source.strip():
        raise HTTPException(400, "no paper supplied")
    job_id = _new_job("review")
    threading.Thread(
        target=_run, daemon=True,
        args=(job_id, modes.review_paper, req.source.strip()),
        kwargs={"per_query": max(4, req.papers // 4), "from_year": req.year,
                "max_papers": req.papers},
    ).start()
    return {"jobId": job_id}


@app.post("/api/review/upload")
async def start_review_upload(file: UploadFile, papers: int = 25, year: int = 2005):
    suffix = Path(file.filename or "paper.txt").suffix or ".txt"
    dest = UPLOADS / f"{uuid.uuid4().hex[:10]}{suffix}"
    dest.write_bytes(await file.read())
    job_id = _new_job("review", file.filename or "")
    threading.Thread(
        target=_run, daemon=True,
        args=(job_id, modes.review_paper, str(dest)),
        kwargs={"per_query": max(4, papers // 4), "from_year": year,
                "max_papers": papers},
    ).start()
    return {"jobId": job_id}


@app.post("/api/ask")
def start_ask(req: AskRequest):
    if not req.question.strip():
        raise HTTPException(400, "no question supplied")
    job_id = _new_job("answer", req.question.strip())
    threading.Thread(
        target=_run, daemon=True,
        args=(job_id, modes.answer_question, req.question.strip()),
        kwargs={"per_query": max(4, req.papers // 4), "from_year": req.year,
                "max_papers": req.papers},
    ).start()
    return {"jobId": job_id}


@app.get("/api/job/{job_id}")
def job_status(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "unknown job")
        payload = {
            "id": job["id"], "kind": job["kind"], "phase": job["phase"],
            "title": job["title"], "stages": list(job["stages"]),
            "warning": job["warning"], "error": job["error"],
            "elapsed": round(time.time() - job["started"]),
            "result": None,
        }
        result = job["result"]
    if result is not None:
        payload["result"] = _clean(
            _review_payload(result) if job["kind"] == "review"
            else _answer_payload(result))
    return JSONResponse(payload)


@app.get("/api/status")
def status():
    return {
        "lineages": sorted(l.value for l in lineages_in_play()),
        "roster": {r.value: f"{s.provider}/{s.model_id}" for r, s in ROSTER.items()},
        # The landing page builds its lineage chips from this, so what the page
        # advertises cannot drift from what the engine is configured to run.
        "lineageByRole": {r.value: s.lineage.value for r, s in ROSTER.items()},
    }


@app.get("/api/history")
def history(limit: int = 30):
    rows = _store.query(
        "SELECT id, mode, question, paper_ref, field, started_at FROM runs "
        "WHERE finished_at IS NOT NULL ORDER BY started_at DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


# --- static -------------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(WEB / "landing.html")


@app.get("/ask")
def ask_page():
    return FileResponse(WEB / "ask.html")


@app.get("/review")
def review_page():
    return FileResponse(WEB / "review.html")


# Mounted last: the named routes above win, everything else is served as a file.
app.mount("/", StaticFiles(directory=WEB), name="web")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
