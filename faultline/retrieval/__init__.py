"""Systematic retrieval — the precondition for everything downstream.

You cannot detect a contradiction between studies you never retrieved. Missing
half a literature does not yield a partial answer; it yields a confident FALSE
CONSENSUS, which is the exact failure this system exists to prevent.

That is why retrieval reports a denominator. An LLM asked the same question
returns eight papers and no idea how many it missed. Here every stage is
counted, and the counts are part of the output rather than a diagnostic.
"""

from faultline.retrieval.models import Paper, RetrievalReport
from faultline.retrieval.openalex import OpenAlexClient

__all__ = ["OpenAlexClient", "Paper", "RetrievalReport"]
