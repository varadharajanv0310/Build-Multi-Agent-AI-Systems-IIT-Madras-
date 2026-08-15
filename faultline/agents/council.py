"""The council: commensurability, conflict, explanation, adjudication, gaps.

This is where the system becomes itself. Four properties are deliberate:

1. Commensurability is judged by TWO OPPOSED LINEAGES, not one model. Getting
   it wrong fails both ways — call everything comparable and you invent
   contradictions, call nothing comparable and you find none — and a single
   pass is wrong constantly.

2. Explanations COMPETE. Each stance argues one explanation type and must cite
   concrete study attributes; an explanation citing nothing is a post-hoc
   rationalisation and the adjudicator is entitled to say so.

3. The adjudicator can REJECT EVERY EXPLANATION. That veto is the single most
   important behaviour here, because an unresolved conflict is what produces a
   research gap. A system that always finds an explanation has learned to
   rationalise.

4. Nothing is averaged. Divergence between lineages is recorded and escalated,
   never smoothed into a middle position.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timezone

from faultline.config import Role
from faultline.providers.base import confidence as _conf
from faultline.router import Router
from faultline.store.db import Store, new_id

# --- schemas -----------------------------------------------------------------

COMMENSURABILITY_SCHEMA = {
    "type": "object",
    "properties": {
        "comparable": {"type": "boolean"},
        "reason_code": {
            "type": "string",
            "enum": ["same_construct", "different_outcome_measure",
                     "different_population", "different_timepoint",
                     "different_intervention", "insufficient_information"],
        },
        "argument": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["comparable", "reason_code", "argument", "confidence"],
}

EXPLANATION_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string"},
        "cited_attributes": {"type": "array", "items": {"type": "string"}},
        "plausibility": {"type": "number"},
        "applies": {"type": "boolean"},
    },
    "required": ["explanation", "cited_attributes", "plausibility", "applies"],
}

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string",
                    "enum": ["explained", "unresolved", "not_a_conflict"]},
        "winning_stance": {"type": "string"},
        "reasoning": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["verdict", "reasoning", "confidence"],
}

GAP_SCHEMA = {
    "type": "object",
    "properties": {
        "bucket": {"type": "string",
                   "enum": ["empirical", "methodological", "theoretical",
                            "translational"]},
        "status": {"type": "string",
                   "enum": ["open", "unimportant", "already_closed", "intractable"]},
        "proposition": {"type": "string"},
        "rationale": {"type": "string"},
    },
    "required": ["bucket", "status", "proposition", "rationale"],
}

# --- stances -----------------------------------------------------------------
# Each panellist argues ONE explanation type. Same prompt to three models would
# be ensembling; different stances on different lineages is a panel.

STANCES: dict[str, str] = {
    "population": "The studies disagree because they enrolled materially "
                  "different populations - baseline status, age, health, risk profile.",
    "dose_exposure": "The studies disagree because the intervention differed in "
                     "dose, frequency, duration, formulation or adherence.",
    "measurement": "The studies disagree because they operationalised the outcome "
                   "differently, or measured it at different timepoints.",
    "power_design": "The studies disagree because of sample size, power, design "
                    "quality, or analytic choices rather than any real effect difference.",
}

PANEL_ROLES = [Role.PANEL_1, Role.PANEL_2, Role.PANEL_3]


@dataclass
class ClaimPair:
    a: dict
    b: dict
    id: str = ""
    comparable: bool | None = None
    lineage_agreement: bool | None = None
    assessments: list[dict] = field(default_factory=list)

    def __post_init__(self):
        if not self.id:
            self.id = new_id("pair")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _describe(claim: dict) -> str:
    scope = claim.get("scope_conditions_json") or []
    if isinstance(scope, str):
        scope = [scope]
    hedges = claim.get("hedges_json") or []
    if isinstance(hedges, str):
        hedges = [hedges]
    return (
        f"Finding: {claim.get('text', '')}\n"
        f"  direction: {claim.get('direction')}\n"
        f"  magnitude: {claim.get('magnitude') or 'not reported'}\n"
        f"  uncertainty: {claim.get('uncertainty') or 'not reported'}\n"
        f"  population: {claim.get('population')}\n"
        f"  sample size: {claim.get('sample_size') or 'not reported'}\n"
        f"  design: {claim.get('design') or 'not reported'}\n"
        f"  outcome measure: {claim.get('outcome_measure')}\n"
        f"  timepoint: {claim.get('timepoint') or 'not reported'}\n"
        f"  scope conditions: {'; '.join(str(s) for s in scope) or 'none stated'}\n"
        f"  author hedges: {'; '.join(str(h) for h in hedges) or 'none'}"
    )


# --- stage 1: commensurability ------------------------------------------------

COMM_SYSTEM_BASE = """You judge whether two research findings are COMMENSURABLE - \
whether they are measuring the same thing closely enough that agreeing or \
disagreeing is meaningful.

