# Paste-ready copy

Every number below is measured from a real run, not estimated. Sources:
`demo/seva.json` (run_d375b1cc3d94) and `demo/question.json` (run_245d5d47c14b).

---

## YouTube — description

> Faultline is a research tool with two jobs on one engine: ask a question and
> get an answer from the literature, or hand it your draft and face three
> independent reviewers before a real referee does.
>
> In this demo it reviews SEVA — a real paper on corpus-poisoning detection in
> RAG, being prepared for IEEE TDSC — and answers a question in a completely
> different field to show the engine is not domain-specific.
>
> WHAT MAKES IT DIFFERENT
> Three reviewers, each running on a different model family, so they do not
> share blind spots. On SEVA they raised six major objections, including that
> the paper's headline Wilson bound is reported without a base rate, that one
> claim is circular by construction, and that calling the method "LLM-free"
> is arguable when it depends on pretrained embedding models.
>
> Every claim traces back to a specific paper. When the literature does not
> support an answer, it says so instead of inventing citations.
>
> TIMESTAMPS
> 0:00  The two jobs
> 0:17  Reviewing a real paper
> 1:15  Answering a question from the literature
> 2:12  Stack and cost
>
> BUILT WITH
> LangGraph orchestration · seven model lineages across Ollama (local), Groq
> and OpenRouter free tiers · retrieval across OpenAlex, Crossref, Europe PMC
> and arXiv.
>
> MEASURED
> Paper review: 113s, 34 model calls, 82% local. Question: 44s, 20 calls, 95%
> local. Total cost of both runs: $0.00.
>
> The runs shown are recorded and replayed, labelled on screen with their run
> id — the pipeline is real, the clock is compressed to fit the format.
>
> Code: https://github.com/varadharajanv0310/FAULTLINE
> Built by V Varadharajan and A Sowmiya Priya, SRM.
> Research Agents Hack — Literature Review & Synthesis track.

---

## DoraHacks — Vision ("Describe the problem which this project solves")

> Researchers cannot review their own work. After eight months on a paper you
> stop seeing it; the referee does not. And when you ask a chat model about a
> literature, it hands you a confident paragraph and a handful of papers, with
> no way to know what it missed or whether any of it is real.
>
> Faultline attacks both halves with one engine. Ask it a question and it
> searches four academic databases, screens what comes back, extracts each
> study's actual findings with the conditions attached, and answers — showing
> the denominator, the conditions that change the answer, and where studies
> disagree. Hand it your draft and it extracts your claims, then runs three
> reviewers who attack your framing, your method and your significance.
>
> The reviewers each run on a different model family. That is the point: three
> prompts against one model produce three flavours of the same blind spot,
> whereas separate lineages disagree about what matters — which is what a real
> panel does. Every objection ships with the minimum change that would fix it.
>
> It is built to be honest about its own limits. Every claim traces to a
> specific paper, the corpus funnel is shown rather than hidden, and when the
> retrieved evidence does not settle a question it reports that instead of
> manufacturing a confident answer.
>
> Tested on a real unsubmitted paper heading to IEEE TDSC, it raised six major
> objections its authors had not written down — including a missing base rate
> behind the paper's headline statistic.

---

## DoraHacks — short tagline

> Three opposed AI reviewers read your paper before a referee does — and answer
> research questions from the literature, with every claim traced to its source.

---

## A note on the form

**Category** is currently set to *Other*. This is a multi-agent AI system, so
**AI / Robotics** is the better fit unless the track guidance says otherwise.

**Demo video** is required and takes a YouTube link — upload
`demo/recording/faultline-demo.mp4` and paste the URL.

---

## Team

- **V Varadharajan** — SRM
- **A Sowmiya Priya** — SRM
