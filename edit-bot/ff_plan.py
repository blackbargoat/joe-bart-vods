#!/usr/bin/env python3
"""edit-bot: no-caption Short straight from the full VOD with ffmpeg, one lossy encode.
Each segment is cut to a lossless intermediate (x264 qp 0 + PCM), then joined, laid out
(facecam on top with lanczos + light sharpen and no zoom, gameplay below), a transparent
1080x1920 overlay (title box) goes on from frame 1, SFX are mixed, audio is two-pass
loudnorm'd to -14 LUFS / -1 dBTP, and the result is encoded once: H.264 High at the
plan's CRF, source fps, AAC 192k 48 kHz.

  python3 -I ff_plan.py plans/joebart-torture.json
"""
import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("EDITBOT_OUT", os.path.join(HERE, "output"))


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def graph(P, loud, audio_only=False):
    fc = []
    mix, n = "[0:a]", 1
    for k, s in enumerate(P.get("sfx", [])):
        ms = int(s["at"] * 1000)
        fc.append(f"[{k + 2}:a]aresample=48000,adelay={ms}|{ms},volume={s.get('volume', 1)}[s{k}]")
        mix += f"[s{k}]"
        n += 1
    tail = f"amix=inputs={n}:normalize=0:duration=first," if n > 1 else ""
    fc.append(f"{mix}{tail}{loud},aresample=48000[a]")
    if not audio_only:
        camh = P.get("cam_h", 608)
        fc += ["[0:v]split[c1][c2]",
               f"[c1]crop={P['cam']},scale=1080:{camh}:flags=lanczos,unsharp=5:5:0.6:5:5:0[cam]",
               f"[c2]crop={P['game']},scale=1080:{1920 - camh}:flags=lanczos[game]",
               "[cam][game]vstack,setsar=1[st]",
               "[st][1:v]overlay=0:0:format=auto,format=yuv420p[v]"]
    return ";".join(fc)


def main(path):
    P = json.load(open(path))
    segs = P["segments"]
    total = sum(b - a for a, b in segs)
    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, f"{P['id']}.mp4")
    with tempfile.TemporaryDirectory(dir=os.path.expanduser("~")) as d:
        parts = []
        for i, (a, b) in enumerate(segs):
            p = os.path.join(d, f"p{i}.mkv")
            run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-i", P["vod"], "-t", f"{b - a:.3f}",
                 "-c:v", "libx264", "-qp", "0", "-preset", "ultrafast", "-c:a", "pcm_s16le", "-ar", "48000", p])
            parts.append(p)
        lst = os.path.join(d, "list.txt")
        open(lst, "w").write("".join(f"file '{p}'\n" for p in parts))
        ins = ["-f", "concat", "-safe", "0", "-i", lst, "-loop", "1", "-i", P["overlay"]]
        for s in P.get("sfx", []):
            ins += ["-i", s["file"]]
        r = subprocess.run(["ffmpeg", "-hide_banner", *ins, "-filter_complex",
                            graph(P, "loudnorm=I=-14:TP=-1:LRA=11:print_format=json", True),
                            "-map", "[a]", "-f", "null", "-"], capture_output=True, text=True).stderr
        j = json.loads(r[r.rindex("{"):r.rindex("}") + 1])
        loud = (f"loudnorm=I=-14:TP=-1:LRA=11:measured_I={j['input_i']}:measured_TP={j['input_tp']}:"
                f"measured_LRA={j['input_lra']}:measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true")
        fps = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=r_frame_rate", "-of", "csv=p=0", P["vod"]],
                             capture_output=True, text=True).stdout.strip()
        run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", graph(P, loud),
             "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}", "-r", fps,
             "-c:v", "libx264", "-profile:v", "high", "-preset", "slow", "-crf", str(P.get("crf", 17)),
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
             "-movflags", "+faststart", out])
    print(json.dumps({"file": out, "seconds": round(total, 2), "loudness_in": j["input_i"]}))


if __name__ == "__main__":
    main(sys.argv[1])
