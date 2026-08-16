# Demo — 3 minute recording guide

Everything below is ready to record. Narration is written to be read aloud or
pasted into a TTS tool; timings add to 3:00.

**Record with:** OBS Studio (free) or Windows Game Bar (`Win+G`).
**Narration:** read it yourself, or paste each block into ElevenLabs / Windows
Narrator / macOS `say` and lay the audio over the screen capture.

---

## Before you record

Pin the demo to a recorded run so nothing depends on a live API call. Generated
search queries vary between runs, and a free-tier rate limit mid-recording would
cost you the working-demo criterion.

```bash
python scripts/make_report.py run_635b7bb33604
```

Open these in tabs beforehand:

1. `reports/run_635b7bb33604.html` — the disagreement map
2. `README.md` on GitHub — the architecture diagram
3. A terminal in the project root
4. `evaluation/results.json`

---

## 0:00 – 0:25 · The problem

**Screen:** ChatGPT or Claude, ask *"Does vitamin D prevent respiratory infections?"*
Let the confident, smooth answer render. Highlight a phrase like "may modestly reduce".

> Ask any AI what the research says about a contested question, and you get this:
> fluent, confident, and averaged. But the real literature disagrees with itself.
> Some trials found a large benefit. Others found nothing at all.
>
> That disagreement is the most informative thing in the evidence — and
> summarisation destroys it. This isn't a mediocre answer. It's a manufactured
> consensus that no individual study supports.

---

## 0:25 – 0:50 · What Faultline does

**Screen:** the architecture diagram in the README.

> Faultline inverts the objective. It never smooths.
>
> It finds where a body of research contradicts itself, adjudicates why, and
> reports what would resolve it. Eight different model lineages take opposed
> roles: two judge independently whether two findings are even comparable, three
> argue competing explanations for why they disagree, and an adjudicator rules.
>
> They run on different training lineages on purpose. A council built from one
> model shares its blind spots — it would reproduce the exact flaw it's meant to
> detect.

---

## 0:50 – 1:35 · The run

**Screen:** terminal. Run it live — this is cached and fast:

```bash
python scripts/run_faultline.py "Does vitamin D supplementation prevent acute respiratory tract infections?"
```

Let the stage log scroll. Point at the calibration and screening lines.

> It starts by calibrating the field — establishing what counts as evidence
> here, rather than importing conventions from somewhere else. That's what lets
> the same system run on economics and psychology unchanged.
>
> Then it searches systematically and screens every paper locally. Watch the
> counts: this is a denominator. A chat model gives you eight papers and no idea
> what it missed — and you cannot detect a contradiction between studies you
> never retrieved.
>
> Screening is deliberately biased toward inclusion. A missed study looks
> exactly like consensus.

---

## 1:35 – 2:15 · The disagreement map

**Screen:** `reports/run_635b7bb33604.html`. Scroll to a conflict. Zoom on the
two claims and their qualifiers, then on the stance lines with lineage labels.

> Here's the output — not a summary, a map.
>
> These two trials genuinely disagree. One found vitamin D halved infection
> risk. The other found nothing. Both are real, and both are kept, with the
> qualifiers that make them comparable: population, dose, baseline status,
> follow-up.
>
> Three models then argue different explanations — each labelled with the
> lineage that produced it. Any stance citing no concrete study detail is
> flagged in red, because an explanation grounded in nothing is a
> rationalisation.
>
> The adjudicator ruled the split tracks dose and baseline status. The published
> Cochrane-style review on this exact question concluded the same thing —
> dosing regimen and baseline status. We reached it independently, from primary
> studies, with no access to that review.

---

## 2:15 – 2:40 · The failure case

**Screen:** terminal.

```bash
python scripts/test_veto.py
```

> Judging asks for a failure case, so here's the one that matters most.
>
> The hardest thing for a system like this is admitting it cannot explain
> something. A model that always finds an answer has learned to rationalise.
>
> Three constructed conflicts. The first has a real moderator — it explains it.
> The third is two different endpoints — it refuses to call it a conflict. The
> middle one is two trials identical in population, dose, measurement and
> design that still disagree.
>
> It returns *unresolved*. It refuses to invent an explanation — and that
> refusal is what produces a research gap.

---

## 2:40 – 3:00 · Cost and evidence

**Screen:** the cost table at the bottom of the report, then `evaluation/results.json`.

> Eight model lineages, and about one cent per run. Everything that scales with
> corpus size runs locally and unmetered; the paid models only ever see the
> handful of contested judgements.
>
> And it's measured — against published systematic reviews, not against test
> cases we wrote ourselves. Retrieval recall, false-conflict rate, and agreement
> with what the review authors concluded. The numbers are in the repo, including
> the ones that aren't flattering.
>
> Faultline. An LLM gives you a plausible answer. This gives you a defensible
> one.

---

## If you have to cut

Drop **0:00–0:25** to 12 seconds. Never cut the veto section — it is the most
distinctive thirty seconds in the video and directly answers the failure-case
criterion.
