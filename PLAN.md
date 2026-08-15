# Faultline — Build Plan

**Track:** Literature Review & Synthesis
**Event:** Research Agents Hack (IIT Madras, DoraHacks)

---

## 1. What it is

Faultline maps where a body of research **contradicts itself**, explains why, and reports what would resolve it.

It does not summarize consensus. Consensus is the failure mode: ask any LLM what the literature says about a contested question and it returns a fluent, confident agreement that averages away the conflict. In evidence synthesis that is worse than no answer — it manufactures agreement that does not exist.

**Two entry points, one engine.**

- **Question mode** — "does X improve Y in population Z?" → assemble the evidence, find genuine contradictions, adjudicate competing explanations, report what remains unexplained.
- **Paper mode** — hand it a paper → extract its claims, derive the implicit question behind each, run the same analysis, then position that paper in its literature: corroborated, contradicted, or isolated.

Paper mode is question mode with the question auto-derived, plus one positioning step. Same agents, same evaluation, two products.

**Domain-general.** OpenAlex indexes every field. Evaluation is anchored where meta-analyses are densest (medicine, psychology, ecology, education) but the system is not restricted to them.

---

## 2. Why it isn't a prompt

A judge will ask this in the first minute. The answer:

| | Chat LLM | Faultline |
|---|---|---|
| Retrieval | ~8 papers, no denominator | Systematic search, screened count, recall estimate |
| Perspective | One model, one opinion | Opposed agents across **different providers** |
| Ability to refuse | Trained toward helpful coherence | Adjudicator can veto every explanation |
| Attribution | "studies suggest" | Paper ID + section + locator, structurally enforced |
| Scale | 8 abstracts in context | 800+ screened |
| Reproducibility | Different answer each time | Same corpus, same trace |
| Error rate | None | Measured against published meta-analyses |

**You cannot detect a contradiction between studies you never retrieved.** Missing half the literature doesn't produce a partial answer — it produces a confident false consensus. That makes systematic retrieval a precondition, not a feature.

> An LLM gives you a **plausible** answer. This gives you a **defensible** one — with a denominator, a trace, and a measured error rate.

---

## 3. Why the council must be multi-provider

The project's thesis is that single-perspective synthesis manufactures false consensus. **If every agent runs on the same model, they share training data, priors, and blind spots — the council reproduces exactly the flaw it exists to detect.** Two instances of one model agree far more than two different models do.

Model diversity is the same argument as reviewer diversity. It is required by the thesis, not decoration.

Two rules:

1. **Convergence is a confidence signal, not a verdict.** Models converge on being wrong together, especially on widely-repeated misconceptions — precisely the failure mode in contested literature. Agreement raises confidence; divergence is flagged, recorded, and escalated to adjudication. Nothing is silently averaged.
2. **Role diversity first, model diversity second.** Three models answering the same prompt and voting is ensembling — cheap, and weak on the collaboration criterion. Each model carries a *different role with different instructions*; disagreements are adjudicated with stated reasons.

This yields a metric nobody else will have: **inter-model agreement rate per judgment type.** "On commensurability, our three models agreed 78% of the time; the 22% where they split is where adjudication budget goes."

---

## 4. Agents

| Agent | Job | Distinct because |
|---|---|---|
| **Field Calibrator** | Establishes the field's evidentiary norms, appraisal framework, terminological instability, adjacent fields | Runs once, configures everything downstream. Domain-general is only possible because this exists |
| **Question Framer** | Structured question spec + **commensurability contract** — what would count as comparable evidence | Without an explicit contract, conflict detection is arbitrary |
| **Retriever** | OpenAlex / Crossref / Europe PMC / arXiv / S2. Query expansion, dedup. Accepts re-search instructions | Recall bounds everything downstream |
| **Screener** | Relevance triage against the spec | Pure volume — thousands of calls |
| **Claim Extractor** | Finding + **qualifiers**: population, N, design, effect direction, magnitude, uncertainty, scope conditions, hedges | Qualifiers are the raw material of conflict analysis, not metadata |
| **Commensurability Pair** | Two opposed agents argue whether two claims measure the same thing | Hardest judgment in the system; single-pass fails constantly in both directions |
| **Conflict Detector** | Among commensurable claims: opposite direction, effect vs null, incompatible magnitudes | Mostly deterministic given good extraction |
| **Explanation Panel** | Competing agents, each advancing one explanation type (population / dose / measurement / timing / power / publication bias), each citing concrete study attributes | Prevents the first plausible explanation winning by default |
| **Adjudicator** | Weighs explanations, assigns confidence, **holds veto** | The veto is the gap signal — the ability to say *no* is the system's most important behavior |
| **Gap Classifier** | Sorts into empirical / methodological / theoretical / translational, then genuinely-open / unimportant / already-closed / intractable | Not all gaps are unresolved disagreements; a methodological gap isn't a disagreement at all |
| **Reviewer Panel** *(paper mode)* | Three reviewers with priors drawn from the field's live controversies | Best use of model diversity in the whole system |

