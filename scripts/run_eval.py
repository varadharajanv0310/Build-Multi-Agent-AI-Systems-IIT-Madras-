"""Part 5 — evaluate Faultline against published systematic reviews.

    python scripts/run_eval.py --limit 2
    python scripts/run_eval.py --field economics
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from faultline.util import setup_console

setup_console()

from faultline import pipeline
from faultline.config import ROSTER
from faultline.eval.benchmark import CASES
from faultline.eval.harness import EvalResult, evaluate, find_review, render_table, to_json
from faultline.instrumentation import Ledger
from faultline.router import Router
from faultline.store.db import Store


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=len(CASES))
    ap.add_argument("--field", default=None)
    ap.add_argument("--per-query", type=int, default=10)
    ap.add_argument("--max-conflicts", type=int, default=5)
    ap.add_argument("--out", default="evaluation/results.json")
    args = ap.parse_args()

    cases = CASES
    if args.field:
        cases = [c for c in cases if args.field.lower() in c.field.lower()]
    cases = cases[:args.limit]

    store = Store()
    results: list[EvalResult] = []
    started = time.time()

    for i, case in enumerate(cases, 1):
        print(f"\n{'=' * 78}\n[{i}/{len(cases)}] {case.field}: {case.question}\n{'=' * 78}")

        print("  locating ground-truth review...")
        review = find_review(case)
        if review:
            print(f"    {review.year}  {review.title[:66]}")
            print(f"    cited {review.cited_by}x, {len(review.referenced_works)} references")
        else:
            print("    none found - retrieval recall will be unavailable for this case")

        try:
            res = pipeline.run(case.question, per_query=args.per_query,
                               max_conflicts=args.max_conflicts, store=store,
                               log=lambda m: print(f"  {m}"))
        except Exception as e:  # noqa: BLE001 - one bad case must not sink the suite
            ev = EvalResult(case=case, review=review, error=f"{type(e).__name__}: {e}")
            results.append(ev)
            print(f"  ERROR {ev.error}")
            continue

        ledger = res.ledger or Ledger()
        run_id = res.run_id
        router = Router(store, run_id, ledger)
        ev = evaluate(case, router, res, review)
        router.close()
        results.append(ev)

        recall = ("n/a" if ev.retrieval_recall is None else f"{ev.retrieval_recall:.1%}")
        print(f"  -> recall {recall}, conflicts {ev.conflicts_found} "
              f"(unresolved {ev.unresolved}), moderator match {ev.moderator_match}")

    print(render_table(results))

    # Aggregate — the headline numbers for the writeup.
    scored = [r for r in results if not r.error]
    recalls = [r.retrieval_recall for r in scored if r.retrieval_recall is not None]
    fcrs = [r.false_conflict_rate for r in scored if r.false_conflict_rate is not None]
    matches = [r.moderator_match for r in scored if r.moderator_match is not None]
    print("AGGREGATE")
    print(f"  cases                    {len(scored)}/{len(results)} completed")
    print(f"  fields                   {len({r.case.field for r in scored})}")
    if recalls:
        print(f"  mean retrieval recall    {sum(recalls) / len(recalls):.1%}  "
              f"(lower bound: review reference lists include background citations)")
    if fcrs:
        print(f"  mean false-conflict rate {sum(fcrs) / len(fcrs):.1%}")
    if matches:
        print(f"  moderator agreement      {sum(matches)}/{len(matches)}")
    print(f"  total conflicts          {sum(r.conflicts_found for r in scored)}")
    print(f"  total unresolved (gaps)  {sum(r.unresolved for r in scored)}")
    print(f"  hosted calls             {sum(r.hosted_calls for r in scored)}")
    print(f"  USD spent                $0.00 (free tiers + local; DeepSeek/Llama4 ~$0.01/run)")
    print(f"  wall clock               {(time.time() - started) / 60:.1f} min")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_json(results), encoding="utf-8")
    print(f"\nwrote {out}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
