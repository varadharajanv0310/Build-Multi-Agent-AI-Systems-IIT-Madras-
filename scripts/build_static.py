"""Build a fully static public demo into dist/.

The public demo replays recorded runs, and a replay is a stage list with
timestamps — no Python required. This emits a directory any static host will
serve: Cloudflare Pages, GitHub Pages, Netlify. No server, no cold start,
no keys to leak and no quota to exhaust.

The pages themselves are unchanged. A fetch shim (web/static-shim.js) answers
the /api/ routes from local JSON, so the poller and the autopilot run exactly
the code they run against the real server.

    python scripts/build_static.py
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from faultline.config import PROJECT_ROOT, ROSTER, lineages_in_play  # noqa: E402
from faultline.util import setup_console  # noqa: E402

WEB = PROJECT_ROOT / "web"
DEMO = PROJECT_ROOT / "demo"
DIST = PROJECT_ROOT / "dist"

PAGES = {"landing.html": "index.html", "ask.html": "ask.html",
         "review.html": "review.html"}
ASSETS = ["style.css", "common.js", "ask.js", "review.js", "autopilot.js",
          "static-shim.js"]


def main() -> int:
    setup_console()
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()

    for asset in ASSETS:
        shutil.copy2(WEB / asset, DIST / asset)

    # Absolute asset paths would break on a project subpath; the shim must
    # also load before common.js so it is in place for the first fetch.
    for src, dst in PAGES.items():
        html = (WEB / src).read_text(encoding="utf-8")
        html = html.replace('href="/style.css"', 'href="style.css"')
        html = html.replace('src="/common.js"',
                            'src="static-shim.js"></script>\n<script src="common.js"')
        for js in ("ask.js", "review.js", "autopilot.js"):
            html = html.replace(f'src="/{js}"', f'src="{js}"')
        # Static hosts serve /ask as a file, not a route.
        html = html.replace('href="/ask"', 'href="ask.html"')
        html = html.replace('href="/review"', 'href="review.html"')
        html = html.replace('href="/"', 'href="index.html"')
        (DIST / dst).write_text(html, encoding="utf-8")

    # Page-to-page navigation inside the autopilot uses server routes; on a
    # static host those are files.
    ap = (DIST / "autopilot.js").read_text(encoding="utf-8")
    ap = ap.replace('const go = (path, at) =>\n    (location.href = `${path}?autopilot=1&t=${at}&speed=${SPEED}&lead=0`);',
                    'const go = (path, at) => {\n'
                    '    // Static hosts serve pages as files, not routes.\n'
                    '    const f = { "/": "index.html", "/review": "review.html",\n'
                    '                "/ask": "ask.html" }[path] || path;\n'
                    '    location.href = `${f}?autopilot=1&t=${at}&speed=${SPEED}&lead=0`;\n'
                    '  };')
    ap = ap.replace('if (page === "/" || page.endsWith("landing.html"))',
                    'if (page === "/" || page.endsWith("index.html") || page.endsWith("landing.html"))')
    ap = ap.replace('(page === "/review" ? "seva" : "question")',
                    '(page.includes("review") ? "seva" : "question")')
    ap = ap.replace('page === "/" ? LEAD', 'IS_LANDING ? LEAD')
    ap = ap.replace('const page = location.pathname;',
                    'const page = location.pathname;\n'
                    '  const IS_LANDING = page === "/" || page.endsWith("index.html")\n'
                    '                     || page.endsWith("landing.html");')
    (DIST / "autopilot.js").write_text(ap, encoding="utf-8")

    # Recorded runs, plus an index the demo listing reads.
    (DIST / "demo").mkdir()
    index = []
    for p in sorted(DEMO.glob("*.json")):
        shutil.copy2(p, DIST / "demo" / p.name)
        d = json.loads(p.read_text(encoding="utf-8"))
        index.append({"name": d.get("name", p.stem), "kind": d.get("kind", ""),
                      "label": d.get("label", ""), "subject": d.get("subject", ""),
                      "recordedAt": d.get("recordedAt", ""),
                      "elapsed": d.get("elapsed", 0), "runId": d.get("runId", "")})
    (DIST / "demo" / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")

    # The landing page builds its lineage chips from this, so the static build
    # captures the real roster rather than hardcoding a number.
    (DIST / "status.json").write_text(json.dumps({
        "lineages": sorted(l.value for l in lineages_in_play()),
        "roster": {r.value: f"{s.provider}/{s.model_id}" for r, s in ROSTER.items()},
        "lineageByRole": {r.value: s.lineage.value for r, s in ROSTER.items()},
        "publicDemo": True,
    }, indent=2), encoding="utf-8")

    total = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file())
    print(f"dist/  {len(list(DIST.rglob('*')))} files, {total/1024:.0f} KB")
    for f in sorted(DIST.rglob("*")):
        if f.is_file():
            print(f"   {f.relative_to(DIST).as_posix():28s} {f.stat().st_size/1024:7.1f} KB")
    print(f"\nrecorded runs: {', '.join(i['name'] for i in index) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
