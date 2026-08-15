"""Provider adapters behind one seam.

Agents name a Role, never a model. Three reasons the indirection is
load-bearing rather than architectural politeness:

1. The event's model policy is ambiguous about proprietary APIs. If they turn
   out to be disallowed, the council goes all-local by editing one dict.
2. A heterogeneous council must swap providers per role trivially — the
   diversity claim depends on it.
3. Free tiers rate-limit rather than bill, so queuing, backoff, budget
   enforcement and failover all need exactly one place to live.
"""

from faultline.providers.base import (
    CompletionResult,
    Provider,
    ProviderError,
    QuotaExhausted,
    extract_json,
)

__all__ = [
    "CompletionResult",
    "Provider",
    "ProviderError",
    "QuotaExhausted",
    "extract_json",
]