### Forced by the problem, four ways

1. **Commensurability is contested** — call everything comparable and you invent conflicts; call nothing comparable and you find none.
2. **Explanation is a competition between structurally different hypotheses.**
3. **Evidence weighting must be argued** — RCT n=2000 vs observational n=40.
4. **Retrieval recall loops backward** — discovering two studies use different terminology for the same outcome is the signal to search again with terms you didn't know to use.

---

## 5. Model roster

Three providers, **all free**. Every model below was empirically verified on 2026-08-16 to emit a valid typed record for a real commensurability judgment — not merely to respond.

| Stage | Calls/run | Model | Lineage | Rationale |
|---|---|---|---|---|
| Relevance screening | 500–3000 | `ollama/qwen3:8b` | Qwen · local | Volume no hosted free tier can absorb |
| Claim extraction | 50–200 | `ollama/gpt-oss:20b` | OpenAI OSS · local | Strongest local model; cached per paper |
| Query expansion | ~5 | `ollama/qwen3:8b` | Qwen · local | Mechanical |
| **Commensurability A** | 200–500 | `ollama/mistral:7b-instruct` | Mistral · local | Free, co-resides with qwen3:8b |
| **Commensurability B** | 200–500 | `groq/llama-3.3-70b-versatile` | Meta · hosted | Opposed lineage is the entire point |
| **Panel stance 1** | ~50 | `openrouter/nvidia/nemotron-3-nano-30b-a3b:free` | NVIDIA | Distinct priors |
| **Panel stance 2** | ~50 | `openrouter/google/gemma-4-31b-it:free` | Gemma | Distinct priors |
| **Panel stance 3** | ~50 | `groq/llama-3.3-70b-versatile` | Meta | Distinct priors |
| **Field calibration** | 1 | `groq/openai/gpt-oss-120b` | OpenAI OSS · 120B | Runs once; errors propagate |
| **Adjudication** | 30–60 | `groq/openai/gpt-oss-120b` | OpenAI OSS · 120B | Strongest verified free model |
| Adjudication failover | — | `openrouter/nvidia/nemotron-3-super-120b-a12b:free` | NVIDIA · 120B | Second 120B-class option |

**Six lineages** — Qwen, Mistral, gpt-oss, Llama, Nemotron, Gemma. Diversity is architectural, not merely vendor-level: six different training corpora and post-training regimes, which is what the thesis requires.

**Hardware:** RTX 5080, 16.3 GB VRAM (~14 GB free). `gpt-oss:20b` (13 GB) and `qwen3:8b` (5.2 GB) **cannot co-reside** — the pipeline must batch by stage (screen the whole corpus, unload, then extract) or Ollama thrashes on every alternation. `qwen3:8b` + `mistral:7b` (9.6 GB total) do co-reside, which is why they pair for local work.

### Gemini is demoted to opportunistic

Verification found `gemini-3.7-flash` returning `503 high demand` and `gemini-3.1-pro-preview` returning `429 quota exceeded` on a brand-new key. **The free tier cannot carry a critical-path role** — a rate limit during a judged demo is an avoidable way to lose the 20% working-demo criterion. Gemini stays wired in the provider registry as an opportunistic extra stance when it responds, and nothing depends on it.

Rejected: `groq/qwen/qwen3.6-27b` (failed JSON schema validation, empty `failed_generation`; redundant with local Qwen anyway).

