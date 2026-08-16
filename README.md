# Faultline

**Finds where a body of research contradicts itself, explains why, and reports what would resolve it.**

Research Agents Hack (IIT Madras) · Track: Literature Review & Synthesis

---

## The problem

Ask any LLM what the research says about a contested question and you get a fluent, confident consensus. That consensus is frequently fictional.

Real literature is full of studies that disagree — different populations, doses, outcome measures, follow-up windows — and the disagreement is usually the most informative thing in the corpus. Summarisation destroys exactly that signal, averaging conflicting findings into a smooth statement no individual study supports.

For a researcher or clinician this is worse than no answer. **Manufactured agreement is the failure mode that matters**, and every existing "research assistant" has it by design.

Faultline inverts the objective. It never smooths. Conflict is preserved structurally, and the system's most important capability is saying *the evidence does not support a conclusion here*.

## Why this isn't a prompt

| | Chat LLM | Faultline |
|---|---|---|
| Retrieval | ~8 papers, no denominator | Systematic search with screened counts and a measured recall figure |
| Perspective | One model, one opinion | 8 model lineages in adjudicated, opposed roles |
| Ability to refuse | Trained toward helpful coherence | Adjudicator can veto every explanation — [verified](scripts/test_veto.py) |
| Attribution | "studies suggest" | Paper ID + locator, structurally enforced |
| Reproducibility | Different answer each time | Same corpus, same trace, persisted |
| Error rate | None | Measured against published systematic reviews |

**You cannot detect a contradiction between studies you never retrieved.** Missing half a literature doesn't produce a partial answer — it produces a confident false consensus. That makes systematic retrieval a precondition, not a feature.

> An LLM gives you a **plausible** answer. This gives you a **defensible** one — with a denominator, a trace, and a measured error rate.

## Architecture

```
                    ┌──────────────────┐
                    │ Field Calibrator │  establishes the field's OWN
                    └────────┬─────────┘  evidentiary norms
                             ↓
                    ┌──────────────────┐
                    │ Question Framer  │  commensurability contract
                    └────────┬─────────┘  + primary-study search strategy
                             ↓
                ┌────────────────────────┐
         ┌─────→│  Retriever (OpenAlex)  │
         │      └────────┬───────────────┘
         │               ↓
         │      ┌──────────────────┐
         │      │    Screener      │  local, unmetered, recall-biased
         │      └────────┬─────────┘
         │               ↓
         │      ┌──────────────────┐
         │      │ Claim Extractor  │  findings WITH qualifiers
         │      └────────┬─────────┘
         │               ↓
         │      ┌────────────────────────────────┐
         │      │ Commensurability  A  ⟷  B      │  two lineages judge
         │      │   split → third lineage rules  │  INDEPENDENTLY
         │      └────────┬───────────────────────┘
         │               ↓
         │      ┌──────────────────┐
         │      │ Conflict Detector│
         │      └────────┬─────────┘
         │               ↓
         │        conflicts found?
         │       ╱               ╲
         └──── no                yes
        widen                     ↓
     (terminology         ┌──────────────────────────────┐
      from calibration)   │ Explanation Panel            │
                          │  population · dose ·         │  3 lineages,
                          │  measurement                 │  3 different stances
                          └────────┬─────────────────────┘
                                   ↓
                          ┌──────────────────┐
                          │   Adjudicator    │  explained / unresolved /
                          └────────┬─────────┘  not_a_conflict  ← the veto
                                   ↓
                          ┌──────────────────┐
                          │  Gap Classifier  │  unresolved → testable gap
                          └──────────────────┘
```

The backward edge is real, not decorative. When no conflict is found, the graph returns to retrieval and widens using terminology the Field Calibrator discovered — because **a narrow corpus that agrees with itself is indistinguishable from a literature that agrees**, and conflating those manufactures the false consensus this system exists to prevent. A linear pipeline cannot express that edge.

### Why multiple agents are forced, not decorative

1. **Commensurability is contested.** Call everything comparable and you invent conflicts; call nothing comparable and you find none. A single pass is wrong constantly.
2. **Explanation is a competition** between structurally different hypotheses, each required to cite concrete study attributes.
3. **Retrieval recall loops backward** — discovering two studies use different terminology for one outcome is the signal to search again with terms you didn't know to use.
4. **A single-model council reproduces the flaw it detects.** Two instances of one model share training data and blind spots. Model diversity is the same argument as reviewer diversity.

## The council

Eight training lineages. Everything scaling with **corpus size** runs locally and unmetered; hosted models only ever see calls scaling with **conflict count**, one to two orders of magnitude smaller. That asymmetry is what makes many full runs viable at near-zero cost.

