/* Demo autopilot — drives the whole 2:42 demo on a fixed schedule.
 *
 * The problem this solves: the narration is synthesised ahead of time, so the
 * picture has to hit its marks to the second or the voice describes something
 * that is not on screen yet. Hand-driving a browser cannot do that repeatably.
 * This can — every cue is an absolute offset from t=0.
 *
 * Cues come from demo/cues.txt, derived from the measured narration:
 *
 *     ACT 1  landing      0.0 ->  17.2   the site, scrolled
 *     ACT 2  paper       17.2 ->  75.1   SEVA reviewed
 *     ACT 3  question    75.1 -> 132.5   creatine answered
 *     ACT 4  close      132.5 -> 160.2   stack, cost, sign-off
 *
 * Because a page navigation resets the clock, each page reads `t` from the URL
 * — the offset it is being entered at — and schedules relative to that.
 *
 * Usage: open /?autopilot=1 , start recording, reload. It does the rest.
 */
(function () {
  const params = new URLSearchParams(location.search);
  if (!params.has("autopilot")) return;

  const SPEED = Math.max(0.25, Math.min(8, +params.get("speed") || 1));
  const LEAD = params.has("lead") ? +params.get("lead") : 5;
  const T = +params.get("t") || 0;          // offset this page is entered at
  const page = location.pathname;

  const t0 = performance.now();
  let anchor = t0;              // when this page's local timeline started

  // Schedule against the GLOBAL timeline; `abs` is seconds from narration t=0.
  //
  // The elapsed-time subtraction is the whole point. setTimeout counts from
  // when it is CALLED, so cues registered later — the ones inside onResult,
  // which only runs once a replay finishes — were firing a full 30s late and
  // landing after the page had already navigated on. Subtracting the time
  // already spent on this page makes a cue mean the same thing no matter when
  // it is registered.
  const cue = (abs, fn) => {
    const target = (abs - T) * 1000 / SPEED + (page === "/" ? LEAD * 1000 : 0);
    const elapsed = performance.now() - anchor;
    setTimeout(fn, Math.max(0, target - elapsed));
  };

  // --- operator HUD (never in frame: bottom-right, small) -------------------
  const hud = document.createElement("div");
  hud.style.cssText =
    "position:fixed;bottom:14px;right:14px;z-index:9999;padding:7px 13px;" +
    "border-radius:100px;background:rgba(19,18,17,.82);color:#f4f1ee;" +
    "font:500 10px/1 'IBM Plex Mono',monospace;letter-spacing:.12em;" +
    "border:1px solid rgba(232,72,15,.55);pointer-events:none";
  document.body.appendChild(hud);
  // The HUD exists only to tell the operator when to hit record. It is inside
  // the capture rectangle, so it must be gone before the first frame that
  // matters — it hides itself the moment the countdown reaches zero.
  const hudTimer = setInterval(() => {
    const el = (performance.now() - t0) / 1000 * SPEED
             - (page === "/" ? LEAD : 0) + T;
    if (el >= 0) { hud.remove(); clearInterval(hudTimer); return; }
    hud.textContent = `RECORD NOW — ${Math.ceil(-el)}`;
  }, 100);

  function glide(to, ms) {
    const from = window.scrollY, start = performance.now();
    const step = (now) => {
      const p = Math.min(1, (now - start) / (ms / SPEED));
      const e = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
      window.scrollTo(0, from + (to - from) * e);
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  const doc = () => document.documentElement.scrollHeight - window.innerHeight;
  const go = (path, at) =>
    (location.href = `${path}?autopilot=1&t=${at}&speed=${SPEED}&lead=0`);


  function run() {
    /* ---------------- still mode — one page, one state ----------------
     * For documentation screenshots. `still=1` skips the timeline entirely:
     * it replays a recorded run at maximum speed, holds on the result, and
     * optionally scrolls to a fraction of the page. No navigation, no cues.
     *   /review?autopilot=1&still=1&demo=seva&scroll=0.3
     */
    if (params.has("still")) {
      const scroll = parseFloat(params.get("scroll") || "0");
      const d = params.get("demo");
      const settle = () => setTimeout(() => {
        if (scroll > 0) window.scrollTo(0, doc() * scroll);
      }, 900);
      if (!d) return settle();
      fetch(`/api/demo/${d}?speed=20`, { method: "POST" })
        .then(r => r.json())
        .then(j => {
          if (j.jobId && window.poller) poller.start(j.jobId);
          const iv = setInterval(() => {
            const v = document.getElementById("viewResult");
            if (v && !v.hidden && document.getElementById("resultBody").innerHTML) {
              clearInterval(iv);
              // Open the disclosures so a screenshot shows the detail, not
              // two collapsed rows.
              if (params.has("open")) {
                for (const b of document.querySelectorAll("[data-toggle]")) b.click();
              }
              settle();
            }
          }, 120);
        });
      return;
    }

    /* ---------------- ACT 1 + ACT 4 — the landing page ---------------- */
    if (page === "/" || page.endsWith("landing.html")) {
      if (T === 0) {
        // Opening: hero, the two jobs, the lineages, the run.
        cue(0.0, () => window.scrollTo(0, 0));
        cue(3.5, () => glide(doc() * 0.15, 3000));   // "two jobs, one engine"
        cue(8.0, () => glide(doc() * 0.38, 3000));   // seven lineages
        cue(12.5, () => glide(doc() * 0.62, 2800));  // the run
        cue(17.2, () => go("/review", 17.2));
      } else {
        // Closing act: the stack paragraph plays over the traceability band,
        // then the closer carries the sign-off.
        cue(132.5, () => window.scrollTo(0, doc() * 0.38));
        cue(134.0, () => glide(doc() * 0.62, 3500));   // lineages / run
        cue(144.3, () => glide(doc() * 0.86, 4000));   // traceability
        cue(155.1, () => glide(doc(), 3500));          // "Put a claim under pressure"
      }
      return;
    }

    /* ---------------- ACT 2 / ACT 3 — a recorded run ---------------- */
    const demo = params.get("demo") || (page === "/review" ? "seva" : "question");
    // Replays are time-compressed to fit their segment; the REPLAY badge stays
    // up throughout, so a compressed replay is never mistaken for a live run.
    const compress = +params.get("compress") || (demo === "seva" ? 4.0 : 2.2);

    cue(T + 0.6, () => {
      fetch(`/api/demo/${demo}?speed=${compress * SPEED}`, { method: "POST" })
        .then(r => r.json())
        .then(j => { if (j.jobId && window.poller) poller.start(j.jobId); });
    });

    const onResult = (fn) => {
      const iv = setInterval(() => {
        const v = document.getElementById("viewResult");
        if (v && !v.hidden && document.getElementById("resultBody").innerHTML) {
          clearInterval(iv); fn();
        }
      }, 120);
      setTimeout(() => clearInterval(iv), 90000);
    };

    if (demo === "seva") {
      // Paper: land on the result ~47s, walk the panel while the objections
      // are being read, hand off to the question at 75.1.
      onResult(() => {
        cue(47.4, () => glide(0, 400));                 // title + counts
        cue(50.0, () => glide(doc() * 0.34, 3000));     // reviewer panel
        cue(56.0, () => glide(doc() * 0.50, 3000));     // method objection
        cue(64.0, () => glide(doc() * 0.66, 3200));     // significance objection
        cue(70.0, () => glide(doc() * 0.82, 2800));     // appraisal
      });
      cue(75.1, () => go("/ask", 75.1));
    } else {
      // Question: headline and readout, then the five conditions, then the
      // evidence list and the corpus funnel under the "denominator" line.
      onResult(() => {
        cue(89.0, () => glide(0, 400));                 // headline + readout
        cue(96.6, () => glide(doc() * 0.28, 3000));     // "It depends on"
        cue(101.0, () => glide(doc() * 0.42, 3500));    // the five axes
        cue(118.1, () => {
          const btn = document.querySelector('[data-toggle="evidenceBody"]');
          if (btn) btn.click();                          // evidence, with sources
          setTimeout(() => glide(doc() * 0.62, 2600), 600 / SPEED);
        });
        cue(125.0, () => {
          const btn = document.querySelector('[data-toggle="corpusBody"]');
          if (btn) btn.click();                          // the funnel
          setTimeout(() => glide(doc() * 0.86, 2800), 600 / SPEED);
        });
      });
      cue(132.5, () => go("/", 132.5));
    }
  }

  // `gate=1` holds the first page until the recorder fires /api/demo/gate, so
  // t=0 is a moment we chose rather than one we estimated. Later pages in the
  // chain carry their offset in `t` and start immediately.
  function begin() {
    if (!params.has("gate") || T > 0) { run(); return; }
    hud.textContent = "ARMED — WAITING FOR RECORDER";
    const poll = setInterval(() => {
      fetch("/api/demo/gate").then(r => r.json()).then(g => {
        if (g.firedAt) {
          clearInterval(poll);
          clearInterval(hudTimer);
          hud.remove();
          anchor = performance.now();   // t=0 is the moment the gate fired
          run();
        }
      }).catch(() => {});
    }, 150);
  }

  if (document.readyState === "complete") begin();
  else window.addEventListener("load", begin);
})();