### Known issue to handle in the provider layer

`ollama/gpt-oss:20b` returned empty content — it routes output through a reasoning channel. Both it and `qwen3:8b` need thinking/content-channel handling in the Ollama adapter. Free-tier limits change; re-verify before the demo.

**Provider abstraction is non-negotiable.** One `complete(messages, schema) -> structured` seam, from the first commit. Three reasons: the event's model policy is ambiguous about proprietary APIs, a heterogeneous council must swap providers per-role trivially, and free tiers rate-limit — the seam is where queuing, backoff, and failover live. If proprietary APIs turn out to be banned, the council goes all-local with zero architectural change.

### Structured output is the precondition

Agents emit typed records, never prose. If two models return `{comparable: false, reason_code: "different_outcome_measure"}` you can compare mechanically and compute agreement. If they return paragraphs, you need another model to compare them, you lose the calibration signal, and you reintroduce the fluency that hides errors. **Prose is a rendering of the record at the very end — never the interchange format.**

---

## 6. Cost model

**Target: $0.00 in API spend. $20 held in reserve, ideally unspent.**

The binding constraint is no longer dollars — it is **free-tier request quotas**. Design accordingly: the budget is measured in requests, not currency.

Per full research question:

| Stage | Calls | Destination |
|---|---|---|
| Screening + extraction | ~3000 | **Local — unmetered** |
| Commensurability (one side) | 200–500 | Local |
| Commensurability (other side) | 200–500 | Groq free tier |
| Explanation panel | ~150 | Gemini + Groq + local |
| Field calibration + adjudication | ~60 | Gemini free tier |
| **Hosted free-tier total** | **~500–700** | subject to daily quota |

**Everything that scales with corpus size runs local.** Hosted free tiers only ever see calls that scale with *conflict count*, which is 1–2 orders of magnitude smaller. That's what makes $0 feasible across 20+ runs.

### $0 here is not the incumbent's $0

Reprograph reports `$0.00` by running a deterministic default path — rule-matching wearing agent clothing, which buys the cost criterion at the direct expense of the collaboration criterion. Faultline reports near-$0 while running **genuine multi-model LLM inference across three providers**, because the volume sits on local hardware and the reasoning sits on free tiers. State this distinction explicitly in the writeup; it is the honest version of the same number.

### Required engineering

Free tiers rate-limit rather than bill, so throughput becomes the failure mode:

- **Content-hash cache on every `(claim, source)` pair** — papers recur heavily across questions. This moves from optimization to load-bearing.
- **Per-provider request budget with a hard cap** — a runaway loop must not burn the daily quota mid-demo.
- **Queue + exponential backoff + cross-provider failover** in the provider seam.
- **Demo replays from cache.** Pre-run the demo corpus so the judged demo is deterministic and quota-independent; show live runs separately for Q&A. A cached replay is honest when labeled, and you want determinism in a demo regardless.

### What the $20 reserve is for

Not the default path. Two legitimate uses:

1. **Quota insurance** during the demo window if free tiers throttle.
2. **A paid-adjudicator comparison run.** Adjudication is the one role where a weaker model most plausibly costs accuracy. If the eval shows that, run the harness a second time with a paid adjudicator and **report both numbers**. "Free-tier config scores X, paid-adjudicator config scores Y, at cost Z" is itself a cost-efficiency finding — 15% of the rubric — rather than an embarrassment.

If paid capacity is needed, DeepSeek is the cheapest capable option by a wide margin; $20 there is effectively unlimited at this workload.

### Why dropping the frontier model is defensible

Adjudication here is **structured**, not open-ended: given two arguments each citing a concrete span, choose one and justify against the field-calibration criteria. Schema-constrained selection is far more tractable for a mid-size model than free-form reasoning.

More importantly, it is the point of the architecture. The opposed-assessor design exists to extract better judgment than any single model would give — **the epistemics live in the structure, not the weights.** A council of free models that outperforms a single strong model on the same task is a stronger result than buying the answer, and it is directly measurable via the inter-model agreement metrics.

---

## 7. Output artifact

A **disagreement map**, not a report:

