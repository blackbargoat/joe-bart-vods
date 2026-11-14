#!/usr/bin/env python3
"""edit-bot (Remotion): cut a moment from a 16:9 Joe Bart VOD and render a 9:16 Short.

Layout: facecam cropped to fill the top 37%, gameplay cropped in tight on the bottom 63%,
bold word-by-word captions (spoken word in yellow) on the seam, quick punch-in zooms on the
loudest reactions. Nothing is squashed or letterboxed.

One-time setup on a fresh container:  bash /mnt/project-files/edit-bot/setup.sh

Check the facecam box first (writes one PNG of the finished layout):
  python3 -I make_short.py --vod vod.mp4 --start 1:52:10 --end 1:52:45 --cam 1500:20:400:260 --still check.png
Render:
  python3 -I make_short.py --vod vod.mp4 --start 1:52:10 --end 1:52:45 --cam 1500:20:400:260 \
      --id rage01 [--no-captions] [--no-zoom] [--hook "TEXT"]
Batch from a planner-bot plan (same fields per clip, see style-guide.md):
  python3 -I make_short.py --plan plan.json

Captions: local speech-to-text with sherpa-onnx + NVIDIA Parakeet TDT 0.6B v2 (int8),
model in models/. No internet needed once set up.
"""
import argparse, json, os, re, shutil, subprocess, sys, time, wave

HERE = os.path.dirname(os.path.abspath(__file__))
RDIR = os.environ.get("REMOTION_DIR", "/home/user/edit-bot-remotion")
CHROME = os.environ.get("CHROME_BIN", "/home/user/chrome-dl/chrome-headless-shell-linux64/chrome-headless-shell")
# Big files do not stay in the shared project folder, so the model lives on local disk (setup.sh fetches it).
MODEL = os.environ.get("PARAKEET_DIR", "/home/user/models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8")
OUTDIR = os.path.join(HERE, "output")


def ts(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = 0.0
    for p in str(v).split(":"):
        s = s * 60 + float(p)
    return s


def rect(v):
    if not v:
        return None
    if isinstance(v, (list, tuple)):
        return [int(x) for x in v]
    return [int(x) for x in re.split(r"[:,x ]+", str(v).strip())]


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:format=duration", "-of", "json", path],
                         capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    return d["streams"][0]["width"], d["streams"][0]["height"], float(d["format"]["duration"])


def cut(vod, start, end, dst):
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-i", vod]
    if end:
        cmd += ["-t", str(end - start)]
    cmd += ["-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", dst]
    run(cmd)


def wav16k(src, dst):
    run(["ffmpeg", "-v", "error", "-y", "-i", src, "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", dst])


def transcribe(wav_path):
    import numpy as np
    import sherpa_onnx
    rec = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=os.path.join(MODEL, "encoder.int8.onnx"),
        decoder=os.path.join(MODEL, "decoder.int8.onnx"),
        joiner=os.path.join(MODEL, "joiner.int8.onnx"),
        tokens=os.path.join(MODEL, "tokens.txt"),
        model_type="nemo_transducer", num_threads=4)
    with wave.open(wav_path) as w:
        sr = w.getframerate()
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    words = []
    # ~20 s windows keep memory flat; cut each at the quietest moment near the 20 s mark
    # so no word is split across windows (split words came out as wrong captions).
    bounds, off, hop = [], 0, sr // 10
    while off < len(audio):
        end = off + 20 * sr
        if end >= len(audio) - 5 * sr:
            end = len(audio)
        else:
            lo, hi = end - 4 * sr, end + 4 * sr
            e = [float(np.mean(audio[i:i + hop] ** 2)) for i in range(lo, hi, hop)]
            end = lo + int(np.argmin(e)) * hop + hop // 2
        bounds.append((off, end))
        off = end
    for off, end in bounds:
        chunk = audio[off:end]
        if len(chunk) < sr // 2:  # skip a tail shorter than 0.5 s
            continue
        st = rec.create_stream()
        st.accept_waveform(sr, chunk)
        rec.decode_stream(st)
        r = st.result
        base = off / sr
        cur = None
        for tok, t in zip(r.tokens, r.timestamps):
            starts_word = tok.startswith(" ") or tok.startswith("▁") or cur is None
            piece = tok.replace("▁", " ")
            if starts_word and piece.strip():
                if cur:
                    words.append(cur)
                cur = {"start": round(base + t, 3), "end": round(base + t + 0.25, 3), "text": piece.strip()}
            elif cur:
                cur["text"] += piece.strip()
                cur["end"] = round(base + t + 0.2, 3)
        if cur:
            words.append(cur)
    for a, b in zip(words, words[1:]):
        a["end"] = round(min(max(a["end"], a["start"] + 0.12), b["start"]), 3)
    return words


