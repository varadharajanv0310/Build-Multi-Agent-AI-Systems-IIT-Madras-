/* Job 01 — ask a question, answer it from the papers. */

const EXAMPLES = [
  "Does creatine improve cognition in healthy adults?",
  "What dose of vitamin D raises serum 25(OH)D above 30 ng/mL?",
  "Is intermittent fasting better than caloric restriction?",
];

mountDebris($("debris"));

const poller = runPoller({
  typicalStages: 8,
  onResult: (r) => { $("resultBody").innerHTML = answerHTML(r); wireResult(); showPhase("result"); },
  onError: (e) => { $("resultBody").innerHTML = errorHTML(e); showPhase("result"); },
});

window.poller = poller;   // autopilot drives the demo through this

async function submit() {
  const question = $("question").value.trim();
  $("inputError").hidden = true;
  if (!question) return failInto("inputError", "Type a question first.");
  resetCancel();
  $("runTitle").textContent = question;
  try {
    const res = await post("/api/ask", {
      question, papers: +$("papers").value, year: +$("year").value,
    });
    if (!res || !res.jobId) {
      // On a public instance live runs are off. Say so, then hand the visitor
      // the recorded run rather than leaving them at a dead end.
      failInto("inputError", res?.detail || "Could not start the run.");
      const strip = $("demoStrip");
      if (strip && !strip.hidden) strip.classList.add("nudge");
      return;
    }
    poller.start(res.jobId);
  } catch (e) {
    failInto("inputError", String(e));
  }
}

