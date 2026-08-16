# Faultline

**Two jobs on one engine. Ask a question and get an answer from the literature.
Or hand it your draft and face three independent reviewers before a real
referee does.**

Track: Literature Review & Synthesis.

---

## The problem

Researchers cannot review their own work. After eight months on a paper you
stop seeing it — the referee does not. And when you ask a chat model about a
literature, it returns a confident paragraph and a handful of papers, with no
way to know what it missed or whether any of it is real.

Both failures have the same root: one model, one perspective, no denominator.

---

## What it does

### Job 01 — Answer a question from the literature

Searches **four academic databases concurrently** (OpenAlex, Crossref, Europe
PMC, arXiv), screens every result for relevance, extracts each study's actual
findings with their qualifiers, and answers.

The answer is not just a sentence. It comes with:

- **Confidence and consensus**, stated separately
- **The conditions that change the answer**, each tagged with the axis it
  moves on — population, dose, duration, setting, measurement, design
- **Where studies disagree**, with the finding indices on each side
- **The corpus funnel** — retrieved → unique → screened → included → excluded

*Measured run — "Does creatine supplementation improve cognitive performance in
healthy adults?"*

| | |
|---|---|
| Answer | Modest improvement, especially during sleep deprivation |
| Confidence / consensus | Moderate / qualified |
| Conditions surfaced | 5, across 5 different axes |
| Databases | Crossref, Europe PMC, OpenAlex |
| Time / calls / cost | 44s · 20 model calls · **$0.00** |
| Ran locally | 95% |

### Job 02 — Review your paper

Extracts your claims, retrieves the surrounding literature, then runs **three
reviewers who attack different axes** — framing, method, significance — and
appraises the evidence base your paper sits in.

Every objection ships with the **minimum change that would neutralise it**.

*Measured run — SEVA, a real unsubmitted paper on corpus-poisoning detection in
RAG, being prepared for IEEE TDSC:*

| | |
|---|---|
| Read | 10,867 words → 9 empirical claims |
| Field identified | Adversarial ML — poisoning detection for RAG (unprompted) |
| Objections | 6 major, 9 total, across 3 lineages |
| Time / calls / cost | 113s · 34 model calls · **$0.00** |
| Ran locally | 82% |

Three of the objections it raised:

- The headline claim reports 0% poison evasion with a 95% Wilson upper bound
  but **no base rate** — without which the bound does not mean what it appears
  to mean.
- *"The gate prevents all the corruption it detects"* is **circular by
  construction**.
- The paper calls the method **"LLM-free"** while depending on pretrained
  embedding models — a referee can call that external model dependence under
  another name.

None of these were in the authors' own limitations section.

---

## Why three model families, not three prompts

This is the part that matters. Three prompts against one model produce three
flavours of the **same blind spot**. Separate training lineages genuinely
disagree about what counts as a problem — which is what a real review panel
does.

Seven lineages run in opposed roles:

| Role | Lineage |
|---|---|
| R1 framing | Nemotron |
| R2 method | **DeepSeek V4** |
| R3 significance | **Llama 4** |
| Adjudicator / calibration | gpt-oss |
| Comparability (opposed pair) | Mistral vs Llama 3 |
| Screening / extraction | Qwen 3 (local) |

An earlier version assigned each assessor a *stance to argue*, then read the
resulting disagreement as independent judgement. That is measurement error,
not evidence, and it produced a meaningless 100% disagreement rate. Assessors
now receive the same neutral prompt and differ only by lineage. Disagreement
fell to 17% — a number that means something.

---

## Honesty as a design constraint

- **Every claim traces to a specific paper.** Findings display the source
  title; nothing is asserted without it.
- **The denominator is shown, not hidden.** A chat model gives you five papers
  and no idea what it missed.
- **When the evidence does not settle a question, it says so** rather than
  manufacturing confidence. On the SEVA run it reported **0 literature
  findings** and marked the evidence base *thin*, because corpus-poisoning
  defence is a genuinely new field — inventing four plausible citations there
  would have looked better and been worthless.
- **Degradation is visible.** When a database is rate-limited the run
  continues and says so in a banner instead of failing silently.

---

## Architecture

**LangGraph** state graph with a backward edge for retrieval widening.
Role→model indirection with cross-provider failover, so a Groq outage cannot
stall the council; a local model terminates every chain. Typed records are the
only interchange format — never prose. Content-hash caching, a request-based
budget, and a full trace of every model call in SQLite.

Inference: **Ollama locally** (Qwen 3, Mistral) plus **Groq** and
**OpenRouter** free tiers. Screening issues one call per retrieved paper, and
running that volume locally is exactly what makes a full run cost **$0.00**.

---

## Known limits

Stated because a tool that hides these is not one you should trust:

- **Retrieval recall is the weak point.** Citation snowballing is not
  implemented, so the corpus is what four databases return for generated
  queries.
- **Abstract-first.** Full-text acquisition is not built; extraction works from
  abstracts and any full text supplied directly.
- Hosted-only deployment degrades: screening volume meets free-tier limits.
  The design pays off locally.

---

## Links

- **Code:** https://github.com/varadharajanv0310/FAULTLINE
- **Demo video:** 2:42, with captions

Built by **V Varadharajan** and **A Sowmiya Priya**, SRM.
