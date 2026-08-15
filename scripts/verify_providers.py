"""Verify every model in the council can emit a valid typed record.

Run this before a demo. Free tiers change without notice, and the council's
diversity claim is only true for models that actually respond.

    python scripts/verify_providers.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from faultline.config import FAILOVER, ROSTER, SETTINGS, Role, lineages_in_play
from faultline.providers.base import ProviderError
from faultline.providers.ollama import OllamaProvider
from faultline.providers.openai_compat import GroqProvider, OpenRouterProvider

# The real shape the council exchanges, not a toy prompt.
SCHEMA = {
    "type": "object",
    "properties": {
        "comparable": {"type": "boolean"},
        "reason_code": {
            "type": "string",
            "enum": ["same_construct", "different_outcome_measure",
                     "different_population", "different_timepoint"],
        },
        "confidence": {"type": "number"},
    },
    "required": ["comparable", "reason_code", "confidence"],
}

TASK = (
    "Claim A: 'Drug D reduced 30-day mortality in ICU sepsis patients.'\n"
    "Claim B: 'Drug D showed no effect on 1-year all-cause mortality in outpatients.'\n\n"
    "Are these two claims measuring the same thing?"
)


def build_providers():
    providers = {"ollama": OllamaProvider()}
    if SETTINGS.groq_api_key:
        providers["groq"] = GroqProvider()
    if SETTINGS.openrouter_api_key:
        providers["openrouter"] = OpenRouterProvider()
    return providers


def main() -> int:
    if missing := SETTINGS.missing_keys():
        print(f"!! Missing config: {', '.join(missing)} — copy .env.example to .env")
        return 2

    providers = build_providers()
    messages = [{"role": "user", "content": TASK}]

    # Dedupe: several roles share a model; verify each model once.
    seen: dict[tuple[str, str], list[str]] = {}
    for role, spec in ROSTER.items():
        seen.setdefault((spec.provider, spec.model_id), []).append(role.value)
    for role, specs in FAILOVER.items():
        for spec in specs:
            seen.setdefault((spec.provider, spec.model_id), []).append(f"{role.value}:failover")

    by_key = {}
    for role, spec in ROSTER.items():
        by_key[(spec.provider, spec.model_id)] = spec
    for specs in FAILOVER.values():
        for spec in specs:
            by_key.setdefault((spec.provider, spec.model_id), spec)

    print(f"Verifying {len(seen)} models across {len(providers)} providers\n")
    ok_count = 0
    failures: list[str] = []

    for key, roles in seen.items():
        provider_name, model_id = key
        spec = by_key[key]
        provider = providers.get(provider_name)
        label = f"{provider_name}/{model_id}"

        if provider is None:
            print(f"  SKIP  {label:52s} (provider not configured)")
            continue

        try:
            result = provider.complete(spec, messages, SCHEMA)
        except ProviderError as e:
            print(f"  FAIL  {label:52s} {type(e).__name__}: {e}")
            failures.append(label)
            continue
        except Exception as e:  # noqa: BLE001 - surface anything unexpected
            print(f"  FAIL  {label:52s} {type(e).__name__}: {str(e)[:110]}")
            failures.append(label)
            continue

        ok_count += 1
        note = f" [{'; '.join(result.notes)}]" if result.notes else ""
        print(f"  OK    {label:52s} {result.latency_ms:>6}ms  "
              f"{spec.lineage.value:<9} {result.data}{note}")
        print(f"        roles: {', '.join(roles)}")

    print(f"\n{ok_count}/{len(seen)} models responding")
    print(f"Lineages in the council: {sorted(l.value for l in lineages_in_play())}")

    if failures:
        print(f"\nFailed: {', '.join(failures)}")
        print("Failover targets exist for the critical roles; check FAILOVER in config.py")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
