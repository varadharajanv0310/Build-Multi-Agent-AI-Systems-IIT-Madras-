"""Field Calibrator and Question Framer — the two agents that run first.

Field calibration is what makes a domain-general system possible. You cannot
apply one commensurability standard across medicine, machine learning, and
economics: what counts as evidence, what a primary study looks like, and which
terms travel under multiple names all differ. Calibration establishes those
norms once and configures everything downstream.

The Question Framer then produces the commensurability contract — an explicit
statement of what would make two claims comparable. Without that contract,
conflict detection is arbitrary: call everything comparable and you invent
contradictions, call nothing comparable and you find none.
"""
from __future__ import annotations

from faultline.config import Role
from faultline.router import Router

CALIBRATION_SCHEMA = {
    "type": "object",
    "properties": {
        "field": {"type": "string"},
        "evidence_hierarchy": {"type": "array", "items": {"type": "string"}},
        "primary_study_designs": {"type": "array", "items": {"type": "string"}},
        "secondary_study_designs": {"type": "array", "items": {"type": "string"}},
        "appraisal_framework": {"type": "string"},
        "appraisal_rationale": {"type": "string"},
        "terminology_variants": {"type": "array", "items": {"type": "string"}},
        "adjacent_fields": {"type": "array", "items": {"type": "string"}},
        "live_controversies": {"type": "array", "items": {"type": "string"}},
        "heterogeneity_conventions": {"type": "string"},
    },
    "required": ["field", "evidence_hierarchy", "primary_study_designs",
                 "appraisal_framework", "terminology_variants", "live_controversies"],
}

CALIBRATION_SYSTEM = """You establish the evidentiary norms of a research field \
so that downstream analysis uses that field's own standards rather than \
importing conventions from a neighbouring discipline.

Be concrete and specific to the field named. Do not give generic \
research-methods boilerplate that would be true of any discipline.

- evidence_hierarchy: what counts as evidence here, strongest first.
- primary_study_designs: design labels that mark a study as reporting NEW \
empirical results (e.g. "randomised controlled trial", "prospective cohort").
- secondary_study_designs: labels that mark synthesis of others' results \
(e.g. "systematic review", "meta-analysis", "narrative review").
- appraisal_framework: name the critical-appraisal approach that fits, and \
justify the choice in one line.
- terminology_variants: concepts that travel under multiple names, or single \
names covering distinct concepts. This is where retrieval silently misses work.
- adjacent_fields: fields studying the same phenomenon under different \
vocabulary. Uncited prior art hides here.
- live_controversies: genuine ongoing methodological disputes in this field.
- heterogeneity_conventions: how this field reports and explains disagreement \
between studies, if it does so formally at all."""