You are not judging whether they agree. You are judging whether comparing them \
is legitimate at all.

{contract}

{stance}

State your argument in one or two sentences, grounded in the specific \
qualifiers shown. Do not hedge toward the middle to seem balanced - argue your \
assigned reading honestly, and if the evidence genuinely defeats it, say so."""

STANCE_A = ("Your assigned reading: these findings ARE commensurable. Look for "
            "the shared construct. Do not manufacture agreement that is not there.")
STANCE_B = ("Your assigned reading: these findings are NOT commensurable. Look "
            "for the dimension on which they differ materially. Do not manufacture "
            "a difference that does not matter.")


def candidate_pairs(claims: list[dict], max_pairs: int = 60) -> list[ClaimPair]:
    """Generate claim pairs worth assessing.

    Pairing is quadratic, and hosted free-tier calls scale with pair count, so
    the cheap deterministic filters matter: claims from the same paper cannot
    contradict each other in the sense we care about, and two findings pointing
    the same direction are not a conflict candidate.
    """
    pairs: list[ClaimPair] = []
    for a, b in itertools.combinations(claims, 2):
        if a["paper_id"] == b["paper_id"]:
            continue
        da, db = a.get("direction"), b.get("direction")
        # Only directional opposition is a conflict candidate. Two positives
        # agreeing is a corroboration edge, handled elsewhere.
        if da == db:
            continue
        if {da, db} <= {"positive", "negative", "null", "mixed"}:
            pairs.append(ClaimPair(a=a, b=b))
        if len(pairs) >= max_pairs:
            break
    return pairs


def assess_commensurability(
    router: Router, store: Store, run_id: str,
    pairs: list[ClaimPair], contract: str,
) -> list[ClaimPair]:
    """Two opposed lineages judge each pair. Divergence is kept, not resolved."""
    for pair in pairs:
        body = (f"FINDING 1\n{_describe(pair.a)}\n\nFINDING 2\n{_describe(pair.b)}\n\n"
                "Are these two findings commensurable?")
        msgs_a = [{"role": "system",
                   "content": COMM_SYSTEM_BASE.format(contract=contract, stance=STANCE_A)},
                  {"role": "user", "content": body}]
        msgs_b = [{"role": "system",
                   "content": COMM_SYSTEM_BASE.format(contract=contract, stance=STANCE_B)},
                  {"role": "user", "content": body}]

        a_res, b_res, agreed = router.opposed(
            Role.COMMENSURABILITY_A, Role.COMMENSURABILITY_B,
            msgs_a, msgs_b, COMMENSURABILITY_SCHEMA,
            agree_on="comparable", stage="commensurability", subject_id=pair.id)

        pair.lineage_agreement = agreed
        rows = []
        for side, res in (("a", a_res), ("b", b_res)):
            if res is None:
                continue
            pair.assessments.append({**res.data, "side": side, "lineage": res.lineage})
            rows.append({
                "id": new_id("cma"), "run_id": run_id,
                "claim_a": pair.a["id"], "claim_b": pair.b["id"], "side": side,
                "comparable": int(bool(res.data.get("comparable"))),
                "reason_code": res.data.get("reason_code"),
                "argument": str(res.data.get("argument", ""))[:1000],
                "confidence": _conf(res.data.get("confidence")),
                "model_id": res.model_id, "lineage": res.lineage, "ts": _now(),
            })
        store.insert_many("commensurability", rows)

        # Both agreeing that it is comparable is the only clean pass. A split
        # is NOT resolved by majority here — it is carried forward as a
        # low-confidence conflict so the adjudicator sees the disagreement.
        votes = [bool(x.get("comparable")) for x in pair.assessments]
        pair.comparable = bool(votes) and any(votes)
    return pairs


# --- stage 2: conflicts -------------------------------------------------------

def detect_conflicts(store: Store, run_id: str, pairs: list[ClaimPair]) -> list[dict]:
    """Deterministic given commensurability and direction."""
    conflicts = []
    for pair in pairs:
        if not pair.comparable:
            continue
        da, db = pair.a.get("direction"), pair.b.get("direction")
        if {da, db} == {"positive", "negative"}:
            kind = "opposite_direction"
        elif "null" in (da, db):
            kind = "effect_vs_null"
        elif "mixed" in (da, db):
            kind = "mixed_vs_definite"
        else:
            continue
        agreement = 1.0 if pair.lineage_agreement else 0.5
        row = {
            "id": new_id("cfl"), "run_id": run_id,
            "claim_a": pair.a["id"], "claim_b": pair.b["id"],
            "kind": kind, "agreement": agreement, "ts": _now(),
        }
        store.insert("conflicts", row)
        conflicts.append({**row, "pair": pair})
    return conflicts


# --- stage 3: explanation panel ----------------------------------------------

PANEL_SYSTEM = """You are one member of a panel explaining why two research \
findings disagree. Each member argues a DIFFERENT explanation type; yours is:

