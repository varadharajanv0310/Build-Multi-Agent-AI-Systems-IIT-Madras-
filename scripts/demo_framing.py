"""Part 3 acceptance test: calibrate -> frame -> retrieve -> screen -> extract.

The question this answers: do the Framer's generated queries actually pull
primary studies, where the raw question pulled only reviews?

    python scripts/demo_framing.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from faultline.util import setup_console

setup_console()

from faultline.agents.extraction import extract_claims, usable_for_conflict
from faultline.agents.framing import (
    calibrate_field, contract_text, criteria_text, frame_question)
from faultline.config import ROSTER
from faultline.instrumentation import Ledger
from faultline.retrieval.models import RetrievalReport
from faultline.retrieval.openalex import OpenAlexClient, dedupe
from faultline.router import Router
from faultline.screening import screen_corpus
from faultline.store.db import Store

DEFAULT_Q = "Does vitamin D supplementation prevent acute respiratory tract infections?"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?", default=DEFAULT_Q)
    ap.add_argument("--per-query", type=int, default=8)
    ap.add_argument("--from-year", type=int, default=2005)
    args = ap.parse_args()

    store = Store()
    ledger = Ledger()
    run_id = store.start_run(
        mode="question", question=args.question,
        config={r.value: f"{s.provider}/{s.model_id}" for r, s in ROSTER.items()})
    router = Router(store, run_id, ledger)

    print(f"run {run_id}\nQ: {args.question}\n")

    # 1. Field calibration ----------------------------------------------------
    print("1. FIELD CALIBRATION")
    cal = calibrate_field(router, args.question)
    print(f"   field: {cal.get('field')}")
    print(f"   appraisal: {cal.get('appraisal_framework')}")
    print(f"   primary designs: {', '.join(cal.get('primary_study_designs', [])[:5])}")
    print(f"   terminology variants: {', '.join(cal.get('terminology_variants', [])[:6])}")
    print(f"   controversies: {'; '.join(cal.get('live_controversies', [])[:2])}")

    # 2. Framing --------------------------------------------------------------
    print("\n2. QUESTION FRAMING")
    spec = frame_question(router, args.question, cal)
    print(f"   population:   {spec.get('population')}")
    print(f"   intervention: {spec.get('intervention')}")
    print(f"   outcome:      {spec.get('outcome')}")
    print("\n" + contract_text(spec))
    print("\n   search queries:")
    for q in spec.get("search_queries", []):
        print(f"     - {q}")

    # 3. Retrieval using the GENERATED queries --------------------------------
    print("\n3. RETRIEVAL (generated queries, targeting primary studies)")
    client = OpenAlexClient()
    report = RetrievalReport(query_strings=spec.get("search_queries", []),
                             databases=["openalex"])
    papers = []
    for q in report.query_strings[:6]:
        try:
            hits = list(client.search(q, limit=args.per_query, from_year=args.from_year))
            papers.extend(hits)
            print(f"   {len(hits):>3} <- {q[:64]}")
        except Exception as e:
            print(f"   ERR <- {q[:50]}: {type(e).__name__}")
    report.raw_hits = len(papers)
    papers = dedupe(papers)
    report.after_dedup = len(papers)
    client.close()
    print(f"   {report.raw_hits} raw -> {len(papers)} after dedup")

    # 4. Screening ------------------------------------------------------------
    print("\n4. SCREENING (local, unmetered)")
    included, borderline, _ = screen_corpus(
        router, store, run_id, papers, criteria_text(spec), report)
    print(f"   included {len(included)} | borderline {len(borderline)} "
          f"| excluded {report.excluded}")
    for p in included[:6]:
        print(f"     [{p.year}] {p.title[:66]}")

    # 5. Extraction -----------------------------------------------------------
    targets = (included + borderline)[:6]
    print(f"\n5. CLAIM EXTRACTION ({len(targets)} papers)")
    claims = extract_claims(router, store, run_id, targets, args.question)
    usable = [c for c in claims if usable_for_conflict(c)]
    print(f"   {len(claims)} claims extracted, {len(usable)} usable for conflict analysis")
    for c in usable[:5]:
        print(f"\n   \"{c['text'][:110]}\"")
        print(f"     direction={c['direction']}  magnitude={c['magnitude']}")
        print(f"     population={str(c['population'])[:70]}")
        print(f"     outcome={str(c['outcome_measure'])[:60]}  timepoint={c['timepoint']}")
        print(f"     scope={c['scope_conditions_json']}")
        print(f"     hedges={c['hedges_json']}  tag={c['confidence_tag']}")

    print(report.render())
    store.finish_run(run_id, ledger.summary(), field=cal.get("field"))
    print(ledger.render())
    router.close()
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
