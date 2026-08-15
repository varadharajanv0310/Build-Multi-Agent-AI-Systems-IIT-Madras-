"""Faultline — main entry point.

    python scripts/run_faultline.py
    python scripts/run_faultline.py "Does X improve Y in Z?"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from faultline.util import setup_console, clip

setup_console()

from faultline import pipeline
from faultline.config import ROSTER
from faultline.graph import build_graph
from faultline.instrumentation import Ledger
from faultline.retrieval.models import RetrievalReport
from faultline.router import Router
from faultline.store.db import Store

DEFAULT_Q = "Does vitamin D supplementation prevent acute respiratory tract infections?"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?", default=DEFAULT_Q)
    ap.add_argument("--per-query", type=int, default=8)
    ap.add_argument("--from-year", type=int, default=2000)
    ap.add_argument("--max-conflicts", type=int, default=5)
    ap.add_argument("--engine", choices=["langgraph", "linear"], default="langgraph")
    args = ap.parse_args()

    store = Store()
    print(f"\nQ: {args.question}")
    print(f"engine: {args.engine}\n")

    if args.engine == "linear":
        res = pipeline.run(args.question, per_query=args.per_query,
                           from_year=args.from_year,
                           max_conflicts=args.max_conflicts, store=store)
    else:
        ledger = Ledger()
        run_id = store.start_run(
            mode="question", question=args.question,
            config={r.value: f"{sp.provider}/{sp.model_id}" for r, sp in ROSTER.items()})
        router = Router(store, run_id, ledger)
        final = build_graph().invoke({
            "question": args.question, "router": router, "store": store,
            "run_id": run_id, "per_query": args.per_query,
            "from_year": args.from_year, "max_extract": 8, "max_pairs": 24,
            "max_conflicts": args.max_conflicts, "log": [],
        }, {"recursion_limit": 40})
        res = pipeline.Result(
            run_id=run_id, question=args.question, ledger=ledger,
            calibration=final.get("calibration", {}), spec=final.get("spec", {}),
            report=final.get("report") or RetrievalReport(),
            included=final.get("included", []), borderline=final.get("borderline", []),
            claims=final.get("claims", []), conflicts=final.get("conflicts", []),
            verdicts=final.get("verdicts", []), gaps=final.get("gaps", []))
        store.finish_run(run_id, ledger.summary(),
                         field=final.get("calibration", {}).get("field"))
        router.close()

    print("\n" + "=" * 72)
    print("DISAGREEMENT MAP")
    print("=" * 72)

    if not res.verdicts:
        print("\n  No commensurable contradictions found in this corpus.")
        print("  That is a finding, not a failure — it means the retrieved")
        print("  studies did not disagree in a way that survives the")
        print("  commensurability contract.")

    for i, v in enumerate(res.verdicts, 1):
        pair = v["conflict"]["pair"]
        print(f"\n[{i}] {v['conflict']['kind'].upper()}  ->  "
              f"{v['verdict'].upper()}  (confidence {v['confidence']:.2f})")
        print(f"    A: {clip(pair.a['text'], 88)}")
        print(f"       {clip(pair.a['population'], 60)} | {pair.a['direction']} | "
              f"{clip(pair.a['magnitude'], 40)}")
        print(f"    B: {clip(pair.b['text'], 88)}")
        print(f"       {clip(pair.b['population'], 60)} | {pair.b['direction']} | "
              f"{clip(pair.b['magnitude'], 40)}")

        if pair.lineage_agreement is False:
            print("    ! assessors from different lineages DISAGREED on comparability")

        for e in v.get("explanations", []):
            cited = e.get("cited_attributes_json") or []
            mark = "+" if e.get("applies") else "-"
            print(f"    {mark} {e['stance']:<14} [{e['lineage']:<9}] "
                  f"p={e['confidence']:.2f}  {clip(e['argument'], 70)}")
            if not cited:
                print("        (cites no concrete attribute)")

        if v.get("winning_stance"):
            print(f"    => {v['winning_stance']}")
        print(f"    => {clip(v['reasoning'], 150)}")

    if res.gaps:
        print("\n" + "=" * 72)
        print("RESEARCH GAPS  (unresolved disagreements)")
        print("=" * 72)
        for g in res.gaps:
            print(f"\n  [{g['bucket']}/{g['status']}]")
            print(f"  {clip(g['proposition'], 300)}")

    print(res.report.render())
    if res.ledger:
        print(res.ledger.render())
    print(f"run {res.run_id}  —  trace: "
          f"SELECT * FROM events WHERE run_id='{res.run_id}'")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