| Role | Model | Lineage | Where |
|---|---|---|---|
| Screening | `qwen3:8b` | Qwen | local |
| Extraction | `gpt-oss:20b` | gpt-oss | local |
| Commensurability A | `mistral:7b-instruct` | Mistral | local |
| Commensurability B | `llama-3.3-70b-versatile` | Llama 3 | Groq |
| Panel — population | `nemotron-3-nano-30b` | Nemotron | OpenRouter |
| Panel — dose | `deepseek-v4-flash` | **DeepSeek V4** | OpenRouter |
| Panel — measurement | `llama-4-maverick` | **Llama 4** | OpenRouter |
| Calibration + Adjudication | `gpt-oss-120b` | gpt-oss | Groq |

Failover chains cross providers, so no single outage stalls the council.

**Platform technologies used:** LangGraph (orchestration), DeepSeek V4, Llama 4.

## Results

Measured against **published systematic reviews** — ground truth this team did not produce. See [`evaluation/results.json`](evaluation/results.json).

| Metric | Result |
|---|---|
| **Moderator agreement with review authors** | **1/1 scorable cases** |
| False-conflict rate | 12.5% |
| Retrieval recall (lower bound) | 11.9% |
| Cost per run | ~$0.01 |
| Local share of inference | ~59% |

**The headline result.** On vitamin D and respiratory infection, the published review concluded the disagreement came down to *"dosing regimen (daily/weekly vs bolus) and baseline status"*. Faultline independently reached `dose_exposure` — working only from primary studies, with no access to the review.

**The veto works.** Verified directly in [`scripts/test_veto.py`](scripts/test_veto.py), because a corpus run cannot distinguish "the adjudicator can't refuse" from "these conflicts happen to be explicable". Three constructed cases — an explicable moderator, two trials matching on every stated dimension whose panel cites nothing, and two different endpoints — all return the correct verdict, including `unresolved`.

### Honest limitations

- **Retrieval recall is the weak number.** Partly definitional (review reference lists include background citations that were never candidate studies, so this is a lower bound), but mostly real. Tripling retrieval breadth raised it only 8.4% → 11.9%, which is sub-linear — the binding constraint is query diversity, not volume. Citation snowballing is the standard fix and is not implemented.
- **Abstract-only.** Full-text acquisition is not built; all analysis runs on titles and abstracts.
- **Ground-truth discovery is biomedicine-shaped.** OpenAlex's `type:review` classification suits fields with formal review culture. Economics and education publish surveys and working papers instead, so 2 of 5 benchmark cases correctly return *no* ground truth rather than a wrong match.
- **Commensurability judgement is the quality ceiling.** Wrong in either direction and no downstream cleverness recovers.

## Reproducibility

```bash
git clone https://github.com/varadharajanv0310/Build-Multi-Agent-AI-Systems-IIT-Madras-
cd Build-Multi-Agent-AI-Systems-IIT-Madras-
pip install -r requirements.txt
cp .env.example .env      # add free Groq + OpenRouter keys, and your email
ollama pull qwen3:8b && ollama pull gpt-oss:20b && ollama pull mistral:7b-instruct
```

```bash
python scripts/verify_providers.py
```

```bash
python scripts/run_faultline.py "Does vitamin D supplementation prevent acute respiratory tract infections?"
```

```bash
python scripts/test_veto.py
```

```bash
python scripts/run_eval.py --limit 2
```

**Requirements:** Python 3.11+, Ollama, ~14 GB VRAM (tested on RTX 5080), free API keys from Groq and OpenRouter. No paid Anthropic/OpenAI keys.

**Datasets:** OpenAlex (~250M works, keyless). Ground truth is discovered at run time from published reviews, not hand-picked.

**Cost:** ~$0.01 per run. Local models are unmetered; Groq and OpenRouter free tiers carry the rest; DeepSeek V4 and Llama 4 are the only paid calls.

> Note on the $0 claim: this is near-zero because volume runs on local hardware and reasoning runs on free tiers, **while still performing genuine multi-model LLM inference**. It is not $0 achieved by making the pipeline deterministic.

## Repository

| Path | Contents |
|---|---|
| `faultline/agents/` | Calibrator, Framer, Extractor, and the council |
| `faultline/graph.py` | LangGraph orchestration, incl. the backward edge |
| `faultline/router.py` | Role→model routing, budget, backoff, cross-lineage failover |
| `faultline/eval/` | Ground-truth discovery and metrics |
| `faultline/store/` | SQLite claim store — **the trace is the product** |
| `scripts/` | Entry points and acceptance tests |
| `PLAN.md` | Full design rationale |

Every model call, cache hit, failover and verdict is persisted:

```bash
sqlite3 data/faultline.sqlite "SELECT stage, role, lineage, kind FROM events ORDER BY id DESC LIMIT 20"
```
