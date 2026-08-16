/* Job 02 — hand a draft to three opposed reviewers. */

const state = { method: "upload", file: null };

mountDebris($("debris"));

const poller = runPoller({
  typicalStages: 15,
  onResult: (r) => { $("resultBody").innerHTML = reviewHTML(r); wireResult(); showPhase("result"); },
  onError: (e) => { $("resultBody").innerHTML = errorHTML(e); showPhase("result"); },
});

window.poller = poller;   // autopilot drives the demo through this

function setMethod(method) {
  state.method = method;
  for (const b of document.querySelectorAll("#methodTabs button")) {
    b.setAttribute("aria-selected", String(b.dataset.method === method));
  }
  $("dropzone").hidden = method !== "upload";
  $("pasteBox").hidden = method !== "paste";
  $("idBox").hidden = method !== "id";
}

async function submit() {
  const papers = +$("papers").value, year = +$("year").value;
  $("inputError").hidden = true;
  resetCancel();
  try {
    let res;
    if (state.method === "upload") {
      if (!state.file) return failInto("inputError", "Choose a file first.");
      const fd = new FormData();
      fd.append("file", state.file);
      $("runTitle").textContent = state.file.name;
      res = await fetch(`/api/review/upload?papers=${papers}&year=${year}`,
                        { method: "POST", body: fd }).then(r => r.json());
    } else {
      const source = state.method === "paste"
        ? $("pasteText").value.trim() : $("identifier").value.trim();
      if (!source) return failInto("inputError", "Paste your paper, or give a DOI.");
      $("runTitle").textContent = state.method === "id" ? source : "Your pasted draft";
      res = await post("/api/review", { source, papers, year });
    }
    if (!res || !res.jobId) {
      // Live runs are off on a public instance; offer the recording instead.
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

function reviewHTML(r) {
  const n = r.novelty || {}, base = r.base || {};
  const parts = [];

  parts.push(`<span class="mono">Review — ${esc(r.paper.meta)}</span>
    <h1 class="result-title">${esc(r.paper.title)}</h1>`);

  if (r.degraded) {
    parts.push(`<div class="note"><span class="tag">Degraded</span>
      <span class="msg">${esc(r.degraded)}</span></div>`);
  }

  parts.push(`<div class="counts">${r.counts.map(c => `
    <div class="cell"><span class="n${c.accent ? " accent" : ""}">${c.n}</span>
    <span class="k">${esc(c.label)}</span></div>`).join("")}</div>`);

  if (r.fatalAlert) {
    parts.push(`<div class="alert-fatal"><span class="tag">FATAL</span>
      <span class="msg">${esc(r.fatalAlert)}</span></div>`);
  }

  // Positioning needs literature; when the search degraded there is nothing
  // honest to say here, so the section is omitted rather than left empty.
  if (n.placement || n.draftSentence) {
    parts.push(`<div class="block">
      <div class="section-head">
        <h2 class="section">Where your contribution sits</h2>
        <span class="mono" style="display:flex;align-items:center;gap:10px">Novelty risk
          <span class="badge">${esc(n.verdict)}</span></span>
      </div>
      ${n.placement ? `<p class="prose">${esc(n.placement)}</p>` : ""}
      ${n.draftSentence ? `<div class="card">
        <div class="card-head"><span class="mono">Draft sentence — yours to use</span>
          <button class="chip-btn" id="copyBtn" data-copy="${esc(n.draftSentence)}">COPY</button></div>
        <p class="draft">${esc(n.draftSentence)}</p></div>` : ""}
      ${n.dismissalRisk ? `<div class="note"><span class="tag">RISK</span>
        <span class="msg">${esc(n.dismissalRisk)}</span></div>` : ""}
      ${(n.mustCite || []).length ? `<div style="margin-top:36px">
        <span class="mono">Must cite</span>
        <div class="rows">${n.mustCite.map(m => `<div class="row">
          <span class="t">${esc(m.title)}</span><span class="w">${esc(m.why)}</span></div>`).join("")}
        </div></div>` : ""}
    </div>`);
  }

  if ((r.panel || []).length) {
    parts.push(`<div class="panel-dark">
      <div style="display:flex;align-items:baseline;justify-content:space-between;gap:20px;flex-wrap:wrap">
        <h2 class="section">Reviewer panel</h2>
        <span class="mono" style="color:rgba(244,241,238,0.5)">Three lineages · no shared blind spots</span>
      </div>
      ${r.panel.map(g => `<div class="reviewer">
        <div class="head"><span class="name">${esc(g.name)}</span>
          <span class="lin">${esc(g.lineage)}</span></div>
        ${g.objections.map(o => `<div class="objection">
          <div class="top">
            <span class="sev sev-${esc(o.severity.toLowerCase())}">${esc(o.severity)}</span>
            <span class="text">${esc(o.text)}</span></div>
          ${o.fix ? `<div class="fixrow"><span class="k">MIN FIX</span>
            <span class="v">${esc(o.fix)}</span></div>` : ""}
        </div>`).join("")}
      </div>`).join("")}
    </div>`);
  }

  if (base.assessment) {
    parts.push(`<div class="block">
      <div class="section-head">
        <h2 class="section">The evidence base your paper sits in</h2>
        <span class="mono" style="display:flex;align-items:center;gap:10px">Quality
          <span class="badge outline">${esc(base.quality)}</span></span>
      </div>
      <p class="prose">${esc(base.assessment)}</p>
      <div class="split">
        <div class="cell"><span class="mono">Systemic issues</span>
          <div class="bullets">${(base.systemic || []).map(s =>
            `<div class="b"><span class="dash">—</span>${esc(s.text)}</div>`).join("")}</div></div>
        <div class="cell"><span class="mono">Construct validity</span>
          <p style="margin:14px 0 0;font-size:15.5px;line-height:1.5;color:rgba(19,18,17,0.8)">
            ${esc(base.construct)}</p></div>
      </div></div>`);
  }

  parts.push(`<div class="disclosure">
    <button data-toggle="claimsBody"><span class="t">Your claims as extracted</span>
      <span class="mono">SHOW — ${r.claims.length} CLAIMS</span></button>
    <div id="claimsBody" hidden style="padding-bottom:24px">
      <p class="mono" style="margin:0 0 18px">Check the tool read you correctly</p>
      ${r.claims.map(c => `<div class="claim">
        <div class="top"><span class="idx">C${esc(c.n)}</span>
          <span class="text">${esc(c.text)}</span>
          <span class="dir dir-${esc(c.direction)}">${esc(c.direction)}</span></div>
        <div class="meta">
          <div><span class="k">Population</span>${esc(c.population)}</div>
          <div><span class="k">Scope conditions</span>${esc(c.scope)}</div>
        </div></div>`).join("")}
    </div></div>`);

  parts.push(runbar(r.run));
  return parts.join("");
}

function wireResult() {
  wireDisclosures();
  const copy = $("copyBtn");
  if (copy) {
    copy.onclick = async () => {
      await navigator.clipboard.writeText(copy.dataset.copy);
      copy.textContent = "COPIED ✓";
    };
  }
}

/* --- wiring --- */

for (const b of document.querySelectorAll("#methodTabs button")) {
  b.onclick = () => setMethod(b.dataset.method);
}

$("papers").oninput = (e) => $("papersOut").textContent = e.target.value;
$("year").oninput = (e) => $("yearOut").textContent = e.target.value;
$("pasteText").oninput = (e) => $("charCount").textContent = `${e.target.value.length} characters`;
$("submitBtn").onclick = submit;
function resetCancel() {
  const b = $("cancelBtn");
  b.textContent = "RUN IN BACKGROUND";
  b.onclick = () => { poller.stop(); showPhase("input"); };
}
resetCancel();

const dz = $("dropzone");
$("fileInput").onchange = (e) => {
  state.file = e.target.files[0] || null;
  $("fileLabel").textContent = state.file ? state.file.name : "Drop your draft, or choose a file";
};
for (const ev of ["dragenter", "dragover"]) {
  dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("hot"); });
}
for (const ev of ["dragleave", "drop"]) {
  dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("hot"); });
}
dz.addEventListener("drop", (e) => {
  state.file = e.dataTransfer.files[0] || null;
  if (state.file) $("fileLabel").textContent = state.file.name;
});

for (const b of document.querySelectorAll("#phaseTabs button")) {
  b.onclick = () => {
    if (b.dataset.phase === "running" && !poller.jobId) return;
    if (b.dataset.phase === "result" && !$("resultBody").innerHTML) return;
    showPhase(b.dataset.phase);
  };
}

mountDemos({
  kind: "review",
  onPlay: (name, title) => openDemo(name, title, (r) => {
    $("resultBody").innerHTML = reviewHTML(r);
    wireResult();
  }),
});

setMethod("upload");
showPhase("input");
