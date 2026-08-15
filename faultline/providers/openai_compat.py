"""Groq and OpenRouter — both speak the OpenAI chat-completions shape.

Hosted free tiers only ever see calls that scale with CONFLICT COUNT, never
with corpus size. That asymmetry is what keeps 20+ full runs inside free quota.

Two details learned during provider verification:

1. Groq sits behind Cloudflare, which blocks the default Python user agent and
   returns an opaque `HTTP 403 error code: 1010`. It reads like an auth
   failure and is not one. A real User-Agent fixes it.

2. 429 is categorically different from 5xx here. Retrying a quota-exhausted
   free tier just burns wall-clock, so it raises QuotaExhausted and the router
   fails over to another lineage instead of backing off.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from faultline.config import SETTINGS, ModelSpec
from faultline.providers.base import (
    CompletionResult,
    Provider,
    ProviderError,
    QuotaExhausted,
    extract_json,
    missing_required,
)


class OpenAICompatProvider(Provider):
    """Shared implementation; subclasses differ only in endpoint and headers."""

    base_url: str

    def __init__(self, api_key: str, timeout: float = 180.0):
        if not api_key:
            raise ProviderError(f"{self.name}: missing API key")
        self.api_key = api_key
        self._client = httpx.Client(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # Not optional — see Groq/Cloudflare note above.
            "User-Agent": SETTINGS.user_agent,
        }

    def complete(
        self,
        spec: ModelSpec,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        max_tokens: int | None = None,
    ) -> CompletionResult:
        # Append the schema to the last user turn even though we also request
        # json_object mode: these providers guarantee *valid JSON*, not JSON
        # matching OUR schema, so the instruction is doing real work.
        msgs = [dict(m) for m in messages]
        for m in reversed(msgs):
            if m.get("role") == "user":
                m["content"] = m["content"] + self.schema_instruction(schema)
                break

        payload = {
            "model": spec.model_id,
            "messages": msgs,
            "max_tokens": max_tokens or spec.max_output_tokens,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }

        started = time.perf_counter()
        try:
            resp = self._client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
            )
        except httpx.RequestError as e:
            raise ProviderError(f"{self.name} unreachable: {e}") from e

        if resp.status_code == 429:
            raise QuotaExhausted(f"{self.name}/{spec.model_id}: rate limited")
        if resp.status_code in (402, 403) and "quota" in resp.text.lower():
            raise QuotaExhausted(f"{self.name}/{spec.model_id}: {resp.text[:160]}")
        if resp.status_code != 200:
            raise ProviderError(
                f"{self.name}/{spec.model_id} HTTP {resp.status_code}: {resp.text[:200]}")

        body = resp.json()
        choices = body.get("choices") or []
        if not choices:
            raise ProviderError(f"{self.name}: no choices in response")

        message = choices[0].get("message", {}) or {}
        notes: list[str] = []
        text = (message.get("content") or "").strip()
        if not text:
            # Some hosted reasoning models mirror Ollama's split channel.
            text = (message.get("reasoning") or "").strip()
            if text:
                notes.append("recovered from reasoning channel")

        data = extract_json(text)
        if missing := missing_required(data, schema):
            raise ProviderError(f"{spec.model_id} omitted required keys {missing}")

        usage = body.get("usage", {}) or {}
        return CompletionResult(
            data=data,
            raw_text=text,
            spec=spec,
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            latency_ms=int((time.perf_counter() - started) * 1000),
            notes=notes,
        )

    def close(self) -> None:
        self._client.close()


class GroqProvider(OpenAICompatProvider):
    name = "groq"
    base_url = "https://api.groq.com/openai/v1"

    def __init__(self, timeout: float = 180.0):
        super().__init__(SETTINGS.groq_api_key, timeout)


class OpenRouterProvider(OpenAICompatProvider):
    name = "openrouter"
    base_url = "https://openrouter.ai/api/v1"

    def __init__(self, timeout: float = 180.0):
        super().__init__(SETTINGS.openrouter_api_key, timeout)

    def _headers(self) -> dict[str, str]:
        # OpenRouter attributes free-tier usage to the referring project.
        return {
            **super()._headers(),
            "HTTP-Referer": SETTINGS.repo_url,
            "X-Title": "Faultline",
        }
