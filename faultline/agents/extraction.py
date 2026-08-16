"""Claim Extractor — findings with their qualifiers.

Qualifiers are not metadata here; they are the raw material of the entire
analysis. A claim stripped of its scope conditions cannot be compared to
anything, so "reduced mortality" and "reduced 30-day mortality in ICU sepsis
patients at 4000 IU/day" are different objects and only the second is usable.

The hedge fields carry the same weight. Citation drift — a source saying "may
suggest" and the citing paper saying "demonstrates" — is invisible unless the
original strength markers survive extraction.
"""
from __future__ import annotations

from datetime import datetime, timezone

from faultline.config import Role
from faultline.retrieval.models import Paper
from faultline.router import Router
from faultline.store.db import Store, new_id

CLAIM_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "claim_type": {"type": "string",
                                   "enum": ["numeric", "empirical", "methodological",
                                            "definitional"]},
                    "citation_function": {"type": "string",
                                          "enum": ["own_finding", "support", "contrast",
                                                   "background", "method_use"]},
                    "direction": {"type": "string",
                                  "enum": ["positive", "negative", "null", "mixed",
                                           "not_stated"]},
                    "magnitude": {"type": "string"},
                    "uncertainty": {"type": "string"},
                    "population": {"type": "string"},
                    "sample_size": {"type": "string"},
                    "design": {"type": "string"},
                    "outcome_measure": {"type": "string"},
                    "timepoint": {"type": "string"},
                    "scope_conditions": {"type": "array", "items": {"type": "string"}},
                    "hedges": {"type": "array", "items": {"type": "string"}},
                    "locator": {"type": "string"},
                    "confidence_tag": {"type": "string", "enum": ["V", "R", "U"]},
                },
                "required": ["text", "direction", "population", "outcome_measure",
                             "scope_conditions", "hedges", "confidence_tag",
                             "citation_function"],
            },
        }
    },
    "required": ["claims"],
}

EXTRACTION_SYSTEM = """You extract research findings from a paper, together with \
the qualifiers that make them comparable to other findings.

Extract ONLY findings this paper itself reports or explicitly attributes. Do \
not infer, do not generalise, do not add what you know from elsewhere.

For every claim capture:

- direction. Read this carefully, because the obvious reading is wrong:
    "positive"  - the intervention HELPED. A real effect in the beneficial
                  direction, statistically supported.
    "negative"  - the intervention HARMED. A real effect in the opposite
                  direction, statistically supported.
    "null"      - NO effect was demonstrated either way.
    "mixed"     - helped on one outcome or subgroup, not on another.

  "negative" does NOT mean "a negative finding" or "found no benefit". Those
  are "null". This distinction decides whether two studies genuinely conflict,
  and getting it wrong invents contradictions between studies that in fact
  agree.

  The arithmetic test overrides any wording: if the confidence interval
  crosses the no-effect value (1.0 for a ratio, 0 for a difference), or the
  result is described as non-significant, the direction is "null" - however
  the point estimate reads. A hazard ratio of 1.01 with CI 0.93 to 1.10 is
  null, not negative. A rate ratio of 0.52 with CI 0.31 to 0.89 is positive.

  A null result is a real finding, not a missing one, and null results are
  exactly what conflict analysis needs.
- magnitude and uncertainty: verbatim numbers where given. If absent, write \
"not reported". NEVER invent or approximate a figure.
- population, design, sample_size, outcome_measure, timepoint: as stated.
- scope_conditions: the boundaries the authors place on the finding - dose, \
setting, subgroup, duration, baseline status. This is what separates a narrow \
result from a general one.
- hedges: the authors' own strength markers, quoted. "may", "suggests", \
"is associated with", "demonstrates". Losing these makes citation drift \
invisible later.
- citation_function: own_finding when the paper reports it; support / contrast \
/ background / method_use when it is citing someone else. Running conflict \
analysis on a "contrast" citation is a category error, so label it honestly.
- confidence_tag: V if the text states it directly, R if you are reading \
between the lines, U if you are unsure what is being claimed.

Prefer few well-qualified claims over many vague ones. If the text does not \
support a field, say "not reported" rather than guessing."""


def extract_claims(
    router: Router,
    store: Store,
    run_id: str,
    papers: list[Paper],
    question: str,
    max_chars: int = 9000,
) -> list[dict]:
    """Extract qualified claims from each paper relevant to the question."""
    items = []
    for p in papers:
        body = (p.fulltext or p.abstract or "").strip()
        if not body:
            continue
        if len(body) > max_chars:
            body = body[:max_chars] + " ...[truncated]"
        prompt = (
            f"RESEARCH QUESTION UNDER REVIEW\n{question}\n\n"
            f"PAPER\nTitle: {p.title}\nYear: {p.year or 'unknown'}\n"
            f"Design hint: {p.type or 'unknown'}\n\n{body}\n\n"
            "Extract the findings from this paper that bear on the research "
            "question, with their qualifiers."
        )
        items.append((p.id, [{"role": "system", "content": EXTRACTION_SYSTEM},
                             {"role": "user", "content": prompt}]))

    results = router.batch(Role.EXTRACTION, items, CLAIM_SCHEMA, stage="extraction")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows: list[dict] = []
    for paper_id, res in results.items():
        for c in res.data.get("claims", []) or []:
            if not c.get("text"):
                continue
            rows.append({
                "id": new_id("clm"),
                "run_id": run_id,
                "paper_id": paper_id,
                "text": c.get("text", "")[:2000],
                "claim_type": c.get("claim_type"),
                "citation_function": c.get("citation_function"),
                "population": c.get("population"),
                "sample_size": c.get("sample_size"),
                "design": c.get("design"),
                "direction": c.get("direction"),
                "magnitude": c.get("magnitude"),
                "uncertainty": c.get("uncertainty"),
                "outcome_measure": c.get("outcome_measure"),
                "timepoint": c.get("timepoint"),
                "scope_conditions_json": c.get("scope_conditions") or [],
                "hedges_json": c.get("hedges") or [],
                "confidence_tag": c.get("confidence_tag", "U"),
                "locator": c.get("locator"),
                "extracted_by": res.model_id,
                "lineage": res.lineage,
                "created_at": now,
            })

    store.insert_many("claims", rows)
    return rows


def usable_for_conflict(claim: dict) -> bool:
    """Claims eligible for conflict analysis.

    Two exclusions carry real weight. A claim the paper is merely CITING is not
    this paper's evidence, and a "contrast" citation exists precisely to
    disagree — treating either as a finding manufactures false conflicts. A
    direction of not_stated cannot contradict anything.
    """
    return (
        claim.get("citation_function") == "own_finding"
        and claim.get("direction") in ("positive", "negative", "null", "mixed")
    )
