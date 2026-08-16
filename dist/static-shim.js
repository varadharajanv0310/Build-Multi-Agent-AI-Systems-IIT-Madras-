/* Static build shim — replaces the Python API with local JSON.
 *
 * The public demo only ever replays recorded runs, and a replay is just a
 * stage list with timestamps. None of that needs a server, so the static
 * build intercepts the handful of /api/ routes the pages call and answers
 * them from files. Cloudflare Pages, GitHub Pages and Netlify can then host
 * the whole thing with no backend, no cold start and nothing to rate-limit.
 *
 * Loaded BEFORE common.js so every later fetch goes through it. The pages,
 * the poller and the autopilot are unmodified — they cannot tell the
 * difference, which is the point: one implementation, not two.
 */
(function () {
  const real = window.fetch.bind(window);
  const jobs = new Map();
  const cache = new Map();
  let gateAt = 0;

  const json = (body, status = 200) =>
    Promise.resolve(new Response(JSON.stringify(body), {
      status, headers: { "Content-Type": "application/json" },
    }));

  const LIVE_MSG =
    "This is the static public demo, so it replays recorded runs only. " +
    "Live runs need API keys and local models — clone the repo to do a real one.";

  function loadDemo(name) {
    if (cache.has(name)) return Promise.resolve(cache.get(name));
    return real(`demo/${name}.json`).then(r => {
      if (!r.ok) throw new Error("no such demo");
      return r.json();
    }).then(d => { cache.set(name, d); return d; });
  }

  window.fetch = function (input, init) {
    const url = typeof input === "string" ? input : (input && input.url) || "";
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    const method = ((init && init.method) || "GET").toUpperCase();
    if (!path.startsWith("/api/")) return real(input, init);

    // Live submission is genuinely unavailable here; say so rather than
    // hanging on a job that will never start.
    if (path === "/api/ask" || path === "/api/review" || path === "/api/review/upload") {
      return json({ detail: LIVE_MSG }, 503);
    }

    if (path === "/api/status") {
      return real("status.json").then(r => r.json()).then(s => json(s))
        .catch(() => json({ lineages: [], roster: {}, lineageByRole: {}, publicDemo: true }));
    }

    if (path === "/api/demo/gate") {
      if (method === "POST") { gateAt = Date.now() / 1000; return json({ firedAt: gateAt }); }
      if (method === "DELETE") { gateAt = 0; return json({ firedAt: 0 }); }
      return json({ firedAt: gateAt });
    }

    if (path === "/api/demo") {
      return real("demo/index.json").then(r => r.json()).then(l => json(l))
        .catch(() => json([]));
    }

    const start = path.match(/^\/api\/demo\/([A-Za-z0-9_-]+)$/);
    if (start && method === "POST") {
      const speed = Math.min(Math.max(
        parseFloat(new URLSearchParams(url.split("?")[1] || "").get("speed")) || 1,
        0.25), 20);
      const id = Math.random().toString(36).slice(2, 14);
      return loadDemo(start[1]).then(rec => {
        jobs.set(id, { rec, speed, started: Date.now() / 1000 });
        return json({ jobId: id });
      }).catch(() => json({ detail: "no such demo" }, 404));
    }

    const poll = path.match(/^\/api\/job\/([A-Za-z0-9_-]+)$/);
    if (poll && method === "GET") {
      const j = jobs.get(poll[1]);
      if (!j) return json({ detail: "unknown job" }, 404);
      const el = (Date.now() / 1000 - j.started) * j.speed;
      // Stages surface on their recorded offsets, exactly as the server
      // replays them, so the progress list behaves identically.
      const stages = j.rec.stages
        .filter(s => s.at <= el)
        .map(s => ({ label: s.label, at: Math.round(s.at) }));
      const done = el >= (j.rec.elapsed || 0);
      return json({
        id: poll[1], kind: j.rec.kind === "review" ? "review" : "answer",
        phase: done ? "result" : "running", title: j.rec.label || "",
        stages,
        warning: (j.rec.warning && stages.length >= 4) ? j.rec.warning : "",
        error: "",
        elapsed: Math.round(el / j.speed),
        replay: {
          recordedAt: j.rec.recordedAt || "", runId: j.rec.runId || "",
          originalElapsed: j.rec.elapsed || 0,
        },
        result: done ? j.rec.result : null,
      });
    }

    return json({ detail: "not available in the static demo" }, 404);
  };
})();
