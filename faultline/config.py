"""Configuration and the role-to-model bindings that define the council.

Every model here was empirically verified (2026-08-16) to emit a valid typed
record for a real commensurability judgment — not merely to respond. See
scripts/verify_providers.py to re-verify; free tiers change without notice.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class Role(str, Enum):
    """What an agent is for. Roles bind to models; agents never name models."""

    QUERY_EXPANSION = "query_expansion"
    SCREENING = "screening"
    EXTRACTION = "extraction"
    CALIBRATION = "calibration"
    COMMENSURABILITY_A = "commensurability_a"
    COMMENSURABILITY_B = "commensurability_b"
    PANEL_1 = "panel_1"
    PANEL_2 = "panel_2"
    PANEL_3 = "panel_3"
    ADJUDICATION = "adjudication"


class Lineage(str, Enum):
    """Training lineage. The council's diversity claim is measured in these,
    not in vendor count — two vendors serving the same base model share the
    blind spots we are trying to break."""

    QWEN = "qwen"
    MISTRAL = "mistral"
    GPT_OSS = "gpt-oss"
    LLAMA = "llama"
    NEMOTRON = "nemotron"
    GEMMA = "gemma"
    GEMINI = "gemini"


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model_id: str
    lineage: Lineage
    # Provider enforces the JSON schema server-side vs. we prompt-and-repair.
    native_schema: bool = False
    # How to handle a reasoning model's separate thinking channel. Per-model,
    # not a boolean, because the right answer genuinely differs:
    #   None    - omit the parameter entirely (non-reasoning models)
    #   False   - disable reasoning outright
    #   "low"   - minimal reasoning effort
    # gpt-oss:20b returns EMPTY output when `think: False` is combined with a
    # JSON schema — 30 tokens generated, both content and thinking blank.
    # Either setting alone is fine; only the pair breaks. It needs "low".
    think: bool | str | None = None
    max_output_tokens: int = 1024
    # Hosted calls draw on a finite free-tier quota; local ones do not.
    metered: bool = True


# --- The council -------------------------------------------------------------
# Local absorbs everything that scales with CORPUS SIZE. Hosted free tiers only
# ever see calls that scale with CONFLICT COUNT, which is 1-2 orders of
# magnitude smaller. That asymmetry is what makes 20+ runs viable at $0.

ROSTER: dict[Role, ModelSpec] = {
    Role.SCREENING: ModelSpec(
        "ollama", "qwen3:8b", Lineage.QWEN,
        native_schema=True, think=False, max_output_tokens=256, metered=False),
    Role.QUERY_EXPANSION: ModelSpec(
        "ollama", "qwen3:8b", Lineage.QWEN,
        native_schema=True, think=False, max_output_tokens=512, metered=False),
    Role.EXTRACTION: ModelSpec(
        "ollama", "gpt-oss:20b", Lineage.GPT_OSS,
        native_schema=True, think="low", max_output_tokens=2048, metered=False),

    # Opposed lineages by construction. Local Mistral vs hosted Llama — if both
    # sides ran the same base model they would agree for the wrong reason.
    Role.COMMENSURABILITY_A: ModelSpec(
        "ollama", "mistral:7b-instruct", Lineage.MISTRAL,
        native_schema=True, max_output_tokens=512, metered=False),
    Role.COMMENSURABILITY_B: ModelSpec(
        "groq", "llama-3.3-70b-versatile", Lineage.LLAMA,
        native_schema=True, max_output_tokens=512),

    # Three stances, three lineages. Same prompt across all three would be
    # ensembling; each carries a different explanation type to argue for.
    Role.PANEL_1: ModelSpec(
        "openrouter", "nvidia/nemotron-3-nano-30b-a3b:free", Lineage.NEMOTRON,
        native_schema=True, max_output_tokens=1024),
    Role.PANEL_2: ModelSpec(
        "openrouter", "google/gemma-4-31b-it:free", Lineage.GEMMA,
        native_schema=True, max_output_tokens=1024),
    Role.PANEL_3: ModelSpec(
        "groq", "llama-3.3-70b-versatile", Lineage.LLAMA,
        native_schema=True, max_output_tokens=1024),

    # Runs once per review and configures everything downstream, so errors
    # propagate further than anywhere else in the system.
    Role.CALIBRATION: ModelSpec(
        "groq", "openai/gpt-oss-120b", Lineage.GPT_OSS,
        native_schema=True, max_output_tokens=4096),

    # Weighs arguments and holds the veto. Strongest verified free model.
    Role.ADJUDICATION: ModelSpec(
        "groq", "openai/gpt-oss-120b", Lineage.GPT_OSS,
        native_schema=True, max_output_tokens=2048),
}

# Tried in order when a role's primary model is rate-limited or erroring.
# Deliberately crosses providers: a Groq outage must not stall the council.
FAILOVER: dict[Role, list[ModelSpec]] = {
    Role.ADJUDICATION: [
        ModelSpec("openrouter", "nvidia/nemotron-3-super-120b-a12b:free",
                  Lineage.NEMOTRON, native_schema=True, max_output_tokens=2048),
        ModelSpec("groq", "llama-3.3-70b-versatile", Lineage.LLAMA,
                  native_schema=True, max_output_tokens=2048),
    ],
    Role.CALIBRATION: [
        ModelSpec("openrouter", "nvidia/nemotron-3-super-120b-a12b:free",
                  Lineage.NEMOTRON, native_schema=True, max_output_tokens=4096),
    ],
    Role.COMMENSURABILITY_B: [
        ModelSpec("openrouter", "nvidia/nemotron-3-nano-30b-a3b:free",
                  Lineage.NEMOTRON, native_schema=True, max_output_tokens=512),
    ],
    Role.PANEL_1: [
        ModelSpec("groq", "llama-3.3-70b-versatile", Lineage.LLAMA,
                  native_schema=True, max_output_tokens=1024)],
    Role.PANEL_2: [
        ModelSpec("openrouter", "nvidia/nemotron-3-nano-30b-a3b:free",
                  Lineage.NEMOTRON, native_schema=True, max_output_tokens=1024)],
    Role.PANEL_3: [
        ModelSpec("openrouter", "google/gemma-4-31b-it:free",
                  Lineage.GEMMA, native_schema=True, max_output_tokens=1024)],
}


@dataclass
class Settings:
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))
    openrouter_api_key: str = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY", ""))
    ollama_host: str = field(default_factory=lambda: os.getenv("OLLAMA_HOST", "http://localhost:11434"))
    polite_pool_email: str = field(default_factory=lambda: os.getenv("POLITE_POOL_EMAIL", ""))
    semantic_scholar_api_key: str = field(default_factory=lambda: os.getenv("SEMANTIC_SCHOLAR_API_KEY", ""))
    max_hosted_requests_per_run: int = field(
        default_factory=lambda: int(os.getenv("MAX_HOSTED_REQUESTS_PER_RUN", "1500")))

    db_path: Path = PROJECT_ROOT / "data" / "faultline.sqlite"
    repo_url: str = "https://github.com/varadharajanv0310/Build-Multi-Agent-AI-Systems-IIT-Madras-"

    @property
    def user_agent(self) -> str:
        """Scholarly APIs give the polite pool faster, more reliable service.
        Also required for Groq: the default Python UA trips a Cloudflare block
        that surfaces as an opaque HTTP 403 'error code: 1010'."""
        contact = self.polite_pool_email or "unknown"
        return f"Faultline/{__import__('faultline').__version__} (research-agent; mailto:{contact})"

    def missing_keys(self) -> list[str]:
        missing = []
        if not self.groq_api_key:
            missing.append("GROQ_API_KEY")
        if not self.openrouter_api_key:
            missing.append("OPENROUTER_API_KEY")
        if not self.polite_pool_email:
            missing.append("POLITE_POOL_EMAIL")
        return missing


SETTINGS = Settings()


def lineages_in_play() -> set[Lineage]:
    """Distinct training lineages across the council — the diversity metric
    that actually matters, reported in the run summary."""
    return {spec.lineage for spec in ROSTER.values()}
