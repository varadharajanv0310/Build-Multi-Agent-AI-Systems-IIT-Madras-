# Submission — Research Agents Hack (IIT Madras)

**Research Agents Hack: Build Multi-Agent AI Systems (IIT Madras)**, DoraHacks.
Track: **Literature Review & Synthesis**. Submitted 17 August 2026.

| | |
|---|---|
| Project | **Faultline** |
| Live demo | https://faultline-6hlo.onrender.com/ |
| Repository | https://github.com/varadharajanv0310/FAULTLINE |
| Team | V Varadharajan · A Sowmiya Priya — SRM Ramapuram, Chennai |

---

## What the track asked for

> *Find relevant papers, compare evidence, summarize consensus, and surface
> research gaps.*

Faultline does this as **two products on one engine**:

- **Ask a question** → it searches, screens, extracts and answers, with the
  conditions that change the answer and the corpus funnel behind it.
- **Review my paper** → it extracts your claims, retrieves the surrounding
  literature, and runs three opposed reviewers.

Both share the same pipeline: field calibration → search strategy → concurrent
multi-database retrieval → recall-biased screening → qualified claim extraction.
What differs is what the council does with the findings at the end.

---

## Named platform technologies used

The event named CrewAI, LangGraph, AutoGen, Llama 4 and DeepSeek V4. Faultline
uses three:

- **LangGraph** — the state graph, including the backward edge that widens
  retrieval when the corpus comes back thin.
- **Llama 4** (`meta-llama/llama-4-maverick`) — reviewer R3, significance.
- **DeepSeek V4** (`deepseek/deepseek-v4-flash`) — reviewer R2, method. This is
  the reviewer that produced the sharpest objection in the demo run.

---

## Evidence

Every figure below comes from a committed run record, not an estimate.

### Paper review — [`demo/seva.json`](demo/seva.json), run `d375b1cc3d94`

Run against SEVA, a real unsubmitted paper on corpus-poisoning detection in RAG
being prepared for IEEE TDSC — written by one of us, and never refereed.

- 10,867 words → 9 empirical claims
- Field identified unprompted: adversarial ML, poisoning detection for RAG
- **6 major objections, 9 total**, across 3 model lineages
- 113s · 34 model calls · 82% local · **$0.00**

It raised a missing base rate behind the paper's headline statistic, a circular
claim, and an argument that the paper's "LLM-free" framing is contestable given
its dependence on pretrained embedding models. None were in the authors' own
limitations section.

### Question answering — [`demo/question.json`](demo/question.json), run `245d5d47c14b`

- Direct answer with moderate confidence, qualified consensus
- **5 conditions across 5 different axes** — population, dose, setting,
  duration, measurement
- 3 databases · 35 retrieved → 29 unique → screened
- 44s · 20 model calls · 95% local · **$0.00**

A deliberately different field from the paper run, to show the engine is not
domain-specific.

---

## Design decisions worth reading

**Opposed lineages, not opposed prompts.** An earlier version assigned each
assessor a stance to argue and read the resulting disagreement as independent
judgement. That is measurement error — it produced a meaningless 100%
disagreement rate. Assessors now share one neutral prompt and differ only by
lineage; disagreement fell to 17%.

**The panel sees the paper.** An earlier version passed reviewers only the
extracted claim list, and they confidently objected that a paper "does not
report the sample size" when it did. Faulting an author for our own extraction
gap is worse than raising nothing.

**Four databases, merged.** Retrieval used to return OpenAlex's hits the moment
they were non-empty, making the other three a failure path. A question that
returned 0 usable papers from OpenAlex alone returns a real answer across all
four. Whichever database answers first is not the same thing as the literature.

**The public instance cannot be exhausted.** It replays recorded runs and
returns 503 for live submission, because a public URL runs on our keys and a
rate-limited key would break the demo for the people it was published for.

---

## Reproducing

```bash
pip install -r requirements.txt
```

```bash
python scripts/record_demo.py mine --paper path/to/paper.pdf
```

Full setup, including the local models, is in the [README](README.md).
Deployment modes are in [docs/DEPLOY.md](docs/DEPLOY.md).

---

## Known limits

- Retrieval recall is the weakest component; citation snowballing is not built.
- Extraction is abstract-first; full-text acquisition is not implemented.
- Hosted-only deployment degrades under free-tier rate limits, because screening
  issues one model call per retrieved paper.