FRAMING_SCHEMA = {
    "type": "object",
    "properties": {
        "population": {"type": "string"},
        "intervention": {"type": "string"},
        "comparator": {"type": "string"},
        "outcome": {"type": "string"},
        "timepoint": {"type": "string"},
        "commensurability_must_match": {"type": "array", "items": {"type": "string"}},
        "commensurability_may_differ": {"type": "array", "items": {"type": "string"}},
        "inclusion_criteria": {"type": "string"},
        "exclusion_criteria": {"type": "string"},
        "search_queries": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["population", "intervention", "outcome",
                 "commensurability_must_match", "commensurability_may_differ",
                 "inclusion_criteria", "exclusion_criteria", "search_queries"],
}

FRAMING_SYSTEM = """You turn a research question into a formal review \
specification and a search strategy.

The most important output is the COMMENSURABILITY CONTRACT: which dimensions \
two findings must share before they can be said to agree or disagree, and \
which may differ without breaking comparability. Everything downstream is \
checked against this contract, so be precise.

Getting it wrong fails in both directions. Require too much and no two studies \
are ever comparable, so real contradictions are missed. Require too little and \
studies measuring different things appear to contradict each other.

SEARCH QUERIES matter as much. Write 4-6 keyword queries (not questions, no \
punctuation) aimed at PRIMARY studies reporting new empirical results. \
Relevance ranking surfaces reviews and meta-analyses first, which is backwards \
for this purpose - so include study-design terms and specific intervention or \
outcome vocabulary that primary reports use and reviews do not. Use the field's \
terminology variants so retrieval does not miss work filed under another name.

INCLUSION CRITERIA MUST BE BROAD. This is the opposite of how a human \
systematic review is written, and the reason is specific: the purpose here is \
to find where the literature DISAGREES WITH ITSELF. Narrow criteria \
manufacture consensus, because the studies that would have contradicted each \
other get excluded before anyone compares them.

So include studies that vary in population, dose or intensity, setting, \
follow-up length, and outcome variant, as long as they bear on the same \
underlying question. Those variations are not noise to be filtered out - they \
are the candidate EXPLANATIONS for why findings conflict, and removing them \
destroys the analysis.

Reserve exclusion for studies that are genuinely about a different question, a \
different intervention, or report no empirical result at all. Do not exclude on \
study quality, sample size, recency, or because a finding looks implausible - \
a null or unexpected result is exactly what conflict analysis needs."""


def calibrate_field(router: Router, question: str, field_hint: str | None = None) -> dict:
    """Establish the field's own evidentiary norms. Runs once per review."""
    hint = f"\nThe field appears to be: {field_hint}" if field_hint else ""
    result = router.complete(
        Role.CALIBRATION,
        [{"role": "system", "content": CALIBRATION_SYSTEM},
         {"role": "user", "content":
             f"Research question:\n{question}{hint}\n\n"
             "Characterise the evidentiary norms of the field this question belongs to."}],
        CALIBRATION_SCHEMA,
        stage="calibration",
    )
    return result.data


def frame_question(router: Router, question: str, calibration: dict) -> dict:
    """Produce the structured spec, the commensurability contract, and a
    search strategy aimed at primary studies."""
    ctx = (
        f"FIELD: {calibration.get('field', 'unknown')}\n"
        f"Primary study designs: {', '.join(calibration.get('primary_study_designs', []))}\n"
        f"Secondary (exclude as primary evidence): "
        f"{', '.join(calibration.get('secondary_study_designs', []))}\n"
        f"Terminology variants: {', '.join(calibration.get('terminology_variants', [])[:12])}\n"
        f"Live controversies: {'; '.join(calibration.get('live_controversies', [])[:5])}\n"
    )
    result = router.complete(
        Role.CALIBRATION,
        [{"role": "system", "content": FRAMING_SYSTEM},
         {"role": "user", "content":
             f"{ctx}\nRESEARCH QUESTION\n{question}\n\n"
             "Produce the review specification, the commensurability contract, "
             "and search queries targeting primary studies."}],
        FRAMING_SCHEMA,
        stage="framing",
    )
    return result.data


def criteria_text(spec: dict) -> str:
    """Render the spec into the screening prompt's criteria block."""
    return (
        f"INCLUDE: {spec.get('inclusion_criteria', '')}\n\n"
        f"EXCLUDE: {spec.get('exclusion_criteria', '')}\n\n"
        f"Population: {spec.get('population', 'any')}\n"
        f"Intervention: {spec.get('intervention', 'any')}\n"
        f"Comparator: {spec.get('comparator', 'any')}\n"
        f"Outcome: {spec.get('outcome', 'any')}"
    )


def contract_text(spec: dict) -> str:
    """Render the commensurability contract for the assessors."""
    must = spec.get("commensurability_must_match", [])
    may = spec.get("commensurability_may_differ", [])
    return (
        "COMMENSURABILITY CONTRACT\n"
        "Two findings are comparable only if they match on ALL of:\n"
        + "\n".join(f"  - {m}" for m in must)
        + "\n\nThey may differ on any of these without breaking comparability:\n"
        + "\n".join(f"  - {m}" for m in may)
    )
