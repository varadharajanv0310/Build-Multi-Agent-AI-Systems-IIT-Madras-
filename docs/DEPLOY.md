# Deploying a live link

## Read this first

Faultline is built around **local inference**. Four roles — screening, query
expansion, extraction and one side of the commensurability pair — plus every
failover chain run on Ollama. That is not incidental: screening issues one
model call per retrieved paper, and running that volume locally is what makes
a full run cost **$0.00** and 82–95% local.

No free web host has a GPU. So a deployed instance is one of two things, and
it is worth being clear which one you are publishing.

| Mode | Env | Needs keys | Live runs | Good for |
|---|---|---|---|---|
| **Public demo** | `FAULTLINE_PUBLIC_DEMO=1` | no | no — replays only | the link you put on a submission |
| **Hosted-only** | `FAULTLINE_HOSTED_ONLY=1` | yes | yes, small runs | a private instance you control |
| **Local** | neither | yes | yes, full | actually using it |

**Recommended for the hackathon: public demo.** It has no keys to leak, no
quota to exhaust, and cannot break while a judge is looking at it. It serves
the real UI and replays the two recorded runs — labelled on screen with their
run ids — and points anyone who wants a live run at the repo.

> Publishing `FAULTLINE_HOSTED_ONLY=1` on a public URL means strangers spend
> **your** Groq and OpenRouter quota. A rate-limited key then breaks the demo
> for the judges you published it for. Don't.

---

## Option A — Render (simplest, free)

1. Push to GitHub (already done).
2. Go to **https://render.com** → sign in with GitHub → **New → Web Service**.
3. Pick the `FAULTLINE` repo. Render detects the `Dockerfile`.
4. Settings:
   - **Instance type**: Free
   - **Environment variable**: `FAULTLINE_PUBLIC_DEMO` = `1`
5. **Create Web Service.** First build takes ~3–5 minutes.

You get `https://faultline-xxxx.onrender.com`.

Free instances **sleep after 15 minutes idle** and take ~50s to wake. Before
judging, open the link once to warm it, or use a free uptime pinger.

## Option B — Fly.io (no sleep on the free allowance)

```bash
fly launch --no-deploy --name faultline
```

```bash
fly secrets set FAULTLINE_PUBLIC_DEMO=1
```

```bash
fly deploy
```

Gives `https://faultline.fly.dev`. Fly keeps a machine warm longer than
Render's free tier, which matters if judges arrive unannounced.

## Option C — Hugging Face Spaces

Good fit for an AI submission and the URL reads well.

1. **https://huggingface.co/new-space** → SDK **Docker** → public.
2. Push this repo to the Space remote.
3. Space **Settings → Variables**: `FAULTLINE_PUBLIC_DEMO` = `1`.
4. Add `app_port: 8000` to the Space `README.md` front matter.

## Option D — a tunnel, for live runs during judging

The only way to show a **real** run — local models, $0.00, the full design —
is to serve it from the machine that has Ollama.

```bash
cloudflared tunnel --url http://localhost:8000
```

Prints a temporary `https://<random>.trycloudflare.com`. No account needed.
Runs only while your machine is on and the command is running, so use it live
in a call, not as the link on the submission.

---

## Verify a deployment

```bash
curl -s https://YOUR-URL/api/status
```

`publicDemo: true` confirms the safe mode is on. Then:

```bash
curl -s -X POST https://YOUR-URL/api/ask -H "Content-Type: application/json" -d "{\"question\":\"test\"}"
```

Should return **503** with the "recorded runs only" message. If it starts a
job instead, `FAULTLINE_PUBLIC_DEMO` did not take and your keys are exposed.

Finally open the URL and click through — the landing page, then a recorded run
from `/review` and `/ask`.

---

## What a visitor sees on the public demo

- The full UI: landing, ask, review, all three real pages
- Two recorded runs they can replay themselves, at real recorded timings
- A **REPLAY OF A RECORDED RUN** badge carrying the original run id and date
- A 503 with an explanation if they try to submit their own paper

That last one is deliberate. A demo that quietly does nothing when you press
the button is worse than one that tells you why.
