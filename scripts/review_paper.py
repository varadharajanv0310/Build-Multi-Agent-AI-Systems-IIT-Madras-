"""Review a paper against its own literature.

    python scripts/review_paper.py 10.1136/bmj.i6583          # a DOI
    python scripts/review_paper.py 2301.00001                 # an arXiv id
    python scripts/review_paper.py mydraft.txt                # a local file
    python scripts/review_paper.py mypaper.pdf                # a PDF
    python scripts/review_paper.py "paste your abstract here..."
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from faultline.util import setup_console, clip

setup_console()

from faultline import pipeline
from faultline.store.db import Store

_MARK = {"corroborated": "SUPPORTED", "contradicted": "CONTRADICTED",
         "mixed": "MIXED", "isolated": "STANDS ALONE",
         "unverifiable": "UNVERIFIABLE"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="DOI, arXiv id, file path, or pasted text")
    ap.add_argument("--claims", type=int, default=3, help="claims to check")
    ap.add_argument("--per-query", type=int, default=10)
    args = ap.parse_args()

    store = Store()
    try:
        res = pipeline.run_paper(args.source, max_claims=args.claims,
                                 per_query=args.per_query, store=store)
    except Exception as e:
        print(f"\nCould not load that paper: {e}")
        store.close()
        return 1

    print("\n" + "=" * 74)
    print(f"PAPER REVIEW  —  {clip(res.paper.title, 56)}")
    print("=" * 74)

    if not res.positions:
        print("\n  No empirical claims were found to check. If you passed a")
        print("  title or a DOI, try the full abstract or a text file instead —")
        print("  there may not have been enough text to extract findings from.")

    for i, p in enumerate(res.positions, 1):
        print(f"\n[{i}] {_MARK.get(p.position, p.position.upper())}")
        print(f"    claim:    {clip(p.claim.get('text'), 84)}")
        print(f"    question: {clip(p.question, 84)}")
        print(f"    literature: {p.supporting} supporting, {p.conflicting} conflicting "
              f"({len(p.comparable_claims)} comparable findings found)")
        print(f"    {clip(p.assessment, 220)}")
        if p.strength_warning:
            print(f"    ! OVERSTATEMENT RISK: {clip(p.strength_warning, 200)}")

    if res.contradicted or res.isolated or res.warnings:
        print("\n" + "-" * 74)
        print("WHAT A REVIEWER WOULD PUSH ON")
        print("-" * 74)
        for p in res.contradicted:
            print(f"  contradicted   {clip(p.claim.get('text'), 60)}")
        for p in res.isolated:
            print(f"  unreplicated   {clip(p.claim.get('text'), 60)}")
        for p in res.warnings:
            print(f"  overstated     {clip(p.strength_warning, 60)}")

    if res.ledger:
        print(res.ledger.render())
    print(f"run {res.run_id}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
