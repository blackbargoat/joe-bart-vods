# edit-bot tools (for scheduled runs that have no /mnt/project-files)

Everything a run needs to edit one clip with ffmpeg, no captions, title box only, one CRF 17 encode.

## Setup (fresh container, ~1 min)
    apt-get install -y ffmpeg fonts-noto-color-emoji   # if missing
    python3 -m pip install pillow numpy sherpa-onnx    # sherpa-onnx only for word timings
    # word-timing model (public GitHub release, reachable from the cloud):
    curl -sSL https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2 | tar xj -C ~/models

## Per clip
1. Download `<clip_id>.mp4` + `.json` from `https://github.com/blackbargoat/joe-bart-vods/releases/download/pipeline/`.
2. Transcribe for word times: `PARAKEET_DIR=~/models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8 python3 -I -c "import sys,json; sys.path.insert(0,'.'); import make_short as m; json.dump(m.transcribe('full.wav'), open('words.json','w'))"` (full.wav = `ffmpeg -i clip.mp4 -ac 1 -ar 16000 full.wav`).
3. Snap each cut from the plan (sheet edit_notes) to silence: never inside a word in words.json, at the quietest point of the gap.
4. Check footage: blackdetect, frames for the moment, cam box edges (Metro Anomaly VODs: cam 480:270:1437:0).
5. `python3 -I make_title.py "<title text with emoji>" title.png`
6. Write plan.json (see example) and run `python3 -I ff_plan.py plan.json` -> `output/<clip_id>.mp4`.
7. Checks: ffprobe 1080x1920 < 60 s; cropdetect 1080:1920:0:0; blackdetect none.

Example plan.json:
    {"id": "d20261113test_cantfail", "vod": "clip.mp4",
     "segments": [[15.51, 22.95], [38.75, 57.02]],
     "cam": "480:270:1437:0", "cam_h": 608, "game": "888:1080:516:0",
     "overlay": "title.png", "sfx": [{"file": "sfx/whoosh.wav", "at": 7.12, "volume": 1.0}], "crf": 17}
(whoosh "at" = first cut time minus 0.32 s)
