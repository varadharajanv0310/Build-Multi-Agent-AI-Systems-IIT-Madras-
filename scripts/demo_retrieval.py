"""Part 2 acceptance test: question in, screened corpus with a denominator out.

    python scripts/demo_retrieval.py
    python scripts/demo_retrieval.py --limit 40 "your question here"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from faultline.util import setup_console

setup_console()

from faultline.config import ROSTER
from faultline.instrumentation import Ledger
from faultline.retrieval.models import RetrievalReport
from faultline.retrieval.openalex import OpenAlexClient, dedupe
from faultline.router import Router
from faultline.screening import screen_corpus
from faultline.store.db import Store

DEFAULT_QUESTION = "Does vitamin D supplementation prevent acute respiratory tract infections?"
DEFAULT_CRITERIA = """Include a paper if it reports PRIMARY empirical results on the effect of
vitamin D supplementation on acute respiratory tract infection incidence or
severity in humans.

Exclude if it is: about a different intervention or outcome; a narrative
commentary or editorial with no data; animal or in-vitro only.

Systematic reviews and meta-analyses on exactly this question count as
"borderline" - they are useful context but are not primary studies."""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    ap.add_argument("--limit", type=int, default=20, help="papers to retrieve")
    ap.add_argument("--from-year", type=int, default=2010)
    args = ap.parse_args()

    store = Store()
    ledger = Ledger()
    run_id = store.start_run(
        mode="question", question=args.question,
        config={r.value: f"{s.provider}/{s.model_id}" for r, s in ROSTER.items()})
    router = Router(store, run_id, ledger)
    report = RetrievalReport(query_strings=[args.question], databases=["openalex"])

    print(f"run {run_id}")
    print(f"Q: {args.question}\n")

    client = OpenAlexClient()

    # The denominator: how large is the pool we are sampling from?
    report.raw_hits = client.count(args.question, from_year=args.from_year)
    print(f"OpenAlex matches: {report.raw_hits:,}  (retrieving {args.limit})")

    papers = list(client.search(args.question, limit=args.limit, from_year=args.from_year))
    papers = dedupe(papers)
    report.after_dedup = len(papers)
    report.abstract_only = sum(1 for p in papers if p.abstract and not p.fulltext)
    report.no_text = sum(1 for p in papers if not p.has_text)
    client.close()
    print(f"after dedup: {len(papers)}\n")

    print("screening (local, unmetered)...")
    included, borderline, decisions = screen_corpus(
        router, store, run_id, papers, DEFAULT_CRITERIA, report)

    print(f"\nINCLUDED ({len(included)})")
    for p in included[:8]:
        print(f"  {p.year}  {p.title[:72]}")

    if borderline:
        print(f"\nBORDERLINE ({len(borderline)}) - the queue a human should read")
        for p in borderline[:5]:
            d = next(x for x in decisions if x.paper_id == p.id)
            print(f"  {p.year}  {p.title[:60]}")
            print(f"        why: {d.reason[:100]}")

    excluded = [d for d in decisions if d.decision == "exclude"]
    if excluded:
        print(f"\nEXCLUDED ({len(excluded)}) - reasons are kept and defensible")
        for d in excluded[:4]:
            print(f"  {d.reason[:100]}")

    print(report.render())
    store.finish_run(run_id, ledger.summary())
    print(ledger.render())

    router.close()
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
