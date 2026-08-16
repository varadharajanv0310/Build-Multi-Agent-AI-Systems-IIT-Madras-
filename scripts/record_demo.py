"""Record a real run so the demo can replay it instead of re-running live.

A live run needs three hosted providers, four databases and 90-150 seconds of
cooperation. On a recording that is three ways to lose the take. So: run it for
real once, keep the exact stage timings and the exact payload, and replay them.

The demo is a REPLAY OF A REAL RUN, not a mock. Nothing here fabricates a
result — it captures one. The UI labels it as a replay and shows the original
run id and date, because a recorded run passed off as a live one is a lie a
judge is entitled to be annoyed about.

    python scripts/record_demo.py seva --paper "C:/path/SEVA_tdsc.pdf"
    python scripts/record_demo.py magnesium --question "How many mg ..."
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from faultline import modes
from faultline.config import PROJECT_ROOT
from faultline.payload import answer_payload, clean, review_payload
from faultline.util import setup_console

DEMO_DIR = PROJECT_ROOT / "demo"


def main() -> int:
    setup_console()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("name", help="demo id, e.g. seva")
    ap.add_argument("--paper", help="path/DOI/arXiv id to review")
    ap.add_argument("--question", help="question to answer")
    ap.add_argument("--papers", type=int, default=25)
    ap.add_argument("--year", type=int, default=2005)
    ap.add_argument("--label", default="", help="human label shown in the UI")
    args = ap.parse_args()

    if bool(args.paper) == bool(args.question):
        ap.error("give exactly one of --paper or --question")

    started = time.time()
    stages: list[dict] = []
    warning = {"text": ""}

    def log(message: str) -> None:
        text = str(message).strip()
        at = round(time.time() - started, 2)
        # Mirror the server's routing exactly, so a replay produces the same
        # stage list and the same banner the live run produced.
        if "unavailable" in text.lower() or "could not search" in text.lower():
            warning["text"] = text
        else:
            stages.append({"label": text, "at": at})
        print(f"  [{at:6.2f}s] {text}", flush=True)

    kwargs = dict(per_query=max(4, args.papers // 4), from_year=args.year,
                  max_papers=args.papers, log=log)

    print(f"recording demo '{args.name}' — this runs for real, be patient\n", flush=True)
    if args.paper:
        res = modes.review_paper(args.paper, **kwargs)
        payload = clean(review_payload(res))
        kind, subject = "review", args.paper
    else:
        res = modes.answer_question(args.question, **kwargs)
        payload = clean(answer_payload(res))
        kind, subject = "answer", args.question

    elapsed = round(time.time() - started, 2)
    if res.error:
        print(f"\nrun errored: {res.error}", flush=True)
        return 1

    record = {
        "name": args.name,
        "kind": kind,
        "label": args.label or Path(subject).name,
        "subject": subject if kind == "answer" else Path(subject).name,
        "recordedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runId": res.run_id,
        "elapsed": elapsed,
        "stages": stages,
        "warning": warning["text"],
        "result": payload,
    }

    DEMO_DIR.mkdir(exist_ok=True)
    out = DEMO_DIR / f"{args.name}.json"
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nrecorded {len(stages)} stages over {elapsed}s -> {out}", flush=True)
    print(f"run id {res.run_id}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
