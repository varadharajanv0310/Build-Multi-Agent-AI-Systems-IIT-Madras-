"""HTTP layer for the Faultline web UI.

Runs are long (30–90s) and stream progress, so the contract is: POST starts a
job and returns immediately with an id; the client polls status for the stage
log; the finished result is served from the same endpoint once ready.

Nothing here contains analysis logic — it adapts faultline.modes to JSON.
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from faultline import modes
from faultline.config import PROJECT_ROOT, ROSTER, lineages_in_play
from faultline.payload import answer_payload, clean, review_payload
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


# --- API ----------------------------------------------------------------------

# A public URL runs on the deployer's API keys, so anyone who finds it can
# spend their quota — and a rate-limited key breaks the demo for the judges it
# was published for. PUBLIC_DEMO serves the recorded runs, which need no keys
# and cannot be exhausted, and turns live submission off.
PUBLIC_DEMO = os.getenv("FAULTLINE_PUBLIC_DEMO", "").strip() in ("1", "true", "yes")

_PUBLIC_MSG = (
    "This public instance serves recorded runs only. Live runs need API keys "
    "and local models — clone the repo and run it yourself to do a real one."
)


def _reject_if_public() -> None:
    if PUBLIC_DEMO:
        raise HTTPException(503, _PUBLIC_MSG)


@app.post("/api/review")
def start_review(req: ReviewRequest):
    _reject_if_public()
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
    _reject_if_public()
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
    _reject_if_public()
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
            "replay": job.get("replay"),
            "result": None,
        }
        result = job["result"]
        kind = job["kind"]
    if result is not None:
        # A replayed run is already the recorded payload; only a live run holds
        # dataclasses that still need mapping.
        payload["result"] = result if isinstance(result, dict) else clean(
            review_payload(result) if kind == "review" else answer_payload(result))
    return JSONResponse(payload)


# --- recorded demos -----------------------------------------------------------
#
# A live run needs three hosted providers and four databases to cooperate for
# 90-150 seconds. During a recording that is three ways to lose the take, so a
# real run is captured once by scripts/record_demo.py and replayed at its
# recorded timings. It is a replay of real output, never a fabricated one, and
# the UI says so — see the REPLAY chip and the recorded run id.

DEMOS = PROJECT_ROOT / "demo"


def _load_demo(name: str) -> dict:
    path = (DEMOS / f"{name}.json").resolve()
    if path.parent != DEMOS.resolve() or not path.is_file():
        raise HTTPException(404, "no such demo")
    return json.loads(path.read_text(encoding="utf-8"))


def _replay(job_id: str, record: dict, speed: float) -> None:
    """Emit the recorded stages on their recorded schedule."""
    try:
        for stage in record["stages"]:
            target = float(stage["at"]) / speed
            with _lock:
                job = _jobs.get(job_id)
                if job is None:
                    return
                delay = target - (time.time() - job["started"])
            if delay > 0:
                time.sleep(delay)
            with _lock:
                job = _jobs.get(job_id)
                if job is None:
                    return
                job["stages"].append({"label": stage["label"],
                                      "at": round(float(stage["at"]))})
                if record.get("warning") and not job["warning"]:
                    # The banner appeared partway through the real run; hold it
                    # until retrieval has actually been reached.
                    if "search" in stage["label"].lower() or len(job["stages"]) >= 4:
                        job["warning"] = record["warning"]
        tail = float(record.get("elapsed", 0)) / speed
        with _lock:
            job = _jobs.get(job_id)
            remaining = tail - (time.time() - job["started"]) if job else 0
        if remaining > 0:
            time.sleep(remaining)
        with _lock:
            if job_id in _jobs:
                _jobs[job_id]["result"] = record["result"]
                _jobs[job_id]["phase"] = "result"
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        with _lock:
            if job_id in _jobs:
                _jobs[job_id]["error"] = f"{type(e).__name__}: {e}"
                _jobs[job_id]["phase"] = "error"


# Recording start gate. The page is loaded and idle before capture begins;
# firing it from here means t=0 is a timestamp we chose, so the narration can
# be aligned to the frame instead of guessed at.
_gate = {"at": 0.0}


@app.post("/api/demo/gate")
def fire_gate():
    _gate["at"] = time.time()
    return {"firedAt": _gate["at"]}


@app.get("/api/demo/gate")
def read_gate():
    return {"firedAt": _gate["at"]}


@app.delete("/api/demo/gate")
def clear_gate():
    _gate["at"] = 0.0
    return {"firedAt": 0.0}


@app.get("/api/demo")
def list_demos():
    if not DEMOS.is_dir():
        return []
    out = []
    for p in sorted(DEMOS.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — a broken file should not hide the rest
            continue
        out.append({"name": d.get("name", p.stem), "kind": d.get("kind", ""),
                    "label": d.get("label", ""), "subject": d.get("subject", ""),
                    "recordedAt": d.get("recordedAt", ""),
                    "elapsed": d.get("elapsed", 0), "runId": d.get("runId", "")})
    return out


@app.post("/api/demo/{name}")
def start_demo(name: str, speed: float = 1.0):
    record = _load_demo(name)
    speed = min(max(speed, 0.25), 20.0)
    job_id = _new_job("review" if record["kind"] == "review" else "answer",
                      record.get("label", ""))
    with _lock:
        # Marks the job as a replay so the page can label it honestly.
        _jobs[job_id]["replay"] = {
            "recordedAt": record.get("recordedAt", ""),
            "runId": record.get("runId", ""),
            "originalElapsed": record.get("elapsed", 0),
        }
    threading.Thread(target=_replay, daemon=True,
                     args=(job_id, record, speed)).start()
    return {"jobId": job_id}


@app.get("/api/status")
def status():
    return {
        "lineages": sorted(l.value for l in lineages_in_play()),
        "roster": {r.value: f"{s.provider}/{s.model_id}" for r, s in ROSTER.items()},
        # The landing page builds its lineage chips from this, so what the page
        # advertises cannot drift from what the engine is configured to run.
        "lineageByRole": {r.value: s.lineage.value for r, s in ROSTER.items()},
        "publicDemo": PUBLIC_DEMO,
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
