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
        "caveats": {"type": "array", "items": {"type": "string"}},
        "disagreement": {"type": "string"},
        "what_would_settle_it": {"type": "string"},
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
- caveats: the conditions that change the answer - population, dose, duration, \
setting. These are the practical part.
- disagreement: where the findings conflict and on what. Empty if they do not.
- what_would_settle_it: only if the evidence is genuinely insufficient.

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
    caveats: list[str] = field(default_factory=list)
    disagreement: str = ""
    what_would_settle_it: str = ""
    evidence: list[dict] = field(default_factory=list)
    supporting_idx: list[int] = field(default_factory=list)

    @property
    def is_answerable(self) -> bool:
        return self.confidence != "insufficient_evidence"


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
    ans.caveats = [str(c) for c in (d.get("caveats") or [])]
    ans.disagreement = str(d.get("disagreement") or "")
    ans.what_would_settle_it = str(d.get("what_would_settle_it") or "")
    ans.supporting_idx = [int(i) for i in (d.get("supporting_claims") or [])
                          if isinstance(i, (int, float))]
    return ans
