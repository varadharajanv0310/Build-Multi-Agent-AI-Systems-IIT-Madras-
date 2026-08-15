"""LangGraph orchestration of the council.

The pipeline is genuinely a state graph rather than a chain, which is why this
is not a wrapper for its own sake. Two edges make the difference:

  adjudicate -> retrieve   the adjudicator can rule that the corpus is too
                           thin to decide, sending the graph back to widen
                           retrieval with terms discovered during analysis
  conflicts  -> END        no commensurable contradictions is a legitimate
                           terminal state, not a failure

A linear pipeline cannot express either. Control flow here is discovered at
runtime from what the evidence turns out to be, which is the structural
argument for agents over a prompt chain.
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph

from faultline.agents.council import (
    adjudicate, assess_commensurability, candidate_pairs, classify_gap,
    detect_conflicts, run_panel)
from faultline.agents.extraction import extract_claims, usable_for_conflict
from faultline.agents.framing import (
    calibrate_field, contract_text, criteria_text, frame_question)
from faultline.retrieval.models import RetrievalReport
from faultline.retrieval.openalex import OpenAlexClient, dedupe
from faultline.screening import screen_corpus


def _keep(a, b):
    return b if b is not None else a


class FaultlineState(TypedDict, total=False):
    question: str
    router: Any
    store: Any
    run_id: str
    per_query: int
    from_year: int
    max_extract: int
    max_pairs: int
    max_conflicts: int

    calibration: dict
    spec: dict
    report: Any
    papers: list
    included: list
    borderline: list
    claims: list
    usable: list
    pairs: list
    conflicts: list
    verdicts: Annotated[list, _keep]
    gaps: Annotated[list, _keep]

    widened: bool          # has retrieval already been re-run once?
    extra_terms: list
    log: list


def _log(state: FaultlineState, msg: str) -> list:
    print(f"      {msg}")
    return [*state.get("log", []), msg]


# --- nodes -------------------------------------------------------------------

def node_calibrate(state: FaultlineState) -> dict:
    cal = calibrate_field(state["router"], state["question"])
    return {"calibration": cal,
            "log": _log(state, f"field: {cal.get('field')}")}


def node_frame(state: FaultlineState) -> dict:
    spec = frame_question(state["router"], state["question"], state["calibration"])
    return {"spec": spec,
            "log": _log(state, f"{len(spec.get('search_queries', []))} queries, "
                               f"contract on "
                               f"{len(spec.get('commensurability_must_match', []))} dimensions")}


def node_retrieve(state: FaultlineState) -> dict:
    queries = list(state["spec"].get("search_queries") or [state["question"]])
    queries += state.get("extra_terms") or []
    client = OpenAlexClient()
    report = state.get("report") or RetrievalReport(databases=["openalex"])
    report.query_strings = queries
    papers = list(state.get("papers") or [])
    for q in queries[:8]:
        try:
            papers.extend(client.search(q, limit=state["per_query"],
                                        from_year=state["from_year"]))
        except Exception:
            continue
    client.close()
    report.raw_hits = len(papers)
    papers = dedupe(papers)
    report.after_dedup = len(papers)
    return {"papers": papers, "report": report,
            "log": _log(state, f"{report.raw_hits} raw -> {len(papers)} unique")}


def node_screen(state: FaultlineState) -> dict:
    included, borderline, _ = screen_corpus(
        state["router"], state["store"], state["run_id"], state["papers"],
        criteria_text(state["spec"]), state["report"])
    return {"included": included, "borderline": borderline,
            "log": _log(state, f"included {len(included)}, borderline {len(borderline)}")}


def node_extract(state: FaultlineState) -> dict:
    targets = (state["included"] + state["borderline"])[:state["max_extract"]]
    claims = extract_claims(state["router"], state["store"], state["run_id"],
                            targets, state["question"])
    usable = [c for c in claims if usable_for_conflict(c)]
    return {"claims": claims, "usable": usable,
            "log": _log(state, f"{len(claims)} claims, {len(usable)} usable")}


def node_commensurability(state: FaultlineState) -> dict:
    pairs = assess_commensurability(
        state["router"], state["store"], state["run_id"],
        candidate_pairs(state["usable"], state["max_pairs"]),
        contract_text(state["spec"]))
    splits = sum(1 for p in pairs if p.lineage_agreement is False)
    return {"pairs": pairs,
            "log": _log(state, f"{len(pairs)} pairs, {splits} lineage disagreements")}


def node_conflicts(state: FaultlineState) -> dict:
    conflicts = detect_conflicts(state["store"], state["run_id"], state["pairs"])
    conflicts = conflicts[:state["max_conflicts"]]
    return {"conflicts": conflicts,
            "log": _log(state, f"{len(conflicts)} genuine conflicts")}


def node_council(state: FaultlineState) -> dict:
    verdicts, gaps = [], []
    for conflict in state["conflicts"]:
        explanations = run_panel(state["router"], state["store"], state["run_id"], conflict)
        verdict = adjudicate(state["router"], state["store"], state["run_id"],
                             conflict, explanations)
        verdict["conflict"] = conflict
        verdict["explanations"] = explanations
        verdicts.append(verdict)
        if gap := classify_gap(state["router"], state["store"], state["run_id"],
                               conflict, verdict):
            gap["conflict"] = conflict
            gaps.append(gap)
    unresolved = sum(1 for v in verdicts if v["verdict"] == "unresolved")
    return {"verdicts": verdicts, "gaps": gaps,
            "log": _log(state, f"{len(verdicts)} adjudicated, {unresolved} unresolved, "
                               f"{len(gaps)} gaps")}


# --- conditional edges -------------------------------------------------------

def after_conflicts(state: FaultlineState) -> str:
    """The backward edge.

    Too few claims to compare usually means retrieval was too narrow, not that
    the literature agrees. Widening once with terminology the field calibration
    surfaced is the difference between 'no conflict found' and 'no conflict
    exists' — and conflating those two is exactly how a false consensus is
    manufactured.
    """
    if state.get("conflicts"):
        return "council"
    if not state.get("widened") and len(state.get("usable", [])) < 4:
        return "widen"
    return END


def node_widen(state: FaultlineState) -> dict:
    """Re-search using terminology variants discovered during calibration."""
    variants = (state.get("calibration", {}).get("terminology_variants") or [])[:4]
    return {"widened": True, "extra_terms": variants,
            "log": _log(state, f"corpus too thin; widening with {len(variants)} "
                               "terminology variants from field calibration")}


def build_graph():
    g = StateGraph(FaultlineState)
    g.add_node("calibrate", node_calibrate)
    g.add_node("frame", node_frame)
    g.add_node("retrieve", node_retrieve)
    g.add_node("screen", node_screen)
    g.add_node("extract", node_extract)
    g.add_node("commensurability", node_commensurability)
    g.add_node("conflicts", node_conflicts)
    g.add_node("widen", node_widen)
    g.add_node("council", node_council)

    g.set_entry_point("calibrate")
    g.add_edge("calibrate", "frame")
    g.add_edge("frame", "retrieve")
    g.add_edge("retrieve", "screen")
    g.add_edge("screen", "extract")
    g.add_edge("extract", "commensurability")
    g.add_edge("commensurability", "conflicts")
    g.add_conditional_edges("conflicts", after_conflicts,
                            {"council": "council", "widen": "widen", END: END})
    g.add_edge("widen", "retrieve")      # the backward edge
    g.add_edge("council", END)
    return g.compile()
