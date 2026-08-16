"""Faultline — web interface.

    streamlit run app.py
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from faultline import modes
from faultline.config import ROSTER, lineages_in_play
from faultline.store.db import Store

st.set_page_config(page_title="Faultline", page_icon="🔍", layout="wide")

CONF_COLOUR = {"high": "green", "moderate": "orange", "low": "red",
               "insufficient_evidence": "red"}
SEV_COLOUR = {"fatal": "red", "major": "orange", "minor": "gray"}


@st.cache_resource
def get_store() -> Store:
    return Store()


def sidebar() -> dict:
    with st.sidebar:
        st.markdown("### Faultline")
        st.caption("Literature review and synthesis, run by a council of "
                   "models on different training lineages.")
        st.markdown("---")
        breadth = st.slider("Papers per search query", 4, 30, 10,
                            help="More papers means better coverage and a slower run.")
        from_year = st.number_input("Published since", 1950, 2026, 2000)
        st.markdown("---")
        st.caption(f"**{len(lineages_in_play())} model lineages**")
        for role, spec in ROSTER.items():
            st.caption(f"`{role.value}` → {spec.lineage.value}")
    return {"per_query": int(breadth), "from_year": int(from_year)}


def render_answer(res) -> None:
    if res.error:
        st.error(res.error)
        return
    a = res.answer
    if a is None:
        st.warning("No answer was produced.")
        return

    st.markdown(f"## {a.headline}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Confidence", a.confidence.replace("_", " "))
    c2.metric("Consensus", a.consensus.replace("_", " "))
    c3.metric("Findings used", len(a.evidence))

    if a.confidence == "insufficient_evidence":
        st.warning("The retrieved evidence does not settle this question. "
                   "That is reported rather than papered over with a "
                   "confident-sounding answer.")

    if a.answer:
        st.markdown(a.answer)

    if a.caveats:
        st.markdown("#### It depends on")
        for c in a.caveats:
            st.markdown(f"- {c}")

    if a.disagreement:
        st.markdown("#### Where the studies disagree")
        st.info(a.disagreement)

    if a.what_would_settle_it:
        st.markdown("#### What would settle it")
        st.markdown(a.what_would_settle_it)

    with st.expander(f"Evidence — {len(a.evidence)} findings, all traceable"):
        for i, c in enumerate(a.evidence, 1):
            st.markdown(
                f"**[{i}]** {c.get('text', '')}  \n"
                f"<small>`{c.get('direction')}` · "
                f"{c.get('magnitude') or 'magnitude not reported'} · "
                f"{c.get('population')} · {c.get('outcome_measure')}</small>",
                unsafe_allow_html=True)

    with st.expander("How this corpus was built"):
        r = res.report
        st.markdown(
            f"- databases: **{', '.join(r.databases)}**\n"
            f"- retrieved **{r.raw_hits}** → **{r.after_dedup}** unique\n"
            f"- screened **{r.screened}**, included **{r.included}**, "
            f"borderline **{r.borderline}**, excluded **{r.excluded}**\n"
            f"- field: **{res.calibration.get('field', 'uncalibrated')}**")
        st.caption("The denominator is the point. A chat model gives you a "
                   "handful of papers and no idea what it missed.")


def render_review(res) -> None:
    if res.error and not res.review.claims:
        st.error(res.error)
        return

    rv = res.review
    st.markdown(f"## {rv.paper_title}")

    fatal, major = rv.fatal, rv.major
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Your claims", len(rv.claims))
    c2.metric("Literature found", len(rv.literature))
    c3.metric("Fatal objections", len(fatal))
    c4.metric("Major objections", len(major))

    if fatal:
        st.error(f"{len(fatal)} objection(s) a referee would treat as fatal. "
                 "Fix these before submitting.")

    pos = rv.positioning or {}
    if pos:
        st.markdown("### Where your contribution sits")
        risk = pos.get("novelty_risk", "unclear")
        colour = {"defensible": "green", "weak": "orange",
                  "already_done": "red"}.get(risk, "gray")
        st.markdown(f"**Novelty:** :{colour}[{risk.replace('_', ' ')}]")
        if pos.get("placement"):
            st.markdown(pos["placement"])
        if pos.get("novelty_claim"):
            st.markdown("**Draft novelty sentence**")
            st.code(pos["novelty_claim"], language=None)
        if pos.get("collapse_risk"):
            st.warning(f"**Risk of being dismissed as:** {pos['collapse_risk']}")
        if pos.get("must_cite"):
            st.markdown("**Must cite** — a referee would notice these missing")
            for m in pos["must_cite"]:
                st.markdown(f"- {m}")

    if rv.objections:
        st.markdown("### Reviewer panel")
        st.caption("Three reviewers with different priors, each running on a "
                   "different model lineage. Same prompt on one model would "
                   "give you three versions of one blind spot.")
        for name in ["R1 — framing", "R2 — method", "R3 — significance"]:
            items = [o for o in rv.objections if o.reviewer == name]
            if not items:
                continue
            with st.expander(f"{name}  ({items[0].lineage})", expanded=True):
                for o in items:
                    st.markdown(
                        f":{SEV_COLOUR.get(o.severity, 'gray')}[**{o.severity.upper()}**] "
                        f"{o.objection}")
                    if o.minimum_fix:
                        st.caption(f"Minimum fix: {o.minimum_fix}")
                    st.markdown("")

    ap = rv.appraisal or {}
    if ap:
        st.markdown("### The evidence base your paper sits in")
        st.markdown(f"**Quality:** `{ap.get('evidence_base', 'unknown')}`")
        if ap.get("assessment"):
            st.markdown(ap["assessment"])
        if ap.get("systemic_issues"):
            for s in ap["systemic_issues"]:
                st.markdown(f"- {s}")
        if ap.get("construct_validity"):
            st.info(f"**Construct validity:** {ap['construct_validity']}")

    if rv.claims:
        with st.expander(f"Your claims as extracted ({len(rv.claims)})"):
            for c in rv.claims:
                st.markdown(
                    f"- {c.get('text', '')}  \n"
                    f"<small>`{c.get('direction')}` · {c.get('population')} · "
                    f"scope: {c.get('scope_conditions_json')}</small>",
                    unsafe_allow_html=True)


# --- page ---------------------------------------------------------------------

st.title("Faultline")
st.caption("Ask a question and get an answer from the papers — or hand over "
           "your own paper and have a council of models review it before a "
           "referee does.")

cfg = sidebar()
tab_q, tab_p = st.tabs(["Ask a question", "Review my paper"])

with tab_q:
    question = st.text_input(
        "Your research question",
        placeholder="How many mg of magnesium is recommended daily?")
    if st.button("Answer it", type="primary", disabled=not question):
        box = st.status("Working…", expanded=True)
        res = modes.answer_question(question, store=get_store(),
                                    log=lambda m: box.write(m), **cfg)
        box.update(label="Done", state="complete", expanded=False)
        render_answer(res)
        if res.ledger:
            st.caption(f"{res.ledger.total_calls} model calls · "
                       f"{res.ledger.local_share:.0%} run locally · $0.00")

with tab_p:
    st.markdown("Upload a PDF, paste your text, or give a DOI / arXiv id.")
    up = st.file_uploader("PDF or text file", type=["pdf", "txt", "md"])
    pasted = st.text_area("…or paste your abstract / paper", height=180)
    ident = st.text_input("…or a DOI / arXiv id", placeholder="10.1136/bmj.i6583")

    if st.button("Review it", type="primary",
                 disabled=not (up or pasted.strip() or ident.strip())):
        source = ""
        if up is not None:
            suffix = Path(up.name).suffix or ".txt"
            tmp = Path(tempfile.gettempdir()) / f"faultline_upload{suffix}"
            tmp.write_bytes(up.getvalue())
            source = str(tmp)
        elif pasted.strip():
            source = pasted.strip()
        else:
            source = ident.strip()

        box = st.status("Working…", expanded=True)
        res = modes.review_paper(source, store=get_store(),
                                 log=lambda m: box.write(m), **cfg)
        box.update(label="Done", state="complete", expanded=False)
        render_review(res)
        if res.ledger:
            st.caption(f"{res.ledger.total_calls} model calls · "
                       f"{res.ledger.local_share:.0%} run locally · $0.00")
