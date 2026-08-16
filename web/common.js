/* Shared helpers for the three Faultline pages.
   Runs take 30–150s, so every submit returns a job id and the page polls it. */

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const post = (url, body) => fetch(url, {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
}).then(r => r.json());

/* Decorative debris inside the progress sphere. Deterministic placement so the
   sphere looks identical on every load rather than reshuffling. */
function mountDebris(host, count = 30) {
  if (!host) return;
  for (let i = 0; i < count; i++) {
    const a = (i / count) * Math.PI * 2 + i * 0.7;
    const r = 10 + ((i * 37) % 32);
    const size = 2 + ((i * 13) % 7);
    const s = document.createElement("span");
    Object.assign(s.style, {
      position: "absolute",
      left: `${50 + Math.cos(a) * r}%`,
      top: `${50 + Math.sin(a) * r * 0.9}%`,
      width: `${size}px`, height: `${size}px`,
      borderRadius: size > 5 ? "2px" : "50%",
      background: i % 4 === 0 ? "#ff7a3c" : "rgba(244,241,238,0.55)",
      filter: i % 3 === 0 ? "blur(1px)" : "none",
      animation: `fl-drift ${8 + (i % 7)}s ease-in-out ${i * 0.2}s infinite`,
    });
    host.appendChild(s);
  }
}

function showPhase(phase) {
  for (const p of ["input", "running", "result"]) {
    const el = $("view" + p[0].toUpperCase() + p.slice(1));
    if (el) el.hidden = p !== phase;
  }
  for (const b of document.querySelectorAll("#phaseTabs button")) {
    b.setAttribute("aria-selected", String(b.dataset.phase === phase));
  }
  window.scrollTo({ top: 0, behavior: "instant" });
}

/* The stage count varies by mode and by how retrieval goes, so progress is
   estimated against a typical run rather than faked as a fixed countdown. */
function runPoller({ typicalStages, onResult, onError }) {
  let timer = null, jobId = null;

  const tick = async () => {
    let job;
    try { job = await fetch(`/api/job/${jobId}`).then(r => r.json()); }
    catch { return; }

    const clock = $("runClock");
    if (clock) clock.textContent = `RUNNING — ${String(job.elapsed).padStart(2, "0")}S / ~90S`;

    $("stageList").innerHTML = job.stages.map((s, i) => {
      const active = i === job.stages.length - 1 && job.phase === "running";
      return `<div class="row${active ? " active" : ""}">
        <span class="mark">${active ? "▸" : "✓"}</span>${esc(s.label)}
        <span class="rule"></span>
        <span class="at">${String(s.at).padStart(2, "0")}s</span></div>`;
    }).join("");

    if (job.warning) {
      $("runWarningText").textContent = job.warning;
      $("runWarning").hidden = false;
    }

    const pct = Math.min(96, Math.round((job.stages.length / typicalStages) * 100));
    $("sphereFill").style.height = `${Math.round(pct * 0.92)}%`;
    $("spherePct").textContent = `${pct}%`;

    if (job.phase === "result" && job.result) { stop(); onResult(job.result); }
    else if (job.phase === "error") { stop(); onError(job.error); }
  };

  const stop = () => { clearInterval(timer); timer = null; };

  return {
    start(id) {
      jobId = id;
      $("stageList").innerHTML = "";
      $("runWarning").hidden = true;
      $("sphereFill").style.height = "0%";
      $("spherePct").textContent = "0%";
      showPhase("running");
      stop();
      timer = setInterval(tick, 700);
      tick();
    },
    stop,
    get jobId() { return jobId; },
  };
}

function failInto(id, message) {
  const el = $(id);
  el.textContent = message;
  el.hidden = false;
}

function errorHTML(message) {
  return `<span class="mono">Run failed</span>
    <h1 class="result-title">The run could not finish.</h1>
    <div class="note"><span class="tag">Error</span><span class="msg">${esc(message)}</span></div>
    <div class="runbar"><button class="chip-btn" onclick="location.reload()">START OVER</button></div>`;
}

function runbar(run, extra = "") {
  const local = Math.round((run.localShare || 0) * 100);
  return `<div class="runbar">
    <span>${run.modelCalls} MODEL CALLS</span>
    <span>${local}% RUN LOCALLY</span>
    <span>COST ${esc(run.cost)}</span>
    ${extra}
    <button class="chip-btn" onclick="location.reload()">NEW RUN</button>
  </div>`;
}

/* Disclosure sections share one behaviour: toggle the body, swap SHOW/HIDE. */
function wireDisclosures(root = document) {
  for (const btn of root.querySelectorAll("[data-toggle]")) {
    btn.onclick = () => {
      const body = root.querySelector(`#${btn.dataset.toggle}`);
      body.hidden = !body.hidden;
      const label = btn.querySelector(".mono");
      if (label) {
        label.textContent = body.hidden
          ? label.textContent.replace("HIDE", "SHOW")
          : label.textContent.replace("SHOW", "HIDE");
      }
    };
  }
}