function answerHTML(r) {
  const c = r.corpus || {};
  const insufficient = String(r.confidence).startsWith("insufficient");
  const parts = [];

  parts.push(`<div style="display:flex;align-items:baseline;justify-content:space-between;gap:20px;flex-wrap:wrap">
    <span class="mono">Answer</span>
    <span class="mono" style="color:var(--muted-soft)">${esc(r.question || "")}</span>
  </div>
  <h1 class="headline">${esc(r.headline)}</h1>`);

  parts.push(`<div class="readout">
    <div class="cell"><span class="k">CONFIDENCE</span>
      <div class="v"><span class="dot"></span>${esc(r.confidence)}</div></div>
    <div class="cell"><span class="k">CONSENSUS</span>
      <div class="v"><span class="dot"></span>${esc(r.consensus)}</div></div>
    <div class="cell"><span class="k">FINDINGS USED</span>
      <div class="v">${r.evidence.length}</div></div>
  </div>`);

  if (insufficient) {
    parts.push(`<div class="note"><span class="tag">HONEST</span><span class="msg">
      The retrieved evidence does not settle this question. That is reported
      rather than dressed up as a confident answer.</span></div>`);
  }
  if (r.answer) parts.push(`<p class="prose" style="margin-top:36px">${esc(r.answer)}</p>`);

  if ((r.caveats || []).length) {
    parts.push(`<div class="block"><h2 class="section">It depends on</h2>
      <div class="conditions">${r.caveats.map(c => `<div class="c">
        <span class="axis">${esc(c.axis)}</span>
        <span class="text">${esc(c.text)}</span></div>`).join("")}</div></div>`);
  }

  if ((r.disagreements || []).length) {
    parts.push(`<div class="disagree"><h2>Where studies disagree</h2>
      ${r.disagreements.map(d => `<div class="d">
        <div class="dhead"><span class="tag">CONTESTED</span>
          <span class="dtext">${esc(d.text)}</span></div>
        ${d.refs ? `<p class="refs">${esc(d.refs)}</p>` : ""}
      </div>`).join("")}</div>`);
  }

  if ((r.whatWouldSettleIt || []).length) {
    parts.push(`<div class="settle"><h2>What would settle it</h2>
      ${r.whatWouldSettleIt.map((w, i) => `<div class="w">
        <span class="n">${String(i + 1).padStart(2, "0")}</span>${esc(w)}</div>`).join("")}</div>`);
  }

  parts.push(`<div class="disclosure">
    <button data-toggle="evidenceBody"><span class="t">Evidence list</span>
      <span class="mono">SHOW — ${r.evidence.length} FINDINGS</span></button>
    <div id="evidenceBody" hidden style="padding-bottom:24px">
      ${r.evidence.map((e, i) => `<div class="evidence">
        <div class="top">
          <span class="n">[${i + 1}]</span>
          <span class="finding">${esc(e.text)}</span>
          <span class="claim-dir dir dir-${esc(e.direction)}">${esc(e.direction)}</span>
        </div>
        <div class="meta">
          <div><span class="k">EFFECT SIZE</span>${esc(e.magnitude || "not reported")}</div>
          <div><span class="k">POPULATION</span>${esc(e.population || "not reported")}</div>
          <div><span class="k">OUTCOME MEASURED</span>${esc(e.outcome || "not reported")}</div>
          <div><span class="k">SOURCE</span>${esc(e.source || "—")}</div>
        </div></div>`).join("")}
    </div></div>`);

  parts.push(`<div class="disclosure" style="margin-top:0">
    <button data-toggle="corpusBody"><span class="t">How this corpus was built</span>
      <span class="mono">SHOW</span></button>
    <div id="corpusBody" hidden style="padding:4px 0 34px">
      <div class="dbchips">${(c.databases || []).map(d =>
        `<span class="dbchip"><span class="dot"></span>${esc(d)}</span>`).join("")}</div>
      <div class="funnel">
        <div class="f"><span class="n">${c.raw}</span><span class="k">RETRIEVED</span></div>
        <div class="f"><span class="n">${c.unique}</span><span class="k">UNIQUE</span></div>
        <div class="f"><span class="n">${c.screened}</span><span class="k">SCREENED</span></div>
        <div class="f"><span class="n accent">${c.included}</span><span class="k">INCLUDED</span></div>
        <div class="f"><span class="n">${c.borderline}</span><span class="k">BORDERLINE</span></div>
        <div class="f"><span class="n dim">${c.excluded}</span><span class="k">EXCLUDED</span></div>
      </div>
      <div class="fieldbox">
        <span class="mono">FIELD IDENTIFIED</span>
        <p>${esc(c.field || "not calibrated")}</p>
      </div>
      <p class="mono" style="margin-top:16px;text-transform:none;letter-spacing:0.04em">
        The denominator is the point — a chat model gives you a handful of papers
        and no idea what it missed.</p>
    </div></div>`);

  parts.push(runbar(r.run));
  return parts.join("");
}

function wireResult() { wireDisclosures(); }

/* --- wiring --- */

$("examples").insertAdjacentHTML("beforeend", EXAMPLES.map(
  t => `<button type="button">${esc(t)}</button>`).join(""));
for (const b of $("examples").querySelectorAll("button")) {
  b.onclick = () => { $("question").value = b.textContent; $("question").focus(); };
}

$("papers").oninput = (e) => $("papersOut").textContent = e.target.value;
$("year").oninput = (e) => $("yearOut").textContent = e.target.value;
$("submitBtn").onclick = submit;
$("question").onkeydown = (e) => { if (e.key === "Enter") submit(); };
function resetCancel() {
  const b = $("cancelBtn");
  b.textContent = "RUN IN BACKGROUND";
  b.onclick = () => { poller.stop(); showPhase("input"); };
}
resetCancel();

for (const b of document.querySelectorAll("#phaseTabs button")) {
  // Tabs navigate between phases that already exist; they never fabricate one.
  b.onclick = () => {
    if (b.dataset.phase === "running" && !poller.jobId) return;
    if (b.dataset.phase === "result" && !$("resultBody").innerHTML) return;
    showPhase(b.dataset.phase);
  };
}

mountDemos({
  kind: "answer",
  onPlay: (name, title) => openDemo(name, title, (r) => {
    $("resultBody").innerHTML = answerHTML(r);
    wireResult();
  }),
});

showPhase("input");
