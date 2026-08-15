"""Small shared utilities."""
from __future__ import annotations

import sys


def setup_console() -> None:
    """Force UTF-8 on stdout/stderr.

    Real paper text and model output routinely contain non-breaking hyphens,
    en dashes, Greek letters and typographic quotes. On Windows the console
    defaults to cp1252, which raises UnicodeEncodeError on all of them — so a
    successful analysis can still die while printing its own results.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def clip(value: object, n: int = 70) -> str:
    """Truncate anything to a printable width without exploding on None."""
    s = "" if value is None else str(value)
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"