{stance}

Argue only your assigned explanation. Another panellist covers the others.

You must ground the explanation in CONCRETE ATTRIBUTES of the two studies as \
shown - specific populations, doses, measures, timepoints, sample sizes. List \
them in cited_attributes, quoting the study detail you rely on.

If your assigned explanation genuinely does not apply to this pair, set \
applies=false and say so. A panel where every stance claims to fit is useless, \
and an explanation citing no concrete attribute is a post-hoc rationalisation \
that will be rejected."""


def run_panel(router: Router, store: Store, run_id: str, conflict: dict) -> list[dict]:
    pair: ClaimPair = conflict["pair"]
    body = (f"FINDING 1\n{_describe(pair.a)}\n\nFINDING 2\n{_describe(pair.b)}\n\n"
            "These findings disagree. Argue your assigned explanation.")
    out = []
    for role, (stance_name, stance_text) in zip(PANEL_ROLES, list(STANCES.items())):
        try:
            res = router.complete(
                role,
                [{"role": "system", "content": PANEL_SYSTEM.format(stance=stance_text)},
                 {"role": "user", "content": body}],
                EXPLANATION_SCHEMA, stage="panel", subject_id=conflict["id"])
        except Exception:
            continue
        rec = {
            "id": new_id("exp"), "run_id": run_id, "conflict_id": conflict["id"],
            "stance": stance_name,
            "argument": str(res.data.get("explanation", ""))[:1500],
            "cited_attributes_json": res.data.get("cited_attributes") or [],
            "confidence": _conf(res.data.get("plausibility")),
            "model_id": res.model_id, "lineage": res.lineage, "ts": _now(),
        }
        store.insert("explanations", rec)
        rec["applies"] = bool(res.data.get("applies", True))
        out.append(rec)
    return out


# --- stage 4: adjudication ----------------------------------------------------

ADJUDICATOR_SYSTEM = """You adjudicate between competing explanations for why \
two research findings disagree.

You have three verdicts, and they are not equally weighted by default:

- "explained": ONE stance is genuinely supported by concrete attributes of \
these specific studies. Name it.
- "unresolved": no stance is adequately supported by the available study \
characteristics. The disagreement is real but nothing in the evidence explains it.
- "not_a_conflict": the findings are not actually in tension once their scope \
conditions are read carefully.

"unresolved" is a FIRST-CLASS verdict, not a fallback. Reaching for it when the \
evidence does not support any explanation is the correct and valuable outcome - \
it is what identifies a genuine research gap. A plausible-sounding story that \
cites no concrete study attribute is a rationalisation; reject it.

