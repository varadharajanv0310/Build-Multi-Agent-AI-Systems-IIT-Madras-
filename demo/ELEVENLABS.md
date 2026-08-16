# Getting an ElevenLabs API key

Exact steps, current as of the free tier. ~3 minutes.

## 1. Create the account

1. Go to **https://elevenlabs.io** and click **Sign up**.
2. Sign up with Google or email. Verify the email if prompted.
3. When asked what you're using it for, any answer is fine — it only tunes
   onboarding, not your quota.

The **Free** plan gives you **10,000 characters/month**, which is roughly
10 minutes of speech. A 3-minute narration is ~2,800 characters, so the free
tier covers the demo and several retakes.

> Free-tier audio carries an attribution requirement in ElevenLabs' terms.
> For a hackathon submission that's normally fine, but if you'd rather not
> attribute, the Starter plan (~$5/month, 30,000 chars) removes it and also
> unlocks commercial use. Check the current terms before you publish.

## 2. Create the key

1. Click your **profile icon** (bottom-left of the dashboard).
2. Choose **API Keys** (on some builds: *Profile + API key*).
3. Click **Create API Key**, name it `faultline-demo`.
4. **Copy it now** — ElevenLabs shows the full key exactly once.

The key looks like `sk_` followed by a long hex string.

## 3. Give it to the script

Add it to the project `.env` (already gitignored — the key never gets committed):

```
ELEVENLABS_API_KEY=sk_your_key_here
```

`capture_demo.ps1 -Narrate` reads `ELEVENLABS_API_KEY` from the environment and
falls back to `.env`, so either works.

## 4. Pick a voice (optional)

Default in the script is **George** (`JBFqnCBsd6RMkjVDRZzb`) — calm, neutral,
reads technical copy without overselling it.

To choose another: **Voices** in the sidebar → pick one → the **ID** is on the
voice's card (or via the "..." menu → *Copy voice ID*). Then:

```powershell
.\scripts\capture_demo.ps1 -Narrate -VoiceId <the-id>
```

Voices that suit a technical demo: **George**, **Brian**, **Charlotte**.
Avoid the highly expressive ones — they oversell, which works against a
submission whose whole argument is that it reports honestly.

## 5. Verify it works

```powershell
.\scripts\capture_demo.ps1 -Narrate -ScriptFile demo\narration.txt
```

Success prints the saved path and the duration. Match that duration against
your capture length before muxing.

## Quota check

Dashboard home shows characters used this month. `demo\narration.txt` is
~2,900 characters, so the free 10,000 allows about three full takes.
