# Submission

## Project summary (200 words)

Ask any AI what the research says about a contested question and it returns a
fluent, confident consensus. That consensus is often fictional. Real literature
disagrees with itself — across populations, doses, and outcome measures — and
summarisation destroys exactly that signal, averaging conflicting findings into
a statement no individual study supports.

Faultline inverts the objective. Given a research question in any field, it
searches systematically, screens with a reported denominator, extracts findings
*with* their qualifiers, and then finds where studies genuinely contradict each
other.

Eight model lineages take opposed roles. Two judge independently whether two
findings are even comparable; a third breaks ties. Three argue competing
explanations for a conflict, each required to cite concrete study attributes. An
adjudicator rules — and can reject every explanation, which is how research gaps
are identified.

Evaluated against published systematic reviews rather than self-authored tests.
On vitamin D and respiratory infection it independently reached the same
moderator the review authors did. False-conflict rate 12.5%; retrieval recall
11.9%, reported as the known weakness.

Runs on local models plus free tiers at roughly one cent per run.

*(198 words)*

---

## Submission checklist

| Requirement | Status |
|---|---|
| Public repository | ✅ [GitHub](https://github.com/varadharajanv0310/Build-Multi-Agent-AI-Systems-IIT-Madras-) |
| Setup instructions | ✅ [README](README.md#reproducibility) |
| 200-word summary | ✅ above |
| Reproducibility section | ✅ models, APIs, datasets, cost, limitations in README |
| Architecture diagram | ✅ README |
| Agent execution trace | ✅ persisted per run in SQLite `events` |
| Evidence citations | ✅ every claim carries paper ID + locator |
| Cost table | ✅ per-lineage in every run and in the report |
| Failure-case demo | ✅ `scripts/test_veto.py` |
| **3-minute demo video** | ❌ **not recorded** — script ready in [DEMO.md](DEMO.md) |

## Reproducibility

**Models.** Local via Ollama: `qwen3:8b`, `gpt-oss:20b`, `mistral:7b-instruct`.
Hosted free tier: `llama-3.3-70b-versatile`, `openai/gpt-oss-120b` (Groq);
`nvidia/nemotron-3-nano-30b-a3b:free` (OpenRouter). Paid, negligible:
`deepseek/deepseek-v4-flash`, `meta-llama/llama-4-maverick` (OpenRouter).

**Platform technologies.** LangGraph, DeepSeek V4, Llama 4.

**APIs.** OpenAlex (keyless, polite pool). Groq and OpenRouter free tiers.

**Datasets.** No fixed dataset. Corpora are retrieved live from OpenAlex
(~250M works, all fields). Evaluation ground truth is discovered at run time
from published reviews rather than hand-picked.

**Estimated run cost.** ~$0.01. Local inference is unmetered; free tiers carry
the reasoning; DeepSeek V4 and Llama 4 are the only billed calls. Total spend
across all development and evaluation is under $1.

**Hardware.** RTX 5080, ~14 GB VRAM. Note `gpt-oss:20b` (13 GB) and `qwen3:8b`
(5.2 GB) cannot co-reside, so the pipeline batches by stage.

**Known limitations.**
- Abstract-only; full-text acquisition is not implemented.
- Retrieval recall 11.9% — a lower bound, since review reference lists include
  background citations, but genuinely low. Citation snowballing is the standard
  fix and is not built.
- Automatic ground-truth discovery depends on OpenAlex's `type:review`
  classification, which suits fields with formal review culture. 2 of 5
  benchmark cases correctly return *no* ground truth rather than a wrong match.
- Commensurability judgement is the quality ceiling.
- Free-tier rate limits are real; the demo replays a recorded run for that
  reason.

## Safety and data

No confidential, personal, patient, unpublished or licence-restricted data is
used. All inputs are open bibliographic metadata and abstracts from OpenAlex.
Every claim in the output is attributed to a specific paper, and unverifiable
claims are tagged rather than asserted.