Judge the arguments against the study details, not against your own prior \
beliefs about the topic. An explanation that merely sounds sensible but is not \
grounded in these two studies fails."""


def adjudicate(router: Router, store: Store, run_id: str,
               conflict: dict, explanations: list[dict]) -> dict:
    pair: ClaimPair = conflict["pair"]
    if not explanations:
        row = {"conflict_id": conflict["id"], "run_id": run_id, "verdict": "unresolved",
               "winning_stance": None, "reasoning": "no explanation was produced",
               "confidence": 0.0, "model_id": "none", "lineage": "none", "ts": _now()}
        store.insert("verdicts", row)
        return row

    blocks = []
    for e in explanations:
        cited = e.get("cited_attributes_json") or []
        blocks.append(
            f"STANCE: {e['stance']}  (argued by {e['lineage']}, "
            f"applies={e.get('applies')}, plausibility={e['confidence']})\n"
            f"  {e['argument']}\n"
            f"  cited study attributes: "
            f"{'; '.join(str(c) for c in cited) or 'NONE — cites nothing concrete'}")

    split_note = ""
    if pair.lineage_agreement is False:
        split_note = ("\nNOTE: the two commensurability assessors DISAGREED on whether "
                      "these findings are even comparable. Weigh that.\n")

    body = (f"FINDING 1\n{_describe(pair.a)}\n\nFINDING 2\n{_describe(pair.b)}\n"
            f"{split_note}\nCOMPETING EXPLANATIONS\n\n" + "\n\n".join(blocks) +
            "\n\nAdjudicate.")

    res = router.complete(
        Role.ADJUDICATION,
        [{"role": "system", "content": ADJUDICATOR_SYSTEM},
         {"role": "user", "content": body}],
        VERDICT_SCHEMA, stage="adjudication", subject_id=conflict["id"])

    row = {
        "conflict_id": conflict["id"], "run_id": run_id,
        "verdict": res.data.get("verdict", "unresolved"),
        "winning_stance": res.data.get("winning_stance"),
        "reasoning": str(res.data.get("reasoning", ""))[:2000],
        "confidence": _conf(res.data.get("confidence")),
        "model_id": res.model_id, "lineage": res.lineage, "ts": _now(),
    }
    store.insert("verdicts", row)
    return row


# --- stage 5: gaps ------------------------------------------------------------

GAP_SYSTEM = """An unresolved disagreement between studies marks a research gap. \
Classify it and state it as something testable.

bucket:
- empirical: an untested population, setting, dose or condition
- methodological: the field lacks a way to measure or test this
- theoretical: competing definitions or unexamined assumptions
- translational: nothing works under real-world constraints

status:
- open: genuinely unaddressed
- unimportant: open but would not change practice
- already_closed: likely settled by work not in this corpus
- intractable: open because it cannot practically be resolved

proposition: state the specific study that would resolve it - population, \
comparison, outcome, and the moderator it would test. Never write "more \
research is needed"; that is not a proposition."""


def classify_gap(router: Router, store: Store, run_id: str,
                 conflict: dict, verdict: dict) -> dict | None:
    if verdict.get("verdict") != "unresolved":
        return None
    pair: ClaimPair = conflict["pair"]
    body = (f"FINDING 1\n{_describe(pair.a)}\n\nFINDING 2\n{_describe(pair.b)}\n\n"
            f"ADJUDICATION: unresolved. {verdict.get('reasoning', '')}\n\n"
            "Classify the gap and state what would resolve it.")
    try:
        res = router.complete(
            Role.ADJUDICATION,
            [{"role": "system", "content": GAP_SYSTEM},
             {"role": "user", "content": body}],
            GAP_SCHEMA, stage="gaps", subject_id=conflict["id"])
    except Exception:
        return None
    row = {
        "id": new_id("gap"), "run_id": run_id, "conflict_id": conflict["id"],
        "bucket": res.data.get("bucket", "empirical"),
        "status": res.data.get("status", "open"),
        "proposition": str(res.data.get("proposition", ""))[:1500],
        "rationale": str(res.data.get("rationale", ""))[:1500],
        "ts": _now(),
    }
    store.insert("gaps", row)
    return row
