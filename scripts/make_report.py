"""Render a run as a standalone disagreement map.

    python scripts/make_report.py              # most recent run
    python scripts/make_report.py run_abc123
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from faultline.util import setup_console

setup_console()

from faultline.report import latest_run_id, write_report
from faultline.store.db import Store


def main() -> int:
    store = Store()
    run_id = sys.argv[1] if len(sys.argv) > 1 else latest_run_id(store)
    if not run_id:
        print("no completed runs found — run scripts/run_faultline.py first")
        return 1
    out = write_report(store, run_id, f"reports/{run_id}.html")
    print(f"wrote {out}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
