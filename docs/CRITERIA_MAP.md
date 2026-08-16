# Judging criteria map — paste-ready

Slot this into the BUIDL Details, after JOB 02 and before "WHY MULTIPLE MODEL
LINEAGES". Plain text: the DoraHacks editor does not parse Markdown on paste.

Every figure is verifiable in the repo — run ids in `demo/`, benchmark numbers
in `evaluation/results.json`.

---

JUDGING CRITERIA MAP

RESEARCH UTILITY — 30%

The problem: a researcher has two questions no summary answers. "What will a
referee attack in my paper?" and "What does the literature actually say, and
what did I miss?"

Evidence in the demo: one PDF produces 9 extracted claims and 9 objections from
three independent reviewers, each with the minimum change that would fix it.
One question produces a direct answer, 5 conditions across 5 axes, 10 findings
each named to its source paper, and the full retrieved → screened → included
funnel.

Tested where it counts: run against a real unsubmitted paper heading to IEEE
TDSC, it found a missing base rate behind the paper's headline statistic, a
circular claim, and a contestable "LLM-free" framing. None were in the authors'
own limitations section.

AGENT COLLABORATION — 25%

Not a prompt chain, and not one model wearing six hats. Seven model lineages
run in opposed roles across three providers:

  Three reviewers on three different model families — Nemotron, DeepSeek V4,
  Llama 4 — attacking framing, method and significance.
  An opposed comparability pair deliberately split across providers, local
  Mistral against hosted Llama 3, so both sides cannot agree for the wrong
  reason.
  An adjudicator that can veto every explanation, verified by a constructed
  test suite (scripts/test_veto.py).

Collaboration is measured, not asserted. An earlier version assigned each
assessor a stance to argue and produced 100% disagreement — but the prompts
caused it, so the number meant nothing. With one neutral prompt and different
lineages, disagreement fell to 17%.

Stages exchange typed records, never prose. Cross-provider failover means a
provider outage cannot stall the council, and a local model terminates every
chain.

WORKING DEMO — 20%

  Deployed and live: https://faultline-6hlo.onrender.com/
  A three-page web application, not a CLI with printed output.
  Two recorded runs you can open and explore in the browser, labelled with their
  original run ids and dates.
  A 2:42 demo video with captions.
  Every model call traced in SQLite and replayable.
  Degradation is visible: a rate-limited database surfaces as a banner while
  the run continues, instead of failing silently.

COST EFFICIENCY — 15%

Both demo runs cost $0.00 — while making 34 and 20 real model calls, at 82%
and 95% local execution.

That is the design, not a coincidence. Screening issues one model call per
retrieved paper, so it is the stage whose volume scales with the corpus; it
runs locally and unmetered. Hosted free tiers only ever see calls that scale
with council size. Content-hash caching and a hard per-run request cap stop a
runaway loop from burning a daily quota mid-demo.

ORIGINALITY — 10%

Most research assistants optimise fluency. Faultline optimises what survives
contact with a differently-trained model.

The insight it is built on: three prompts against one model produce three
flavours of the same blind spot, because they share training. Independent
lineages disagree about what counts as a problem — which is what a real review
panel does, and why review panels have more than one person on them.

Benchmarked against published systematic reviews rather than a self-authored
test set. Against a Cochrane-style review with 61 ground-truth references it
retrieved 106 papers at 19.7% recall, included 9, and surfaced 4 conflicts of
which 3 were explained by a stated moderator — with a 25% false-conflict rate.
Recall is the weakest number in the system and it is published here rather than
omitted, because a retrieval figure nobody reports is a retrieval figure nobody
verified.
