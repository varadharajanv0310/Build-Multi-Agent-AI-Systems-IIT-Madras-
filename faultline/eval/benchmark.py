"""Benchmark cases.

Deliberately spread across five fields. A system claiming to be domain-general
should be evaluated that way, and showing it works across medicine, psychology,
education and economics is a stronger result than depth in one literature.

Each case names topical review terms rather than a pinned DOI, so the harness
discovers the ground-truth review at run time from OpenAlex. That keeps the
benchmark honest — no hand-picked review chosen because it flattered a result —
and keeps it working as literatures move.
"""
from __future__ import annotations

from faultline.eval.harness import BenchmarkCase

CASES: list[BenchmarkCase] = [
    BenchmarkCase(
        question="Does vitamin D supplementation prevent acute respiratory tract infections?",
        field="clinical nutrition",
        review_query="vitamin D supplementation acute respiratory tract infection prevention",
        must_contain=("vitamin d",),
        notes="Known moderator: baseline 25(OH)D status. Deficient populations "
              "benefit, replete ones do not — a real conflict with a real "
              "explanation, so the adjudicator should EXPLAIN rather than veto.",
    ),
    BenchmarkCase(
        question="Does omega-3 fatty acid supplementation reduce major adverse "
                 "cardiovascular events?",
        field="cardiovascular medicine",
        review_query="omega 3 fatty acid supplementation cardiovascular events "
                     "randomized trials",
        must_contain=("omega-3", "omega 3", "n-3", "fatty acid"),
        notes="Contested. Positive trials versus large null trials, with dose, "
              "EPA-versus-DHA and endpoint definition all proposed as moderators "
              "and none settled.",
    ),
    BenchmarkCase(
        question="Does mindfulness-based stress reduction reduce symptoms of anxiety?",
        field="clinical psychology",
        review_query="mindfulness based stress reduction anxiety randomized controlled trials",
        must_contain=("mindfulness",),
        notes="Dense small-RCT literature. Effect sizes shrink sharply with "
              "active control conditions — a design moderator.",
    ),
    BenchmarkCase(
        question="Does reducing class size improve student academic achievement?",
        field="education",
        review_query="class size reduction student achievement",
        must_contain=("class size",),
        notes="Large-scale experiments disagree with observational work; effects "
              "concentrate in early grades and disadvantaged pupils.",
    ),
    BenchmarkCase(
        question="Does raising the minimum wage reduce employment?",
        field="labour economics",
        review_query="minimum wage employment effects",
        must_contain=("minimum wage",),
        notes="The canonical contested literature. Disagreement is largely "
              "methodological rather than about a moderator, so this is the case "
              "most likely to produce a genuine UNRESOLVED verdict.",
    ),
]


def by_field(name: str) -> list[BenchmarkCase]:
    return [c for c in CASES if name.lower() in c.field.lower()]