def loud_peaks(wav_path, n_max, min_gap=4.0):
    """Big reactions = short windows much louder than the clip's usual level."""
    import numpy as np
    with wave.open(wav_path) as w:
        sr = w.getframerate()
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    win = int(0.1 * sr)
    if len(a) < win * 10:
        return []
    rms = np.sqrt(np.mean(a[: len(a) // win * win].reshape(-1, win) ** 2, axis=1) + 1e-9)
    db = 20 * np.log10(rms)
    smooth = np.convolve(db, np.ones(3) / 3, mode="same")
    voiced = smooth[smooth > -45]
    base = np.median(voiced) if len(voiced) else np.median(smooth)
    thresh = base + 14  # screams/yells sit ~15-25 dB over normal talk; normal peaks ~12
    order = np.argsort(-smooth)
    picks = []
    for i in order:
        if len(picks) >= n_max or (smooth[i] < thresh and (picks or smooth[i] < base + 10)):
            break
        t = i * 0.1
        if t < 0.5 or all(abs(t - p) >= min_gap for p in picks):
            picks.append(t)
    return [{"at": round(max(0, t - 0.15), 2), "dur": 0.9, "scale": 1.28} for t in sorted(picks)]


def render(job):
    jid = job.get("id") or time.strftime("clip-%Y%m%d-%H%M%S")
    start, end = ts(job.get("start")) or 0.0, ts(job.get("end"))
    pub = os.path.join(RDIR, "public")
    clip_name = f"src-{jid}.mp4"
    clip = os.path.join(pub, clip_name)
    t0 = time.time()
    cut(job["vod"], start, end, clip)
    sw, sh, dur = probe(clip)
    props = {"clip": clip_name, "sourceW": sw, "sourceH": sh, "durationSec": round(dur, 3),
             "cam": rect(job.get("cam")), "game": rect(job.get("game")),
             "split": float(job.get("split", 0.37)), "words": [], "captions": False,
             "zooms": [], "hook": job.get("hook")}
    need_audio = job.get("captions", True) or job.get("zoom", True)
    if need_audio and not job.get("still"):
        wav = os.path.join(pub, f"src-{jid}.wav")
        wav16k(clip, wav)
        if job.get("captions", True):
            if job.get("words"):  # whole-VOD transcript (VOD seconds), done once per VOD
                allw = json.load(open(job["words"]))
                props["words"] = [{"start": round(w["start"] - start, 3), "end": round(w["end"] - start, 3),
                                   "text": w["text"]} for w in allw
                                  if w["start"] >= start - 0.05 and w["end"] <= (end or 1e9) + 0.05]
            else:
                props["words"] = transcribe(wav)
            props["captions"] = True
        if job.get("zoom", True):
            props["zooms"] = job.get("zooms") or loud_peaks(wav, n_max=max(1, int(dur // 8)))
        os.remove(wav)
    t1 = time.time()
    os.makedirs(OUTDIR, exist_ok=True)
    pfile = os.path.join(OUTDIR, f"{jid}.props.json")
    json.dump(props, open(pfile, "w"), indent=1)
    base = ["npx", "remotion"]
    common = ["src/index.ts", "JoeBartShort", f"--props={pfile}", f"--browser-executable={CHROME}"]
    if job.get("still"):
        frame = int(float(job.get("still_at", 1.0)) * 30)
        run(base + ["still"] + common[:2] + [job["still"]] + common[2:] + [f"--frame={frame}"], cwd=RDIR)
        os.remove(clip)
        return job["still"]
    raw = os.path.join(RDIR, "out", f"{jid}.raw.mp4")
    run(base + ["render"] + common[:2] + [raw] + common[2:] + ["--codec=h264", "--crf=18",
        "--audio-bitrate=192k", "--log=error"], cwd=RDIR)
    out = os.path.join(OUTDIR, f"{jid}.mp4")
    run(["ffmpeg", "-v", "error", "-y", "-i", raw, "-c:v", "copy", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", out])
    os.remove(raw)
    os.remove(clip)
    t2 = time.time()
    print(json.dumps({"id": jid, "file": out, "seconds": round(dur, 1), "prep_s": round(t1 - t0),
                      "render_s": round(t2 - t1), "words": len(props["words"]), "zooms": len(props["zooms"])}))
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--vod"); p.add_argument("--start"); p.add_argument("--end")
    p.add_argument("--cam"); p.add_argument("--game"); p.add_argument("--split", type=float, default=0.37)
    p.add_argument("--id"); p.add_argument("--hook")
    p.add_argument("--no-captions", action="store_true"); p.add_argument("--no-zoom", action="store_true")
    p.add_argument("--still", help="write one PNG of the layout instead of rendering")
    p.add_argument("--still-at", default="1.0", help="seconds into the clip for --still")
    p.add_argument("--words", help="whole-VOD transcript JSON from --transcribe-vod (better captions)")
    p.add_argument("--transcribe-vod", help="write a whole-VOD word transcript to this JSON and exit")
    p.add_argument("--plan")
    a = p.parse_args()
    if a.transcribe_vod:
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            wav = os.path.join(d, "a.wav"); wav16k(a.vod, wav)
            json.dump(transcribe(wav), open(a.transcribe_vod, "w"))
        print(a.transcribe_vod); return
    if not os.path.exists(CHROME):
        sys.exit("Headless Chrome missing: run setup.sh")
    if a.plan:
        plan = json.load(open(a.plan))
        base = os.path.dirname(os.path.abspath(a.plan))
        done = []
        for i, k in enumerate(plan.get("clips", plan), 1):
            vod = k.get("vod") or k.get("src")
            k["vod"] = vod if os.path.isabs(vod) else os.path.join(base, vod)
            k.setdefault("id", f"clip{i:02d}")
            if k.get("words") and not os.path.isabs(k["words"]):
                k["words"] = os.path.join(base, k["words"])
            out = render(k)
            done.append({"id": k["id"], "file": out, "title": k.get("title", ""),
                         "hashtags": k.get("hashtags", ""), "start": k.get("start"), "end": k.get("end")})
        json.dump({"clips": done}, open(os.path.join(OUTDIR, "ready_for_post.json"), "w"), indent=2)
        return
    if not a.vod:
        p.error("--vod or --plan is required")
    render({"vod": a.vod, "start": a.start, "end": a.end, "cam": a.cam, "game": a.game, "split": a.split,
            "id": a.id, "hook": a.hook, "captions": not a.no_captions, "zoom": not a.no_zoom, "words": a.words,
            "still": a.still, "still_at": a.still_at})


if __name__ == "__main__":
    main()
