"""The router: roles in, typed records out.

Everything the free-tier constraint demands lives here — cache lookup, budget
enforcement, backoff, and cross-lineage failover — so that no agent has to
know which model it is talking to, or that a model failed at all.

One distinction does real work: a rate-limited free tier and a flaky endpoint
need opposite responses. Backing off on an exhausted quota just burns
wall-clock, so QuotaExhausted fails over immediately to a different lineage,
while a transient error retries the same model first.
"""
from __future__ import annotations

import time
from typing import Any, Iterable, Sequence

from faultline.config import FAILOVER, ROSTER, SETTINGS, ModelSpec, Role
from faultline.instrumentation import BudgetExceeded, Ledger
from faultline.providers.base import CompletionResult, Provider, ProviderError, QuotaExhausted
from faultline.providers.ollama import OllamaProvider
from faultline.providers.openai_compat import GroqProvider, OpenRouterProvider
from faultline.store.db import Store, cache_key


class AllModelsFailed(ProviderError):
    """Primary and every failover exhausted. The caller decides whether to
    abstain — which, for this system, is a legitimate and common outcome."""


class Router:
    def __init__(self, store: Store, run_id: str, ledger: Ledger | None = None,
                 use_cache: bool = True, max_retries: int = 2):
        self.store = store
        self.run_id = run_id
        self.ledger = ledger or Ledger()
        self.use_cache = use_cache
        self.max_retries = max_retries
        self._providers: dict[str, Provider] = {}

    # --- provider registry ---------------------------------------------------

    def provider(self, name: str) -> Provider:
        if name not in self._providers:
            if name == "ollama":
                self._providers[name] = OllamaProvider()
            elif name == "groq":
                self._providers[name] = GroqProvider()
            elif name == "openrouter":
                self._providers[name] = OpenRouterProvider()
            else:
                raise ProviderError(f"unknown provider {name!r}")
        return self._providers[name]

    # --- the one call agents make -------------------------------------------

    def complete(
        self,
        role: Role,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        stage: str | None = None,
        subject_id: str | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        chain: list[ModelSpec] = [ROSTER[role], *FAILOVER.get(role, [])]
        last_error: Exception | None = None

        for depth, spec in enumerate(chain):
            is_failover = depth > 0

            # Cache first — papers recur heavily across questions, and without
            # reuse the free-tier quota maths does not survive 20+ runs.
            key = cache_key(spec.provider, spec.model_id, messages, schema)
            if self.use_cache and (hit := self.store.cache_get(key)):
                self.ledger.record(role, spec, cache_hit=True,
                                   tokens_in=hit["tokens_in"], tokens_out=hit["tokens_out"])
                self.store.event(self.run_id, "cache_hit", stage=stage, role=role.value,
                                 provider=spec.provider, model_id=spec.model_id,
                                 lineage=spec.lineage.value, subject_id=subject_id)
                return CompletionResult(
                    data=hit["data"], raw_text=hit["raw_text"] or "", spec=spec,
                    tokens_in=hit["tokens_in"], tokens_out=hit["tokens_out"],
                    from_cache=True)

            try:
                self.ledger.check_budget(spec)
            except BudgetExceeded:
                self.store.event(self.run_id, "quota", stage=stage, role=role.value,
                                 provider=spec.provider, model_id=spec.model_id,
                                 detail="run budget exceeded")
                raise

            result = self._attempt(role, spec, messages, schema, stage, subject_id,
                                   max_tokens, is_failover)
            if isinstance(result, CompletionResult):
                self.store.cache_put(key, spec.provider, spec.model_id,
                                     spec.lineage.value, result.data, result.raw_text,
                                     result.tokens_in, result.tokens_out)
                return result
            last_error = result

            if is_failover or depth + 1 < len(chain):
                self.store.event(
                    self.run_id, "failover", stage=stage, role=role.value,
                    provider=spec.provider, model_id=spec.model_id,
                    lineage=spec.lineage.value, subject_id=subject_id,
                    detail=f"{type(last_error).__name__}: {last_error}")

        raise AllModelsFailed(
            f"role {role.value}: all {len(chain)} models failed; last: {last_error}")

    def _attempt(self, role, spec, messages, schema, stage, subject_id,
                 max_tokens, is_failover) -> CompletionResult | Exception:
        """Try one model, retrying only errors that retrying can fix."""
        provider = self.provider(spec.provider)

        for attempt in range(1, self.max_retries + 2):
            try:
                result = provider.complete(spec, messages, schema, max_tokens)
            except QuotaExhausted as e:
                # Retrying an exhausted quota is pure wall-clock. Fail over.
                self.ledger.record(role, spec, failure=True, failover=is_failover)
                self.store.event(self.run_id, "quota", stage=stage, role=role.value,
                                 provider=spec.provider, model_id=spec.model_id,
                                 lineage=spec.lineage.value, subject_id=subject_id,
                                 detail=str(e))
                return e
            except ProviderError as e:
                if attempt > self.max_retries:
                    self.ledger.record(role, spec, failure=True, failover=is_failover)
                    self.store.event(self.run_id, "error", stage=stage, role=role.value,
                                     provider=spec.provider, model_id=spec.model_id,
                                     lineage=spec.lineage.value, subject_id=subject_id,
                                     attempts=attempt, detail=str(e))
                    return e
                time.sleep(min(2 ** attempt, 8))
                continue

            result.attempts = attempt
            self.ledger.record(role, spec, tokens_in=result.tokens_in,
                               tokens_out=result.tokens_out,
                               latency_ms=result.latency_ms, failover=is_failover)
            self.store.event(self.run_id, "call", stage=stage, role=role.value,
                             provider=spec.provider, model_id=spec.model_id,
                             lineage=spec.lineage.value, subject_id=subject_id,
                             tokens_in=result.tokens_in, tokens_out=result.tokens_out,
                             latency_ms=result.latency_ms, attempts=attempt)
            return result

        return ProviderError("unreachable")

    # --- opposed judgement ---------------------------------------------------

    def opposed(
        self,
        role_a: Role,
        role_b: Role,
        messages_a: list[dict[str, str]],
        messages_b: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        agree_on: str,
        stage: str | None = None,
        subject_id: str | None = None,
    ) -> tuple[CompletionResult | None, CompletionResult | None, bool | None]:
        """Run two lineages against the same question and report whether they
        agree — without merging them.

        Agreement is a confidence signal, never a verdict. Models converge on
        being wrong together, especially on widely-repeated misconceptions,
        which is exactly the failure mode in contested literature. So the
        divergent cases are kept and escalated rather than averaged away.
        """
        a = b = None
        try:
            a = self.complete(role_a, messages_a, schema, stage=stage, subject_id=subject_id)
        except ProviderError:
            pass
        try:
            b = self.complete(role_b, messages_b, schema, stage=stage, subject_id=subject_id)
        except ProviderError:
            pass

        agreed: bool | None = None
        if a is not None and b is not None:
            agreed = a.data.get(agree_on) == b.data.get(agree_on)
            self.store.event(
                self.run_id, "note", stage=stage, subject_id=subject_id,
                detail=f"lineages {a.lineage} vs {b.lineage} "
                       f"{'AGREE' if agreed else 'DIVERGE'} on {agree_on}")
        return a, b, agreed

    # --- VRAM-aware batching -------------------------------------------------

    def batch(
        self,
        role: Role,
        items: Sequence[tuple[str, list[dict[str, str]]]],
        schema: dict[str, Any],
        *,
        stage: str | None = None,
    ) -> dict[str, CompletionResult]:
        """Run one role across many inputs, keeping a single model resident.

        gpt-oss:20b (13GB) and qwen3:8b (5.2GB) cannot co-reside in the 5080's
        ~14GB of free VRAM. Interleaving roles per-item would make Ollama swap
        weights on every call, so stages run to completion one model at a time.
        """
        out: dict[str, CompletionResult] = {}
        for subject_id, messages in items:
            try:
                out[subject_id] = self.complete(
                    role, messages, schema, stage=stage, subject_id=subject_id)
            except BudgetExceeded:
                raise
            except ProviderError:
                continue  # abstaining on one item must not sink the stage
        return out

    def release_local(self, roles: Iterable[Role]) -> None:
        """Evict local models between stages so the next stage has VRAM."""
        provider = self._providers.get("ollama")
        if not isinstance(provider, OllamaProvider):
            return
        for role in roles:
            spec = ROSTER[role]
            if spec.provider == "ollama":
                provider.unload(spec.model_id)

    def close(self) -> None:
        for p in self._providers.values():
            if hasattr(p, "close"):
                p.close()
