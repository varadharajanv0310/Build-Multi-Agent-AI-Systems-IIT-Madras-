"""Paper mode — hand it a paper, get that paper positioned in its literature.

Question mode asks "where does this field disagree?". Paper mode asks the
sharper question a researcher actually has: **is my finding corroborated,
contradicted, or standing alone?**

Mechanically it is question mode with the question DERIVED from the paper's own
claims, plus a final positioning step. Same council, same evaluation, very
different product — and the one you can point at a draft before you submit it.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from faultline.config import SETTINGS, Role
from faultline.retrieval.models import Paper
from faultline.retrieval.openalex import OpenAlexClient
from faultline.router import Router

QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "population": {"type": "string"},
        "intervention": {"type": "string"},
        "outcome": {"type": "string"},
        "is_testable": {"type": "boolean"},
    },
    "required": ["question", "is_testable"],
}

QUESTION_SYSTEM = """A paper makes a claim. Recover the research question that \
claim is an answer to.

The question must be one OTHER studies could also have answered, so that the \
claim can be checked against them. Strip anything specific to this paper - its \
cohort name, its acronyms, its sample - and keep the underlying relationship.

Good:  "Does vitamin D supplementation reduce respiratory infection incidence?"
Bad:   "What did the VIDARIS trial find?"  (only this paper can answer that)

Set is_testable to false if the claim is definitional, methodological, or a \
statement about the paper itself rather than an empirical finding about the \
world."""

POSITION_SCHEMA = {
    "type": "object",
    "properties": {
        "position": {
            "type": "string",
            "enum": ["corroborated", "contradicted", "mixed", "isolated",
                     "unverifiable"],
        },
        "supporting": {"type": "integer"},
        "conflicting": {"type": "integer"},
        "assessment": {"type": "string"},
        "strength_warning": {"type": "string"},
    },
    "required": ["position", "assessment"],
}

POSITION_SYSTEM = """Position one paper's claim against the findings retrieved \
from its literature.

- "corroborated"  - independent studies report the same direction on a
                    comparable construct
- "contradicted"  - independent studies report the opposite, or a null result
                    where this paper reports an effect
- "mixed"         - the literature genuinely splits
- "isolated"      - nothing comparable was found. This is NOT support. An
                    unreplicated claim standing alone is a real and reportable
                    state, and saying so is more useful than implying agreement.
- "unverifiable"  - the retrieved evidence cannot speak to this claim

Count supporting and conflicting findings honestly.

