"""Local models via Ollama — the unmetered workhorse.

Everything that scales with corpus size runs here. Two hard-won details are
encoded below:

1. Reasoning models (qwen3, gpt-oss) route their answer through a separate
   `thinking` channel and can return an EMPTY `content`. Reading only
   `content` silently yields nothing — observed on gpt-oss:20b during
   provider verification.

2. gpt-oss:20b (13GB) and qwen3:8b (5.2GB) cannot co-reside in the 5080's
   ~14GB of free VRAM. Alternating between them per-call makes Ollama swap
   weights every time. `unload()` exists so the pipeline can batch by stage
   instead of thrashing.
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
    extract_json,
    missing_required,
)


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, host: str | None = None, timeout: float = 600.0):
        self.host = (host or SETTINGS.ollama_host).rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def complete(
        self,
        spec: ModelSpec,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        max_tokens: int | None = None,
    ) -> CompletionResult:
        payload: dict[str, Any] = {
            "model": spec.model_id,
            "messages": messages,
            "stream": False,
            # Ollama enforces a real JSON schema server-side.
            "format": schema,
            "options": {
                "num_predict": max_tokens or spec.max_output_tokens,
                # Deterministic-ish: this is a judgment task, not creative
                # writing, and reproducible traces are part of the deliverable.
                "temperature": 0.1,
            },
            "keep_alive": "10m",
        }
        if spec.think is not None:
            # Reasoning burns output tokens and adds latency, and the council's
            # epistemics come from opposed roles rather than any single model
            # ruminating — so we buy throughput back where we safely can.
            # But see ModelSpec.think: gpt-oss:20b silently emits NOTHING when
            # `think: False` meets a JSON schema, so this is per-model.
            payload["think"] = spec.think

        started = time.perf_counter()
        try:
            resp = self._client.post(f"{self.host}/api/chat", json=payload)
        except httpx.RequestError as e:
            raise ProviderError(f"ollama unreachable at {self.host}: {e}") from e

        if resp.status_code != 200:
            raise ProviderError(f"ollama HTTP {resp.status_code}: {resp.text[:200]}")

        body = resp.json()
        message = body.get("message", {}) or {}

        # The empty-content trap: prefer content, fall back to the reasoning
        # channel rather than returning nothing.
        text = (message.get("content") or "").strip()
        notes: list[str] = []
        if not text:
            text = (message.get("thinking") or "").strip()
            if text:
                notes.append("recovered from reasoning channel")

        data = extract_json(text)
        if missing := missing_required(data, schema):
            raise ProviderError(f"{spec.model_id} omitted required keys {missing}")

        return CompletionResult(
            data=data,
            raw_text=text,
            spec=spec,
            tokens_in=body.get("prompt_eval_count", 0),
            tokens_out=body.get("eval_count", 0),
            latency_ms=int((time.perf_counter() - started) * 1000),
            notes=notes,
        )

    # --- VRAM management -----------------------------------------------------

    def loaded(self) -> list[str]:
        try:
            r = self._client.get(f"{self.host}/api/ps", timeout=15.0)
            return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            return []

    def unload(self, model_id: str) -> None:
        """Evict a model from VRAM. Called between pipeline stages so the next
        stage's model has room, instead of forcing a swap on every call."""
        try:
            self._client.post(
                f"{self.host}/api/chat",
                json={"model": model_id, "messages": [], "keep_alive": 0},
                timeout=60.0,
            )
        except Exception:
            pass  # Best effort; Ollama will evict under pressure anyway.

    def close(self) -> None:
        self._client.close()
