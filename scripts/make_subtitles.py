"""Build subtitles for the demo by aligning the script to the narration audio.

Not guesswork: ElevenLabs leaves a clear gap between sentences, so the speech
segments are detected from the waveform envelope and the script is distributed
across them in proportion to how long each one actually lasts. That keeps the
captions on the voice even where the delivery speeds up or slows down, which
dividing the script by character count would not.

    python scripts/make_subtitles.py

Writes demo/recording/narration.srt.
"""
from __future__ import annotations

import array
import math
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from faultline.config import PROJECT_ROOT  # noqa: E402
from faultline.util import setup_console  # noqa: E402

AUDIO = PROJECT_ROOT / "demo" / "recording" / "narration.mp3"
SCRIPT = PROJECT_ROOT / "demo" / "narration.txt"
OUT = PROJECT_ROOT / "demo" / "recording" / "narration.srt"

# A caption should be readable at a glance: two short lines, on screen long
# enough to finish, and never so long it outlives the sentence it belongs to.
MAX_LINE = 42
MAX_LINES = 2
MIN_CUE = 1.0
MAX_CUE = 6.0

SILENCE_TH = 40.0     # envelope units; the noise floor sits near 1
MERGE_GAP = 0.24      # shorter than this is a breath, not a sentence break
MIN_SEG = 0.30


def ffmpeg() -> str:
    for p in Path(
        Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    ).rglob("ffmpeg.exe"):
        return str(p)
    return "ffmpeg"


def envelope(wav_path: Path) -> tuple[float, list[float]]:
    w = wave.open(str(wav_path))
    sr = w.getframerate()
    data = array.array("h", w.readframes(w.getnframes()))
    w.close()
    win = int(sr * 0.02)
    env = []
    for i in range(0, len(data) - win, win):
        s = data[i:i + win]
        env.append(math.sqrt(sum(x * x for x in s) / len(s)))
    return len(data) / sr, env


def speech_segments(env: list[float]) -> list[tuple[float, float]]:
    on = [e > SILENCE_TH for e in env]
    segs, i = [], 0
    while i < len(on):
        if on[i]:
            j = i
            while j < len(on) and on[j]:
                j += 1
            segs.append((i * 0.02, j * 0.02))
            i = j
        else:
            i += 1
    if not segs:
        return []
    merged = [segs[0]]
    for s, e in segs[1:]:
        if s - merged[-1][1] < MERGE_GAP:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return [(s, e) for s, e in merged if e - s > MIN_SEG]


def wrap(text: str) -> str:
    words, lines, cur = text.split(), [], ""
    for wd in words:
        if cur and len(cur) + 1 + len(wd) > MAX_LINE:
            lines.append(cur)
            cur = wd
        else:
            cur = f"{cur} {wd}".strip()
    if cur:
        lines.append(cur)
    # Never truncate. An earlier version clipped to a line budget here and
    # silently ate "Computing." out of the middle of a sentence — a caption
    # that drops words is worse than one that runs an extra line. Cues are
    # split to fit before they reach this point.
    return "\n".join(lines)


def ts(t: float) -> str:
    if t < 0:
        t = 0.0
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"


def main() -> int:
    setup_console()
    if not AUDIO.exists():
        print(f"missing {AUDIO}")
        return 1

    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "n.wav"
        subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(AUDIO), "-ac", "1", "-ar", "16000",
                        "-f", "wav", str(wav)], check=True)
        dur, env = envelope(wav)

    segs = speech_segments(env)
    words = SCRIPT.read_text(encoding="utf-8").split()
    total_speech = sum(e - s for s, e in segs)
    print(f"audio {dur:.2f}s | {len(segs)} speech segments | {len(words)} words")

    # Walk the segments, taking a share of the remaining words proportional to
    # each segment's share of the remaining speech time.
    def snap(i: int, lo: int, hi: int) -> int:
        """Nudge a split onto a clause boundary if one is close.

        Proportional splitting lands wherever the arithmetic says, which
        produces breaks like "two jobs on one / engine." Readers parse a cue
        far faster when it ends where the sentence pauses, so a split is moved
        up to two words to reach punctuation.
        """
        best, best_d = i, 99
        for j in range(max(lo + 1, i - 2), min(hi, i + 3)):
            if j <= lo or j > hi:
                continue
            if words[j - 1].rstrip('"\'').endswith((".", "!", "?")):
                d = abs(j - i) - 0.5      # full stops win ties
            elif words[j - 1].rstrip('"\'').endswith((",", ";", ":", "—")):
                d = abs(j - i)
            else:
                continue
            if d < best_d:
                best, best_d = j, d
        return best

    cues: list[tuple[float, float, str]] = []
    idx = 0
    spent = 0.0
    for k, (s, e) in enumerate(segs):
        spent += e - s
        target = round(len(words) * spent / total_speech)
        if k == len(segs) - 1:
            target = len(words)
        else:
            target = snap(target, idx, len(words))
        chunk = words[idx:target]
        idx = target
        if not chunk:
            continue
        cues.append((s, e, " ".join(chunk)))
    if idx < len(words) and cues:
        s, e, t = cues[-1]
        cues[-1] = (s, e, t + " " + " ".join(words[idx:]))

    # Split anything too long to read, and give short cues a little breathing
    # room without letting one overlap the next.
    budget = MAX_LINE * MAX_LINES
    final: list[tuple[float, float, str]] = []
    for i, (s, e, text) in enumerate(cues):
        span = e - s
        # Split on BOTH axes. Duration alone was not enough: a short segment
        # can still carry more text than two lines hold, and that overflow is
        # what used to get clipped.
        parts = max(math.ceil(span / MAX_CUE), math.ceil(len(text) / budget))
        if parts > 1:
            ws = text.split()
            per = math.ceil(len(ws) / parts)
            for p in range(parts):
                seg_words = ws[p * per:(p + 1) * per]
                if not seg_words:
                    continue
                final.append((s + span * p / parts,
                              s + span * (p + 1) / parts,
                              " ".join(seg_words)))
        else:
            nxt = cues[i + 1][0] if i + 1 < len(cues) else e + MIN_CUE
            final.append((s, min(max(e, s + MIN_CUE), nxt - 0.05), text))

    # The captions must contain the script, exactly. Verified rather than
    # trusted, because the failure mode is silent: a dropped word looks like a
    # normal caption to anyone who is not reading along with the source.
    emitted = " ".join(t for _, _, t in final).split()
    if emitted != words:
        print(f"WORD LOSS: script {len(words)} words, captions {len(emitted)}")
        for a, b in zip(words, emitted):
            if a != b:
                print(f"  first divergence: script {a!r} vs caption {b!r}")
                break
        return 1
    print(f"integrity: all {len(words)} words present, in order")

    lines = []
    for i, (s, e, text) in enumerate(final, 1):
        lines.append(f"{i}\n{ts(s)} --> {ts(e)}\n{wrap(text)}\n")
    OUT.write_text("\n".join(lines), encoding="utf-8")

    print(f"wrote {len(final)} cues -> {OUT}")
    print("\nfirst four:")
    for s, e, t in final[:4]:
        print(f"  {ts(s)} -> {ts(e)}  {t[:64]}")
    print("last two:")
    for s, e, t in final[-2:]:
        print(f"  {ts(s)} -> {ts(e)}  {t[:64]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
