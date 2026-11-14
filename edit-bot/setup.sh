#!/usr/bin/env bash
# Rebuild the Remotion editor on a fresh cloud container (source and models persist in this folder).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
R=/home/user/edit-bot-remotion
mkdir -p "$R/public/fonts" "$R/out"
cp -r "$HERE/remotion/." "$R/"
cp "$HERE/fonts/Montserrat-Black.ttf" "$R/public/fonts/"
(cd "$R" && npm ci --no-audit --no-fund)
python3 -m pip install -q sherpa-onnx==2.0.1 numpy
# Remotion's own Chrome mirror (remotion.media) is blocked here; Chrome for Testing on storage.googleapis.com works.
if [ ! -x /home/user/chrome-dl/chrome-headless-shell-linux64/chrome-headless-shell ]; then
  mkdir -p /home/user/chrome-dl && cd /home/user/chrome-dl
  curl -sSfL -o chs.zip https://storage.googleapis.com/chrome-for-testing-public/157.0.8080.0/linux64/chrome-headless-shell-linux64.zip
  unzip -q chs.zip && rm chs.zip
fi
# Speech-to-text model (Parakeet TDT 0.6B v2 int8, from the sherpa-onnx GitHub releases)
M=/home/user/models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8
if [ ! -f "$M/encoder.int8.onnx" ]; then
  mkdir -p /home/user/models && cd /home/user/models
  curl -sSfL -o p.tar.bz2 https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2
  tar -xjf p.tar.bz2 --no-same-owner && rm p.tar.bz2
fi
echo "edit-bot ready"
