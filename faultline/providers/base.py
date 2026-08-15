"""Provider contract and the JSON extraction that makes typed records possible.

Agents exchange typed records, never prose. If two models return
`{"comparable": false, "reason_code": "different_outcome_measure"}` we can
compare them mechanically and compute an agreement rate. If they return
paragraphs we would need a third model to compare them, losing the calibration
signal and reintroducing the fluency that hides errors.

Prose is a rendering of the record at the very end. Never the interchange.
"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from faultline.config import ModelSpec


class ProviderError(RuntimeError):
    """Provider failed in a way worth trying another model for."""


class QuotaExhausted(ProviderError):
    """Free-tier quota hit. Distinct from a transient error: retrying the same
    model will not help, so the router must fail over rather than back off."""


@dataclass
class CompletionResult:
    data: dict[str, Any]
    raw_text: str
    spec: ModelSpec
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    attempts: int = 1
    from_cache: bool = False
    repaired: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def model_id(self) -> str:
        return self.spec.model_id

    @property
    def lineage(self) -> str:
        return self.spec.lineage.value


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json(text: str) -> dict[str, Any]:
    """Recover a JSON object from model output.

    Needed because "structured output" means four different things across our
    providers, and reasoning models add a fifth failure mode by narrating
    before they answer. Tries, in order: whole string, fenced block, then the
    outermost balanced brace pair scanned with string-awareness so a `}` inside
    a quoted value does not truncate the object.
    """
    if not text or not text.strip():
        raise ProviderError("empty response body")

    candidates: list[str] = [text.strip()]

    for m in _FENCE.finditer(text):
        candidates.append(m.group(1).strip())

    balanced = _outermost_object(text)
    if balanced:
        candidates.append(balanced)

    for cand in candidates:
        if not cand.startswith("{"):
            continue
        try:
            parsed = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    raise ProviderError(f"no JSON object in response: {text[:220]!r}")


def _outermost_object(text: str) -> str | None:
    """Scan for a balanced {...}, ignoring braces inside string literals.

    A naive find('{')/rfind('}') breaks on values that contain braces — which
    quoted evidence spans from papers routinely do.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def missing_required(obj: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    return [k for k in schema.get("required", []) if k not in obj]


def confidence(value: Any, default: float = 0.5) -> float:
    """Coerce a model's confidence onto 0..1.

    Models answer "confidence" on whatever scale they feel like: 0.85, 85, or
    9 out of 10 all show up, and observed panel output mixed all three in one
    run. Left raw, a 85.0 would outrank every properly-scaled 0.9 and quietly
    invert the ranking the adjudicator depends on.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v or v in (float("inf"), float("-inf")):  # NaN / inf
        return default
    if v < 0:
        return 0.0
    if v <= 1.0:
        return v
    if v <= 10.0:      # "9 out of 10"
        return v / 10.0
    if v <= 100.0:     # "85 percent"
        return v / 100.0
    return 1.0


class Provider(ABC):
    """One provider. Knows how to ask for a typed record and how to read the
    answer back; knows nothing about roles, budgets, or failover."""

    name: str

    @abstractmethod
    def complete(
        self,
        spec: ModelSpec,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        max_tokens: int | None = None,
    ) -> CompletionResult:
        """Return a validated typed record, or raise ProviderError."""

    @staticmethod
    def schema_instruction(schema: dict[str, Any]) -> str:
        """Appended for models without server-side schema enforcement, and kept
        even for those that have it — belt and braces costs a few tokens and
        removes a whole class of parse failure."""
        return (
            "\n\nRespond with a single JSON object and nothing else. "
            "No prose before or after, no markdown fences. "
            f"It must match this schema exactly:\n{json.dumps(schema, indent=2)}"
        )
