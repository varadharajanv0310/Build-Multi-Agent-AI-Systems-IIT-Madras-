"""Does the adjudicator's veto actually fire?

The veto is the most important behaviour in the system: an unresolved conflict
is what produces a research gap, and a system that ALWAYS finds an explanation
has learned to rationalise — the exact failure this project exists to avoid.

Corpus runs cannot prove it, because a corpus whose conflicts happen to be
explicable is indistinguishable from an adjudicator that cannot say no. So
this tests the behaviour directly with three constructed cases:

  A. Explicable    - studies differ on a concrete, stated moderator.
                     Correct verdict: explained.
  B. Unexplainable - studies match on every stated dimension and still
                     disagree, and the panel cites nothing concrete.
                     Correct verdict: unresolved.
  C. Not a conflict - different endpoints entirely.
                     Correct verdict: not_a_conflict.

Case B is the one that matters. If it comes back "explained", the adjudicator
is rationalising and the prompt is wrong.

    python scripts/test_veto.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from faultline.util import setup_console, clip

setup_console()

from faultline.agents.council import ClaimPair, adjudicate
from faultline.config import ROSTER
from faultline.instrumentation import Ledger
from faultline.router import Router
from faultline.store.db import Store, new_id


def claim(**kw):
    base = {
        "id": new_id("clm"), "paper_id": new_id("pap"), "text": "",
        "direction": "positive", "magnitude": "not reported",
        "uncertainty": "not reported", "population": "", "sample_size": "",
        "design": "randomised controlled trial", "outcome_measure": "",
        "timepoint": "", "scope_conditions_json": [], "hedges_json": [],
    }
    return {**base, **kw}


# --- A. genuinely explicable -------------------------------------------------
A1 = claim(
    text="Drug X reduced 30-day mortality.", direction="positive",
    magnitude="RR 0.62 (95% CI 0.44-0.87)",
    population="ICU patients with septic shock, baseline lactate > 4 mmol/L",
    sample_size="812", outcome_measure="all-cause mortality", timepoint="30 days",
    scope_conditions_json=["high-dose 6 mg/kg", "administered within 6 hours of onset"])
A2 = claim(
    text="Drug X showed no effect on 30-day mortality.", direction="null",
    magnitude="RR 0.98 (95% CI 0.86-1.12)",
    population="ward patients with uncomplicated sepsis, normal lactate",
    sample_size="1,940", outcome_measure="all-cause mortality", timepoint="30 days",
    scope_conditions_json=["low-dose 1 mg/kg", "administered up to 48 hours after onset"])

# --- B. no available explanation ---------------------------------------------
# Same population, same dose, same endpoint, same timing, same design, similar
# size. Nothing in the recorded characteristics can account for the split.
B1 = claim(
    text="Drug Y reduced 12-month relapse rate.", direction="positive",
    magnitude="HR 0.68 (95% CI 0.51-0.91)",
    population="adults 40-65 with moderate rheumatoid arthritis, methotrexate-naive",
    sample_size="1,204", outcome_measure="12-month relapse rate", timepoint="12 months",
    scope_conditions_json=["10 mg daily oral", "multicentre, double-blind"])
B2 = claim(
    text="Drug Y did not reduce 12-month relapse rate.", direction="null",
    magnitude="HR 0.97 (95% CI 0.79-1.19)",
    population="adults 40-65 with moderate rheumatoid arthritis, methotrexate-naive",
    sample_size="1,187", outcome_measure="12-month relapse rate", timepoint="12 months",
    scope_conditions_json=["10 mg daily oral", "multicentre, double-blind"])

# --- C. not a conflict --------------------------------------------------------
C1 = claim(
    text="Drug Z lowered systolic blood pressure.", direction="positive",
    magnitude="-8.2 mmHg (95% CI -11.0 to -5.4)", population="adults with stage 1 hypertension",
    outcome_measure="systolic blood pressure", timepoint="8 weeks")
C2 = claim(
    text="Drug Z did not change patient-reported fatigue.", direction="null",
    magnitude="0.3 points (95% CI -0.8 to 1.4)", population="adults with stage 1 hypertension",
    outcome_measure="patient-reported fatigue score", timepoint="8 weeks")


def explanations(run_id, conflict_id, cited: bool, lineages=("nemotron", "deepseek", "llama4")):
    """Panel output. `cited=False` means every stance is a bare assertion with
    no concrete study attribute behind it — which the adjudicator is told to
    treat as a post-hoc rationalisation."""
    stances = ["population", "dose_exposure", "measurement"]
    out = []
    for stance, lin in zip(stances, lineages):
        out.append({
            "id": new_id("exp"), "run_id": run_id, "conflict_id": conflict_id,
            "stance": stance, "lineage": lin, "model_id": f"test/{lin}",
            "confidence": 0.8, "applies": True,
            "argument": (f"The studies differ in {stance.replace('_', ' ')}."
                         if not cited else
                         f"The studies differ materially in {stance.replace('_', ' ')}, "
                         "as recorded in their stated characteristics."),
            "cited_attributes_json": [] if not cited else
                ["differing dose", "differing baseline severity"],
        })
    return out


CASES = [
    ("A  explicable moderator", A1, A2, True, "explained"),
    ("B  NO available explanation", B1, B2, False, "unresolved"),
    ("C  different endpoints", C1, C2, False, "not_a_conflict"),
]


def main() -> int:
    store = Store()
    ledger = Ledger()
    run_id = store.start_run(
        mode="question", question="[veto test] can the adjudicator refuse?",
        config={r.value: f"{s.provider}/{s.model_id}" for r, s in ROSTER.items()})
    router = Router(store, run_id, ledger, use_cache=False)

    print("Testing whether the adjudicator can REFUSE to explain.\n")
    failures = []

    for label, a, b, cited, expected in CASES:
        pair = ClaimPair(a=a, b=b)
        pair.comparable = True
        pair.lineage_agreement = True
        conflict = {"id": new_id("cfl"), "run_id": run_id, "kind": "effect_vs_null",
                    "claim_a": a["id"], "claim_b": b["id"], "pair": pair}
        store.insert("conflicts",
                     {k: v for k, v in conflict.items() if k != "pair"}
                     | {"agreement": 1.0, "ts": "2026-08-16T00:00:00+00:00"})

        exps = explanations(run_id, conflict["id"], cited)
        verdict = adjudicate(router, store, run_id, conflict, exps)
        got = verdict["verdict"]
        ok = got == expected
        if not ok:
            failures.append(label)
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
        print(f"        expected {expected!r}, got {got!r} "
              f"(confidence {verdict['confidence']:.2f}, {verdict['lineage']})")
        print(f"        {clip(verdict['reasoning'], 140)}\n")

    store.finish_run(run_id, ledger.summary())
    router.close()
    store.close()

    if failures:
        print(f"FAILED: {', '.join(failures)}")
        if any(f.startswith("B") for f in failures):
            print("\nCase B failing means the adjudicator invents an explanation rather")
            print("than admitting none is available. That is the rationalisation failure")
            print("the whole design is meant to prevent — strengthen the veto prompt.")
        return 1
    print("Veto works: the adjudicator explains when it can and refuses when it cannot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
