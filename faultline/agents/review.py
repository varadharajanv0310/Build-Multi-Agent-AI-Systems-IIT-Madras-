"""Review a paper the way a hostile-but-fair reviewer would.

Three reviewers with different priors, each on a DIFFERENT model lineage. That
is the point: three prompts on one model produce three flavours of the same
blind spot, whereas three lineages disagree about what matters, which is what
real review panels do.

Reviewer objections are the useful output. A review that only praises is
worthless before submission, because the actual referee will not be kind.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from faultline.config import Role
from faultline.router import Router

REVIEWER_ROLES = [Role.PANEL_1, Role.PANEL_2, Role.PANEL_3]

REVIEWERS = [
    ("R1 — framing", "You attack FRAMING: the problem definition, the "
     "assumptions, whether the question is well-posed, whether the framing "
     "hides something."),
    ("R2 — method", "You attack METHOD and EVIDENCE: design, sample, measures, "
     "comparisons, statistics, what the data cannot support."),
    ("R3 — significance", "You attack SIGNIFICANCE: whether the contribution is "
     "novel and large enough to matter, and whether prior work already did it."),
]

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "objections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "objection": {"type": "string"},
                    "severity": {"type": "string",
                                 "enum": ["fatal", "major", "minor"]},
                    "minimum_fix": {"type": "string"},
                },
                "required": ["objection", "severity", "minimum_fix"],
            },
        },
        "strongest_point": {"type": "string"},
    },
    "required": ["objections"],
}

REVIEWER_SYSTEM = """You are peer-reviewing a paper before submission, so the \
author can fix problems before a real referee finds them.

{stance}

Give your three strongest objections. For each: state it concretely, rate its \
severity, and give the MINIMUM change that would neutralise it. Objections the \
author cannot act on are useless.

Be specific to this paper. Generic methodology complaints that would apply to \
any paper are noise. If the paper is genuinely strong on your axis, say so in \
strongest_point rather than manufacturing a complaint - but do not soften a \
real problem to be polite."""

APPRAISAL_SCHEMA = {
    "type": "object",
    "properties": {
        "evidence_base": {"type": "string",
                          "enum": ["strong", "moderate", "thin", "performative"]},
        "assessment": {"type": "string"},
        "systemic_issues": {"type": "array", "items": {"type": "string"}},
        "construct_validity": {"type": "string"},
    },
    "required": ["evidence_base", "assessment"],
}

APPRAISAL_SYSTEM = """Appraise the quality of the evidence base this paper sits \
in — the field's evidence, not only this paper's.

- evidence_base: strong / moderate / thin / performative. "performative" means \
the field cites heavily but the underlying evidence is weak or unreplicated.
- systemic_issues: publication bias, missing null results, small-sample norms, \
absent replication, benchmark overfitting, unfalsifiable framing.
- construct_validity: does the field's standard measure actually capture what \
it claims to?

Base this on the retrieved findings supplied, not on general impressions."""

POSITION_SCHEMA = {
    "type": "object",
    "properties": {
        "placement": {"type": "string"},
        "nearest_works": {"type": "array", "items": {"type": "string"}},
        "novelty_claim": {"type": "string"},
        "novelty_risk": {"type": "string",
                         "enum": ["defensible", "weak", "already_done", "unclear"]},
        "collapse_risk": {"type": "string"},
        "must_cite": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["placement", "novelty_claim", "novelty_risk"],
}

POSITION_SYSTEM = """Position this paper against the literature retrieved.

- placement: where the contribution sits, in one or two sentences.
- nearest_works: the retrieved findings closest to it, and why each is close.
- novelty_claim: a publication-ready "unlike prior work, we..." sentence.
- novelty_risk: defensible / weak / already_done / unclear. Be blunt - telling \
the author their novelty claim is weak now is worth more than a referee saying \
it later.
- collapse_risk: the prior work this contribution is most likely to be \
dismissed as a special case of, and the one sentence that prevents that.
- must_cite: retrieved works whose absence a referee would notice."""


@dataclass
class Objection:
    reviewer: str
    lineage: str
    objection: str
    severity: str
    minimum_fix: str


@dataclass
class PaperReview:
    paper_title: str = ""
    claims: list[dict] = field(default_factory=list)
    literature: list[dict] = field(default_factory=list)
    appraisal: dict = field(default_factory=dict)
    positioning: dict = field(default_factory=dict)
    objections: list[Objection] = field(default_factory=list)
    unanswerable: str = ""

    @property
    def fatal(self) -> list[Objection]:
        return [o for o in self.objections if o.severity == "fatal"]

    @property
    def major(self) -> list[Objection]:
        return [o for o in self.objections if o.severity == "major"]


def _paper_block(title: str, claims: list[dict], limit: int = 8) -> str:
    lines = [f"PAPER: {title}", "", "ITS CLAIMS:"]
    for i, c in enumerate(claims[:limit], 1):
        lines.append(
            f"  [{i}] {c.get('text', '')}\n"
            f"      direction={c.get('direction')} "
            f"magnitude={c.get('magnitude') or 'not reported'}\n"
            f"      population={c.get('population')} "
            f"design={c.get('design') or 'not reported'}\n"
            f"      scope={c.get('scope_conditions_json')} "
            f"hedges={c.get('hedges_json')}")
    return "\n".join(lines)


def _lit_block(literature: list[dict], limit: int = 14) -> str:
    if not literature:
        return "RETRIEVED LITERATURE: none found."
    lines = ["RETRIEVED LITERATURE:"]
    for i, c in enumerate(literature[:limit], 1):
        lines.append(f"  [{i}] [{c.get('direction')}] {c.get('text', '')[:170]}"
                     f"  ({c.get('population')})")
    return "\n".join(lines)


def run_reviewer_panel(router: Router, review: PaperReview) -> list[Objection]:
    """Three reviewers, three priors, three lineages."""
    ctx = (_paper_block(review.paper_title, review.claims) + "\n\n"
           + _lit_block(review.literature))
    out: list[Objection] = []
    for role, (name, stance) in zip(REVIEWER_ROLES, REVIEWERS):
        try:
            res = router.complete(
                role,
                [{"role": "system", "content": REVIEWER_SYSTEM.format(stance=stance)},
                 {"role": "user", "content": ctx + "\n\nReview this paper."}],
                REVIEW_SCHEMA, stage="review_panel")
        except Exception:
            continue
        for o in (res.data.get("objections") or [])[:3]:
            out.append(Objection(
                reviewer=name, lineage=res.lineage,
                objection=str(o.get("objection", ""))[:600],
                severity=str(o.get("severity", "minor")),
                minimum_fix=str(o.get("minimum_fix", ""))[:400]))
    return out


def appraise(router: Router, review: PaperReview) -> dict:
    try:
        res = router.complete(
            Role.ADJUDICATION,
            [{"role": "system", "content": APPRAISAL_SYSTEM},
             {"role": "user", "content":
                 _paper_block(review.paper_title, review.claims) + "\n\n"
                 + _lit_block(review.literature) + "\n\nAppraise the evidence base."}],
            APPRAISAL_SCHEMA, stage="appraisal")
        return res.data
    except Exception:
        return {}


def position(router: Router, review: PaperReview) -> dict:
    try:
        res = router.complete(
            Role.ADJUDICATION,
            [{"role": "system", "content": POSITION_SYSTEM},
             {"role": "user", "content":
                 _paper_block(review.paper_title, review.claims) + "\n\n"
                 + _lit_block(review.literature) + "\n\nPosition this paper."}],
            POSITION_SCHEMA, stage="positioning")
        return res.data
    except Exception:
        return {}
