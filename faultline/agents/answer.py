"""Answer a question from the literature.

Question mode's job is to ANSWER — "how much magnesium per day?" gets a number
and the evidence behind it, not a lecture about disagreement.

Disagreement still matters, but it belongs in its proper place: after the
answer, as a caveat on confidence, rather than instead of one. A tool that
refuses to answer because the literature is messy has just handed the work back
to the person who asked.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from faultline.config import Role
from faultline.router import Router

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "headline": {"type": "string"},
        "confidence": {"type": "string",
                       "enum": ["high", "moderate", "low", "insufficient_evidence"]},
        "consensus": {"type": "string",
                      "enum": ["strong", "qualified", "contested", "no_consensus"]},
        "supporting_claims": {"type": "array", "items": {"type": "integer"}},
        # Conditions carry the axis they vary on, so the reader can scan for the
        # one that applies to them instead of reading four sentences of prose.
        "caveats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "axis": {"type": "string",
                             "enum": ["population", "dose", "duration", "setting",
                                      "measurement", "design"]},
                    "text": {"type": "string"},
                },
                "required": ["axis", "text"],
            },
        },
        "disagreements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "refs": {"type": "string"},
                },
                "required": ["text"],
            },
        },
        "what_would_settle_it": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "headline", "confidence", "consensus", "caveats"],
}

ANSWER_SYSTEM = """Answer the question using ONLY the findings supplied. You are \
writing for someone who needs a usable answer, not a literature lecture.

- headline: the direct answer in one sentence. If the question asks for a \
number, give the number and its units. Do not open with "it depends" - state \
the central answer, then qualify it.
- answer: two to four sentences expanding it, citing findings by their [n] \
index so every statement is traceable.
- consensus: strong (findings broadly agree) / qualified (agree within stated \
limits) / contested (they genuinely conflict) / no_consensus.
- confidence: your confidence in the headline given the evidence supplied.
- caveats: the conditions that change the answer. Each carries the axis it \
varies on (population, dose, duration, setting, measurement, design) and one \
sentence saying how the answer shifts along it. These are the practical part.
- disagreements: each place the findings genuinely conflict. "text" states what \
is contested; "refs" cites the finding indices on each side and, where you can \
see it, what the difference traces to. Empty list if they do not conflict - \
manufacturing a disagreement is as bad as hiding one.
- what_would_settle_it: the specific studies that would resolve it, one per \
item. Only when the evidence is genuinely insufficient or contested.

Never invent a number, a study, or a figure that is not in the supplied \
findings. If they cannot answer the question, say so in the headline and set \
confidence to insufficient_evidence. An honest "the evidence does not settle \
this" is a real answer; a fabricated precision is not."""


@dataclass
class Answer:
    question: str
    headline: str = ""
    answer: str = ""
    confidence: str = "insufficient_evidence"
    consensus: str = "no_consensus"
    caveats: list[dict] = field(default_factory=list)
    disagreements: list[dict] = field(default_factory=list)
    what_would_settle_it: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    supporting_idx: list[int] = field(default_factory=list)

    @property
    def is_answerable(self) -> bool:
        return self.confidence != "insufficient_evidence"

    @property
    def disagreement(self) -> str:
        """Flat rendering, for surfaces that want one paragraph."""
        return "  ".join(d.get("text", "") for d in self.disagreements).strip()


def format_evidence(claims: list[dict], limit: int = 20) -> str:
    lines = []
    for i, c in enumerate(claims[:limit], 1):
        scope = c.get("scope_conditions_json") or []
        if isinstance(scope, str):
            scope = [scope]
        lines.append(
            f"[{i}] {c.get('text', '')}\n"
            f"     direction={c.get('direction')}  "
            f"magnitude={c.get('magnitude') or 'not reported'}\n"
            f"     population={c.get('population')}  "
            f"outcome={c.get('outcome_measure')}\n"
            f"     scope={'; '.join(str(s) for s in scope) or 'none stated'}")
    return "\n".join(lines)


def answer_question(router: Router, question: str, claims: list[dict]) -> Answer:
    """Synthesise a direct answer from extracted findings."""
    ans = Answer(question=question, evidence=claims[:20])

    if not claims:
        ans.headline = "No usable evidence was retrieved for this question."
        ans.answer = ("Retrieval and screening did not produce findings that "
                      "bear on the question. That is a retrieval result, not a "
                      "conclusion about the literature.")
        return ans

    res = router.complete(
        Role.ADJUDICATION,
        [{"role": "system", "content": ANSWER_SYSTEM},
         {"role": "user", "content":
             f"QUESTION\n{question}\n\nFINDINGS FROM THE LITERATURE\n"
             f"{format_evidence(claims)}\n\nAnswer the question."}],
        ANSWER_SCHEMA, stage="answer")

    d = res.data
    ans.headline = str(d.get("headline", ""))
    ans.answer = str(d.get("answer", ""))
    ans.confidence = str(d.get("confidence", "low"))
    ans.consensus = str(d.get("consensus", "no_consensus"))
    ans.caveats = _caveats(d.get("caveats"))
    ans.disagreements = _disagreements(d)
    ans.what_would_settle_it = _settle(d.get("what_would_settle_it"))
    ans.supporting_idx = [int(i) for i in (d.get("supporting_claims") or [])
                          if isinstance(i, (int, float))]
    return ans


_AXES = ("population", "dose", "duration", "setting", "measurement", "design")


def _caveats(raw: object) -> list[dict]:
    """Normalise conditions to {axis, text}.

    The schema asks for objects, but a model under load returns bare strings.
    A string that opens with a recognised axis ("Dose: ...") keeps it; anything
    else is filed under the axis we can actually defend, which is none.
    """
    out: list[dict] = []
    for c in (raw or []):
        if isinstance(c, dict):
            axis = str(c.get("axis", "")).strip().lower()
            text = str(c.get("text", "")).strip()
        else:
            axis, _, rest = str(c).partition(":")
            axis, text = axis.strip().lower(), rest.strip()
            if axis not in _AXES or not text:
                axis, text = "", " ".join(str(c).split())
        if not text:
            continue
        out.append({"axis": axis if axis in _AXES else "condition", "text": text})
    return out


def _disagreements(d: dict) -> list[dict]:
    raw = d.get("disagreements")
    # Older prompt shape returned a single prose field; accept it rather than
    # dropping a real disagreement on the floor.
    if not raw:
        legacy = str(d.get("disagreement") or "").strip()
        return [{"text": legacy, "refs": ""}] if legacy else []
    out: list[dict] = []
    for item in raw:
        if isinstance(item, dict):
            text = str(item.get("text", "")).strip()
            refs = str(item.get("refs", "")).strip()
        else:
            text, refs = " ".join(str(item).split()), ""
        if text:
            out.append({"text": text, "refs": refs})
    return out


def _settle(raw: object) -> list[str]:
    if isinstance(raw, str):
        raw = [raw] if raw.strip() else []
    return [" ".join(str(x).split()) for x in (raw or []) if str(x).strip()]