- Nodes: claims with scope conditions, citation confidence tag `[V]` / `[R]` / `[U]`
- Edges: agreement / conflict / incommensurable
- Conflict nodes: adjudicated explanation + confidence + inter-model agreement
- Unresolved conflicts: flagged as gaps, classified into four buckets
- Every node: paper ID + locator
- **Verify queue**: every `[R]`/`[U]` item with the exact search string to run

**Design invariants** (enforced in code, not requested in prompts):

1. No unattributed assertion, ever.
2. Conflicting findings are never merged into a single sentence.
3. "The literature does not support a conclusion here" is a *frequent* output.
4. The map is primary. Prose is generated *from* it and is secondary.

---

## 8. Evaluation

Published meta-analyses already perform this task formally — they quantify heterogeneity, run subgroup analyses and meta-regression to explain it, and state explicitly whether it was explained or remained. **That is peer-reviewed expert ground truth for exactly our output.**

Replay real reviews against literature available at review time and measure:

| Metric | Question |
|---|---|
| **Conflict recall** | Did we find the heterogeneity the authors found? |
| **False-conflict rate** | Did we invent contradictions they explicitly ruled out? |
| **Explanation precision** | Did we identify the same moderator their subgroup analysis found? |
| **Gap overlap** | Did our unresolved conflicts match their "implications for research"? |
| **Retrieval recall** | What fraction of their included studies did we retrieve? |
| **Abstain rate** | How often did we correctly decline? |
| **Inter-model agreement** | Per judgment type — the calibration signal |

**Secondary:** retrospective gap validation — restrict to pre-cutoff literature, check whether later published work addressed the gaps we flagged.

We will not score near-perfect, and reporting the honest number is the point. Every currently submitted project either has no evaluation or grades itself against defects it authored.

Run across **at least three fields** — showing it works across domains is a stronger result than depth in one.

---

## 9. Scope boundary

Keep two layers structurally separate:

- **Engine** — evidence claims, conflicts, explanations, gaps. **Measurable** against published meta-analyses. This is what gets evaluated.
- **Advisory layer** *(paper mode)* — reviewer simulation, positioning, novelty framing, read-next lists. **Not measurable.** This is what gets demoed.

If they blend, the evaluation story dissolves — and that story is the single biggest advantage over the submitted field.

---

## 10. Build order

**Phase A — Foundation** *(nothing works without these)*
1. Provider abstraction layer + cost/token instrumentation from call #1
2. Claim store: SQLite, append-only, full provenance, content-hash cache
3. Retrieval layer: OpenAlex primary; Crossref, Europe PMC, arXiv, S2
4. Document ingestion: structured sources first (PMC XML, arXiv LaTeX), PDF fallback

**Phase B — Engine**
5. Field Calibrator
6. Question Framer + paper-claim derivation
7. Claim Extractor (with qualifiers)
8. Screening cascade
9. Commensurability pair *(first multi-provider agent)*
10. Conflict Detector
11. Explanation Panel
12. Adjudicator + backward edges to Retriever/Extractor
13. Gap Classifier

**Phase C — Proof**
14. Meta-analysis replay harness
15. Retrospective gap validation
16. Inter-model agreement instrumentation
17. Cost report generator

**Phase D — Surface**
18. Disagreement map UI
19. Trace viewer (the trace is the product)
20. Advisory layer: reviewer panel, positioning

**Phase E — Submission**
21. README, architecture diagram, reproducibility section (models, APIs, datasets, run cost, limitations)
22. Demo video + **failure-case demo**

---

## 11. Honest limits

- **Commensurability judgment is the quality ceiling.** Wrong in either direction and no downstream cleverness recovers.
- **Retrieval recall bounds everything.** Missing studies produce false consensus — the exact failure this exists to prevent. Measured and reported, never assumed.
- **Explanations risk post-hoc rationalization.** Mitigated by requiring every explanation to cite concrete, checkable study attributes.
- **Open-access ceiling.** Abstract-level fallback, then explicit abstain. High abstain rates in some fields are honest, not a bug.
- **Citation function.** A citation can be background, contrast, method-use, or support — running entailment on a *contrast* citation is a category error and a false-positive source. The extractor must classify function and route accordingly.
- **PDF parsing is where systems like this die.** Prefer structured sources; treat PDF as the degraded fallback it is.
