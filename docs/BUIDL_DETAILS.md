# BUIDL "Details" — paste-ready

The DoraHacks editor does not parse Markdown on paste, so this is written to
read correctly as plain text. Paste it as-is; if you want headings bold, select
the heading line and use the editor's toolbar.

Live demo: https://faultline-6hlo.onrender.com/
Code: https://github.com/varadharajanv0310/FAULTLINE

---

Faultline — two jobs on one engine.

Ask a question and get an answer from the literature. Or hand it your draft and
face three independent reviewers before a real referee does.

Track: Literature Review & Synthesis.

Live demo — https://faultline-6hlo.onrender.com/
Code — https://github.com/varadharajanv0310/FAULTLINE


THE PROBLEM

Researchers cannot review their own work. After eight months on a paper you
stop seeing it. The referee does not.

And when you ask a chat model about a literature, it returns a confident
paragraph and a handful of papers, with no way to know what it missed or
whether any of it is real.

Both failures share a root: one model, one perspective, no denominator.


JOB 01 — ANSWER A QUESTION FROM THE LITERATURE

It searches four academic databases at once (OpenAlex, Crossref, Europe PMC,
arXiv), screens every result for relevance, reads the studies that survive, and
answers.

The answer arrives with confidence and consensus stated separately, the
conditions that change it — each tagged with the axis it moves on — anywhere
studies disagree, and the full corpus funnel showing what was retrieved,
screened, included and excluded.

Measured run, "Does creatine supplementation improve cognitive performance in
healthy adults?"

   Answer — modest improvement, especially during sleep deprivation
   Confidence and consensus — moderate, qualified
   Conditions surfaced — 5, across 5 different axes
   Databases — Crossref, Europe PMC, OpenAlex
   44 seconds · 20 model calls · 95% ran locally · cost $0.00


JOB 02 — REVIEW YOUR PAPER

It extracts your claims, retrieves the surrounding literature, then runs three
reviewers who attack different axes: framing, method, significance. Every
objection ships with the minimum change that would neutralise it.

Measured run on SEVA — a real unsubmitted paper on corpus-poisoning detection
in RAG, being prepared for IEEE TDSC:

   Read 10,867 words, extracted 9 empirical claims
   Identified the field unprompted — adversarial ML, poisoning detection for RAG
   Raised 6 major objections, 9 total, across 3 model lineages
   113 seconds · 34 model calls · 82% ran locally · cost $0.00

Three of the objections it raised:

   The headline claim reports 0% poison evasion with a 95% Wilson upper bound
   but no base rate — without which the bound does not mean what it appears to.

   "The gate prevents all the corruption it detects" is circular by
   construction.

   The paper calls the method "LLM-free" while depending on pretrained
   embedding models. A referee can call that external model dependence under
   another name.

None of these appeared in the authors' own limitations section.


WHY THREE MODEL FAMILIES, NOT THREE PROMPTS

Three prompts against one model produce three flavours of the same blind spot.
Separate training lineages genuinely disagree about what counts as a problem,
which is what a real review panel does.

Seven lineages run in opposed roles:

   R1 framing — Nemotron
   R2 method — DeepSeek V4
   R3 significance — Llama 4
   Adjudicator and field calibration — gpt-oss
   Comparability, an opposed pair — Mistral against Llama 3
   Screening and extraction — Qwen 3, local

An earlier version gave each assessor a stance to argue, then read the
resulting disagreement as independent judgement. That is measurement error,
not evidence, and it produced a meaningless 100% disagreement rate. Assessors
now get the same neutral prompt and differ only by lineage. Disagreement fell
to 17% — a number that means something.


HONESTY AS A DESIGN CONSTRAINT

Every claim traces to a specific paper, and findings display the source title.
Nothing is asserted without it.

The denominator is shown rather than hidden. A chat model gives you five papers
and no idea what it missed.

When the evidence does not settle a question, it says so instead of
manufacturing confidence. On the SEVA run it reported zero literature findings
and marked the evidence base thin, because corpus-poisoning defence is a
genuinely new field. Inventing four plausible citations there would have looked
better and been worthless.

Degradation is visible. A rate-limited database surfaces as a banner while the
run continues, rather than failing silently.


ARCHITECTURE

A LangGraph state graph with a backward edge for retrieval widening. Roles map
to models through an indirection with cross-provider failover, so a single
provider outage cannot stall the council, and a local model terminates every
chain. Typed records are the only interchange format — never prose. Every model
call is content-hash cached and traced in SQLite.

Inference runs on Ollama locally (Qwen 3, Mistral) plus Groq and OpenRouter
free tiers. Screening issues one model call per retrieved paper, and running
that volume locally is exactly what makes a full run cost nothing.


THE LIVE DEMO

https://faultline-6hlo.onrender.com/

The public instance replays two recorded runs, labelled on screen with their
original run ids and dates. Live submission is disabled there on purpose: a
public URL runs on our API keys, and a rate-limited key would break the demo
for the people it was published for. Clone the repo to do a real run.

Note: it is a free instance, so it sleeps after inactivity and the first load
can take about a minute to wake.


Built by V Varadharajan and A Sowmiya Priya, SRM.