strength_warning is where you flag OVERSTATEMENT: the paper asserting more than \
its own evidence carries, or more than the surrounding literature supports - a \
subgroup result stated generally, a hedge dropped, a narrow population \
described broadly. Leave it empty if there is none. Do not invent one."""


@dataclass
class ClaimPosition:
    claim: dict
    question: str
    position: str = "unverifiable"
    supporting: int = 0
    conflicting: int = 0
    assessment: str = ""
    strength_warning: str = ""
    comparable_claims: list[dict] = field(default_factory=list)


def load_paper(source: str) -> Paper:
    """Accept a DOI, an arXiv id, a local text/PDF file, or raw pasted text."""
    src = source.strip()

    # local file
    path = Path(src)
    if path.exists() and path.is_file():
        if path.suffix.lower() == ".pdf":
            text = _read_pdf(path)
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
        return Paper(id=f"local:{path.name}", title=_guess_title(text) or path.stem,
                     abstract=text[:20000], fulltext=text,
                     fulltext_source="local_file", source="local")

    # DOI
    if src.lower().startswith(("10.", "doi:", "https://doi.org/")):
        doi = re.sub(r"^(doi:|https://doi\.org/)", "", src, flags=re.I)
        client = OpenAlexClient()
        paper = client.by_doi(doi)
        client.close()
        if paper is None:
            raise ValueError(f"DOI not found in OpenAlex: {doi}")
        return paper

    # arXiv
    if m := re.match(r"^(?:arxiv:)?(\d{4}\.\d{4,5})(v\d+)?$", src, re.I):
        return _from_arxiv(m.group(1))

    # raw text pasted on the command line
    if len(src) > 200:
        return Paper(id="pasted", title="pasted text", abstract=src[:20000],
                     fulltext=src, fulltext_source="pasted", source="pasted")

    # last resort: treat as a title and look it up
    client = OpenAlexClient()
    hits = list(client.search(src, limit=1))
    client.close()
    if hits:
        return hits[0]
    raise ValueError(
        f"could not resolve {src!r} — pass a DOI, an arXiv id, a file path, "
        "or paste the abstract text")


_SKIP_LINE = ("abstract", "http", "doi:", "arxiv:", "keywords", "index terms",
              "anonymous author", "manuscript", "preprint", "submitted to",
              "ieee transactions", "under review", "conference on")


def _guess_title(text: str) -> str:
    """The title, which a typesetter will have wrapped across two or three lines.

    Taking only the first line gave "SEVA: Lightweight, LLM-Free Detection of"
    — a sentence cut mid-phrase, shown as the heading of someone's own paper.
    Titles are joined until the line stops looking like a continuation.

    Showing a user 'faultline_upload' as the title of their own paper is a
    small thing that makes the whole tool feel broken."""
    lines = []
    for raw in (text or "").splitlines():
        line = " ".join(raw.split())
        if not line:
            if lines:
                break
            continue
        low = line.lower()
        if low.startswith(_SKIP_LINE):
            if lines:
                break
            continue
        # A bare page number or figure marker above the title is noise.
        if len(line) < 15 and not lines:
            continue
        if len(line) > 250:
            break
        lines.append(line)
        joined = " ".join(lines)
        # A title that ends on terminal punctuation, or has run long enough,
        # is complete. Continuations end mid-phrase ("... Detection of").
        if len(joined) > 40 and line[-1] not in ",-–—:;" and not _looks_partial(line):
            break
        if len(joined) > 220:
            break
    return " ".join(lines)[:250]


_PARTIAL_TAIL = ("of", "for", "in", "the", "a", "an", "and", "or", "with",
                 "to", "on", "from", "via", "under", "using", "against")


def _looks_partial(line: str) -> bool:
    """True when a line clearly continues onto the next one."""
    last = line.rstrip().split()[-1].lower().strip(":,;") if line.split() else ""
    return last in _PARTIAL_TAIL


# PDF text extraction splits letters whose glyphs were kerned apart, so "SEVA"
# arrives as "SEV A" and appears that way in the title, every extracted claim
# and every objection quoting it. Repairing it here fixes all of them at once.
_LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
              "ﬃ": "ffi", "ﬄ": "ffl", "‑": "-"}


def _repair_pdf_text(text: str) -> str:
    for bad, good in _LIGATURES.items():
        text = text.replace(bad, good)
    # An ALLCAPS name split by kerning ("SEV A") is rejoined only on evidence,
    # because the bare pattern would turn "NATO A team" into "NATOA". Two
    # things count as evidence: the joined form appearing elsewhere in the
    # document, or the same split repeating often enough to be systematic.
    # A kerned name breaks on every occurrence — 52 times in the paper this
    # was written for — whereas a real phrase does not repeat identically.
    counts = Counter(m.group(0) for m in
                     re.finditer(r"\b([A-Z]{3,}) ([A-Z])\b(?![A-Za-z])", text))
    for split, n in counts.items():
        joined = split.replace(" ", "")
        if n >= 5 or re.search(rf"\b{re.escape(joined)}\b", text, re.I):
            text = re.sub(rf"\b{re.escape(split)}\b(?![A-Za-z])", joined, text)
    # Hyphenation across a line break: "detec-\ntion" -> "detection".
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    return text


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise RuntimeError(
            "PDF input needs pypdf — run: pip install pypdf") from e
    reader = PdfReader(str(path))
    return _repair_pdf_text(
        "\n".join((p.extract_text() or "") for p in reader.pages))


def _from_arxiv(arxiv_id: str) -> Paper:
    r = httpx.get("https://export.arxiv.org/api/query",
                  params={"id_list": arxiv_id, "max_results": 1},
                  headers={"User-Agent": SETTINGS.user_agent}, timeout=60)
    r.raise_for_status()
    body = r.text
    title = re.search(r"<title>(.*?)</title>", body, re.S)
    summary = re.search(r"<summary>(.*?)</summary>", body, re.S)
    titles = re.findall(r"<title>(.*?)</title>", body, re.S)
    return Paper(
        id=f"arxiv:{arxiv_id}",
        title=" ".join((titles[1] if len(titles) > 1 else (title.group(1) if title else "")).split()),
        abstract=" ".join(summary.group(1).split()) if summary else None,
        arxiv_id=arxiv_id, source="arxiv", fulltext_source="abstract_only")


def derive_question(router: Router, claim: dict, paper_title: str) -> dict:
    """Recover the general research question a claim answers."""
    body = (
        f"PAPER: {paper_title}\n\n"
        f"CLAIM: {claim.get('text')}\n"
        f"  population: {claim.get('population')}\n"
        f"  intervention/exposure: {claim.get('design') or 'not stated'}\n"
        f"  outcome: {claim.get('outcome_measure')}\n\n"
        "What research question is this claim an answer to?"
    )
    res = router.complete(
        Role.CALIBRATION,
        [{"role": "system", "content": QUESTION_SYSTEM},
         {"role": "user", "content": body}],
        QUESTION_SCHEMA, stage="question_derivation", subject_id=claim.get("id"))
    return res.data


def position_claim(router: Router, claim: dict, question: str,
                   literature: list[dict]) -> ClaimPosition:
    """Place one of the paper's claims against what the literature found."""
    pos = ClaimPosition(claim=claim, question=question,
                        comparable_claims=literature)
    if not literature:
        pos.position = "isolated"
        pos.assessment = ("No comparable findings were retrieved. The claim "
                          "stands alone in this corpus — which is not the same "
                          "as being supported by it.")
        return pos

    lines = []
    for c in literature[:12]:
        lines.append(
            f"- [{c.get('direction')}] {c.get('text', '')[:180]}\n"
            f"    {c.get('population')} | {c.get('outcome_measure')} | "
            f"{c.get('magnitude') or 'magnitude not reported'}")

    body = (
        f"RESEARCH QUESTION\n{question}\n\n"
        f"THE PAPER'S CLAIM\n{claim.get('text')}\n"
        f"  direction: {claim.get('direction')}\n"
        f"  magnitude: {claim.get('magnitude') or 'not reported'}\n"
        f"  population: {claim.get('population')}\n"
        f"  scope: {claim.get('scope_conditions_json')}\n"
        f"  author hedges: {claim.get('hedges_json')}\n\n"
        f"FINDINGS RETRIEVED FROM THE LITERATURE ({len(literature)})\n"
        + "\n".join(lines) +
        "\n\nPosition the paper's claim against these findings."
    )
    res = router.complete(
        Role.ADJUDICATION,
        [{"role": "system", "content": POSITION_SYSTEM},
         {"role": "user", "content": body}],
        POSITION_SCHEMA, stage="positioning", subject_id=claim.get("id"))

    pos.position = res.data.get("position", "unverifiable")
    pos.supporting = int(res.data.get("supporting") or 0)
    pos.conflicting = int(res.data.get("conflicting") or 0)
    pos.assessment = str(res.data.get("assessment", ""))
    pos.strength_warning = str(res.data.get("strength_warning") or "")
    return pos
