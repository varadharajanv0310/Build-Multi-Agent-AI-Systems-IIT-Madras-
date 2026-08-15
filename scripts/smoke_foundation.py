"""Part 1 acceptance test.

Exercises the whole foundation end to end: store, router, cache, ledger,
cross-lineage opposed judgement, and the trace.

    python scripts/smoke_foundation.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from faultline.config import ROSTER, Role, lineages_in_play
from faultline.instrumentation import Ledger
from faultline.router import Router
from faultline.store.db import Store

SCHEMA = {
    "type": "object",
    "properties": {
        "comparable": {"type": "boolean"},
        "reason_code": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["comparable", "reason_code", "confidence"],
}

PAIR = (
    "Claim A: 'Drug D reduced 30-day mortality in ICU sepsis patients (n=812, RCT).'\n"
    "Claim B: 'Drug D showed no effect on 1-year all-cause mortality in outpatients "
    "(n=4,100, cohort).'\n\n"
    "Are these two claims measuring the same thing?"
)


def msgs(stance: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content":
            f"You assess whether two research claims are commensurable. {stance} "
            "Argue your assigned side honestly; do not hedge toward the middle."},
        {"role": "user", "content": PAIR},
    ]


def main() -> int:
    store = Store()
    ledger = Ledger()
    run_id = store.start_run(
        mode="question",
        question="[smoke] commensurability across lineages",
        config={r.value: f"{s.provider}/{s.model_id}" for r, s in ROSTER.items()})
    router = Router(store, run_id, ledger)
    failed = []

    print(f"run {run_id}\n")

    # 1. Single call through a role ------------------------------------------
    print("1. adjudication role, cold call")
    try:
        r1 = router.complete(Role.ADJUDICATION, msgs("Be strict."), SCHEMA,
                             stage="smoke", subject_id="pair_1")
        print(f"   {r1.model_id} [{r1.lineage}] {r1.latency_ms}ms  {r1.data}")
    except Exception as e:
        print(f"   FAIL {type(e).__name__}: {e}")
        failed.append("cold call")

    # 2. Same call again — must be served from cache --------------------------
    print("\n2. identical call, must hit cache")
    try:
        r2 = router.complete(Role.ADJUDICATION, msgs("Be strict."), SCHEMA,
                             stage="smoke", subject_id="pair_1")
        print(f"   from_cache={r2.from_cache}  "
              f"{'OK' if r2.from_cache else 'FAIL - cache miss'}")
        if not r2.from_cache:
            failed.append("cache")
    except Exception as e:
        print(f"   FAIL {type(e).__name__}: {e}")
        failed.append("cache")

    # 3. Opposed judgement across two lineages --------------------------------
    print("\n3. opposed judgement (two lineages, disagreement preserved)")
    try:
        a, b, agreed = router.opposed(
            Role.COMMENSURABILITY_A, Role.COMMENSURABILITY_B,
            msgs("Argue they ARE comparable."),
            msgs("Argue they are NOT comparable."),
            SCHEMA, agree_on="comparable", stage="smoke", subject_id="pair_1")
        for side, res in (("A", a), ("B", b)):
            print(f"   {side}: {res.lineage:<9} {res.data}" if res
                  else f"   {side}: unavailable")
        print(f"   -> {'AGREE' if agreed else 'DIVERGE'} "
              "(divergence is signal, not error)")
        if a is None and b is None:
            failed.append("opposed")
    except Exception as e:
        print(f"   FAIL {type(e).__name__}: {e}")
        failed.append("opposed")

    # 4. Batch through a local role -------------------------------------------
    print("\n4. batched local screening (one model resident)")
    try:
        items = [(f"item_{i}", msgs(f"Case {i}.")) for i in range(3)]
        out = router.batch(Role.SCREENING, items, SCHEMA, stage="smoke")
        print(f"   {len(out)}/3 returned typed records")
        if len(out) < 2:
            failed.append("batch")
    except Exception as e:
        print(f"   FAIL {type(e).__name__}: {e}")
        failed.append("batch")

    # 5. Trace and ledger ------------------------------------------------------
    trace = store.trace(run_id)
    print(f"\n5. trace: {len(trace)} events")
    kinds: dict[str, int] = {}
    for row in trace:
        kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
    print(f"   {kinds}")
    if not trace:
        failed.append("trace")

    store.finish_run(run_id, ledger.summary())
    print(ledger.render())
    print(f"lineages available: {sorted(l.value for l in lineages_in_play())}")

    router.close()
    store.close()

    if failed:
        print(f"\nFAILED: {', '.join(failed)}")
        return 1
    print("\nPart 1 foundation OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
