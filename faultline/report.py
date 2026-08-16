"""Render a run as a standalone disagreement map.

The map is the product, not a prose summary. Prose is generated FROM the
record and stays secondary, because the moment findings are narrated they
start averaging together — which is the failure this system exists to prevent.

Everything here is reconstructed from the SQLite store, so a report can be
regenerated for any past run without re-running the pipeline.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from faultline.store.db import Store

_VERDICT_STYLE = {
    "explained": ("#1a7f5a", "EXPLAINED"),
    "unresolved": ("#b3541e", "UNRESOLVED  →  research gap"),
    "not_a_conflict": ("#5a6270", "NOT A CONFLICT"),
}

CSS = """
:root{--bg:#fbfaf7;--fg:#1c1c1c;--mut:#6b6b6b;--line:#e2ded6;--card:#fff;--accent:#b3541e}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#14150f;--fg:#ece9e2;
 --mut:#9a978f;--line:#2c2d26;--card:#1c1d16;--accent:#e08a4e}}
:root[data-theme=dark]{--bg:#14150f;--fg:#ece9e2;--mut:#9a978f;--line:#2c2d26;--card:#1c1d16;--accent:#e08a4e}
*{box-sizing:border-box}
body{margin:0;padding:2rem 1.25rem 4rem;background:var(--bg);color:var(--fg);
 font:16px/1.6 Georgia,"Iowan Old Style",serif;max-width:60rem;margin-inline:auto}
h1{font-size:1.9rem;margin:0 0 .3rem;letter-spacing:-.01em}
h2{font-size:1.05rem;text-transform:uppercase;letter-spacing:.1em;color:var(--mut);
 margin:2.6rem 0 .9rem;font-weight:normal}
.q{color:var(--mut);font-style:italic;margin-bottom:1.4rem}
.funnel{display:flex;flex-wrap:wrap;gap:.5rem;margin:.5rem 0 0}
.step{background:var(--card);border:1px solid var(--line);border-radius:.4rem;
 padding:.5rem .8rem;font:13px/1.3 ui-monospace,monospace}
.step b{display:block;font-size:1.3rem;font-family:Georgia,serif}
.step span{color:var(--mut)}
.conflict{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--vc);
 border-radius:.4rem;padding:1rem 1.2rem;margin:1rem 0}
.verdict{font:12px/1 ui-monospace,monospace;letter-spacing:.08em;color:var(--vc);
 text-transform:uppercase;margin-bottom:.7rem}
.claim{padding:.5rem 0;border-top:1px dotted var(--line)}
.claim .meta{font:12px/1.5 ui-monospace,monospace;color:var(--mut)}
.dir{display:inline-block;padding:0 .4rem;border-radius:.2rem;font-weight:bold}
.dir.positive{background:#1a7f5a22;color:#1a7f5a}
.dir.negative{background:#a3282822;color:#a32828}
.dir.null{background:#5a627022;color:var(--mut)}
.dir.mixed{background:#b3541e22;color:var(--accent)}
.stance{font:13px/1.5 ui-monospace,monospace;padding:.35rem 0 .35rem .8rem;
 border-left:2px solid var(--line);margin:.35rem 0}
.lin{color:var(--accent);font-weight:bold}
.nocite{color:#a32828}
.reason{margin-top:.7rem;padding-top:.6rem;border-top:1px solid var(--line);font-size:.94rem}
.gap{background:var(--card);border:1px solid var(--accent);border-radius:.4rem;
 padding:1rem 1.2rem;margin:.9rem 0}
.gap .tag{font:11px/1 ui-monospace,monospace;letter-spacing:.08em;color:var(--accent);
 text-transform:uppercase}
table{border-collapse:collapse;width:100%;font-size:.9rem}
td,th{text-align:left;padding:.4rem .6rem;border-bottom:1px solid var(--line)}
th{color:var(--mut);font-weight:normal;font-size:.8rem;text-transform:uppercase;
 letter-spacing:.06em}
.note{color:var(--mut);font-size:.88rem;font-style:italic;margin-top:.6rem}
.empty{background:var(--card);border:1px dashed var(--line);border-radius:.4rem;
 padding:1.4rem;color:var(--mut)}
code{font:13px ui-monospace,monospace;background:var(--line);padding:.1rem .3rem;border-radius:.2rem}
"""


def _e(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _claim_html(c: dict, label: str) -> str:
    scope = c.get("scope_conditions_json") or "[]"
    try:
        scope = ", ".join(json.loads(scope)) if isinstance(scope, str) else ", ".join(scope)
    except Exception:
        scope = str(scope)
    d = _e(c.get("direction"))
    return f"""<div class="claim"><b>{label}</b> {_e(c.get('text'))}
      <div class="meta"><span class="dir {d}">{d}</span>
      &nbsp;{_e(c.get('magnitude') or 'magnitude not reported')}<br>
      {_e(c.get('population'))} &middot; {_e(c.get('outcome_measure'))}
      &middot; {_e(c.get('timepoint') or 'timepoint not reported')}<br>
      scope: {_e(scope) or 'none stated'}</div></div>"""


def render_run(store: Store, run_id: str) -> str:
    run = store.query("SELECT * FROM runs WHERE id=?", (run_id,))
    if not run:
        raise ValueError(f"no such run: {run_id}")
    run = run[0]
    ledger = json.loads(run["ledger_json"] or "{}")

    claims = {r["id"]: dict(r) for r in
              store.query("SELECT * FROM claims WHERE run_id=?", (run_id,))}
    conflicts = store.query("SELECT * FROM conflicts WHERE run_id=?", (run_id,))
    verdicts = {r["conflict_id"]: dict(r) for r in
                store.query("SELECT * FROM verdicts WHERE run_id=?", (run_id,))}
    explanations: dict[str, list[dict]] = {}
    for r in store.query("SELECT * FROM explanations WHERE run_id=?", (run_id,)):
        explanations.setdefault(r["conflict_id"], []).append(dict(r))
    gaps = store.query("SELECT * FROM gaps WHERE run_id=?", (run_id,))
    screened = store.query(
        "SELECT decision, COUNT(*) n FROM screening WHERE run_id=? GROUP BY decision",
        (run_id,))
    counts = {r["decision"]: r["n"] for r in screened}
    papers = sum(counts.values())

    parts: list[str] = [
        f"<h1>Faultline</h1><div class='q'>{_e(run['question'])}</div>",
        f"<div class='meta'>field: <b>{_e(run['field'] or 'uncalibrated')}</b> "
        f"&middot; run <code>{_e(run_id)}</code></div>",
        "<h2>Corpus</h2><div class='funnel'>",
        f"<div class='step'><b>{papers}</b><span>screened</span></div>",
        f"<div class='step'><b>{counts.get('include', 0)}</b><span>included</span></div>",
        f"<div class='step'><b>{counts.get('borderline', 0)}</b><span>borderline</span></div>",
        f"<div class='step'><b>{counts.get('exclude', 0)}</b><span>excluded</span></div>",
        f"<div class='step'><b>{len(claims)}</b><span>claims</span></div>",
        f"<div class='step'><b>{len(conflicts)}</b><span>conflicts</span></div>",
        "</div><div class='note'>Every exclusion carries a stated reason and is "
        "queryable in the trace — that is what makes the screen defensible.</div>",
        "<h2>Disagreement map</h2>",
    ]

    if not conflicts:
        parts.append(
            "<div class='empty'>No commensurable contradictions survived the "
            "commensurability contract.<br><br>That is a finding, not a failure: "
            "the retrieved studies did not disagree in a way that makes comparison "
            "legitimate. Reporting it honestly is the point — a smoothed summary "
            "would have invented agreement instead.</div>")

    for cf in conflicts:
        v = verdicts.get(cf["id"], {})
        colour, label = _VERDICT_STYLE.get(v.get("verdict", ""), ("#5a6270", "PENDING"))
        a, b = claims.get(cf["claim_a"], {}), claims.get(cf["claim_b"], {})
        parts.append(f"<div class='conflict' style='--vc:{colour}'>")
        parts.append(f"<div class='verdict'>{_e(cf['kind'])} &rarr; {label}</div>")
        parts.append(_claim_html(a, "A"))
        parts.append(_claim_html(b, "B"))
        if cf["agreement"] is not None and float(cf["agreement"]) < 1.0:
            parts.append("<div class='note'>Assessors from different lineages "
                         "disagreed on whether these are comparable; a third "
                         "lineage ruled.</div>")
        for e in explanations.get(cf["id"], []):
            cited = e["cited_attributes_json"] or "[]"
            try:
                cited_list = json.loads(cited) if isinstance(cited, str) else cited
            except Exception:
                cited_list = []
            tail = ("<span class='nocite'>cites no concrete attribute</span>"
                    if not cited_list else _e("; ".join(map(str, cited_list))[:120]))
            parts.append(
                f"<div class='stance'><span class='lin'>{_e(e['lineage'])}</span> "
                f"&middot; {_e(e['stance'])} &middot; p={float(e['confidence'] or 0):.2f}<br>"
                f"{_e(e['argument'])}<br><small>{tail}</small></div>")
        if v:
            win = f"<b>{_e(v.get('winning_stance'))}</b> &mdash; " if v.get("winning_stance") else ""
            parts.append(f"<div class='reason'>{win}{_e(v.get('reasoning'))}</div>")
        parts.append("</div>")

    if gaps:
        parts.append("<h2>Research gaps</h2>"
                     "<div class='note'>A gap is an unresolved disagreement: the "
                     "adjudicator rejected every proposed explanation, so nothing "
                     "in the available study characteristics accounts for it.</div>")
        for g in gaps:
            parts.append(
                f"<div class='gap'><div class='tag'>{_e(g['bucket'])} &middot; "
                f"{_e(g['status'])}</div>{_e(g['proposition'])}"
                f"<div class='note'>{_e(g['rationale'])}</div></div>")

    by_lin = ledger.get("by_lineage", {})
    if by_lin:
        parts.append("<h2>Cost</h2><table><tr><th>lineage</th><th>calls</th>"
                     "<th>cached</th><th>tokens</th><th>failovers</th></tr>")
        for name, t in sorted(by_lin.items()):
            parts.append(
                f"<tr><td>{_e(name)}</td><td>{t.get('calls', 0)}</td>"
                f"<td>{t.get('cache_hits', 0)}</td>"
                f"<td>{t.get('tokens_in', 0) + t.get('tokens_out', 0):,}</td>"
                f"<td>{t.get('failovers', 0)}</td></tr>")
        parts.append("</table>")
        parts.append(
            f"<div class='note'>{ledger.get('local_calls', 0)} of "
            f"{ledger.get('total_calls', 0)} calls never touched a metered endpoint "
            f"({ledger.get('local_share', 0):.0%}); cache hit rate "
            f"{ledger.get('cache_hit_rate', 0):.0%}. Genuine multi-model inference "
            f"across {len(by_lin)} lineages — not a deterministic pipeline.</div>")

    return (f"<title>Faultline — {_e(run['question'])[:60]}</title>"
            f"<style>{CSS}</style>" + "\n".join(parts))


def write_report(store: Store, run_id: str, path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_run(store, run_id), encoding="utf-8")
    return out


def latest_run_id(store: Store) -> str | None:
    rows = store.query(
        "SELECT id FROM runs WHERE finished_at IS NOT NULL "
        "ORDER BY started_at DESC LIMIT 1")
    return rows[0]["id"] if rows else None
